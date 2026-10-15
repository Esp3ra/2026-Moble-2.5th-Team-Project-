"""Recoverable USB serial and killable camera capture workers."""
import glob
import logging
import multiprocessing as mp
import os
import queue
import threading
import time

import cv2
import serial

from .protocol import Framer, ack_matches, automatic_temperature_stop, encode, telemetry_valid

LOG = logging.getLogger(__name__)


class SerialLink:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.outbox = queue.Queue(maxsize=1)
        self.thread = None
        self.connected = False
        self.telemetry = None
        self.received_at = 0
        self.last_ack = None
        self.last_ack_at = 0
        self.pending = {}
        self.error = 'Waiting for Arduino'
        self.port = ''
        self.bad_packets = 0
        self.reconnects = 0
        self.safety_override = False

    def start(self):
        self.thread = threading.Thread(target=self._run, name='serial', daemon=True)
        self.thread.start()

    def submit(self, command):
        try:
            self.outbox.get_nowait()
        except queue.Empty:
            pass
        try:
            self.outbox.put_nowait(command)
        except queue.Full:
            pass

    def snapshot(self, now):
        with self.lock:
            oldest = min((entry[0] for entry in self.pending.values()), default=now)
            healthy = (self.connected and self.last_ack is not None
                       and now - self.last_ack_at <= self.cfg['ack_seconds']
                       and now - oldest <= self.cfg['ack_seconds'])
            return {'telemetry': dict(self.telemetry) if self.telemetry else None,
                    'received_at': self.received_at, 'healthy': healthy,
                    'connected': self.connected, 'error': self.error, 'port': self.port,
                    'ack': dict(self.last_ack) if self.last_ack else None,
                    'safety_override': self.safety_override,
                    'bad_packets': self.bad_packets, 'reconnects': self.reconnects}

    def _resolve_port(self):
        if self.cfg['port'] != 'auto':
            return self.cfg['port']
        # Fail explicitly when several serial devices exist; never guess a board.
        paths = glob.glob('/dev/serial/by-id/*')
        if not paths:
            paths = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
        unique = sorted(set(os.path.realpath(p) for p in paths))
        if len(unique) != 1:
            raise IOError('Expected one serial device, found {}; set serial.port'.format(len(unique)))
        return unique[0]

    def _run(self):
        while not self.stop_event.is_set():
            handle = None
            try:
                port = self._resolve_port()
                handle = serial.Serial(port, self.cfg['baud'], timeout=0.1, write_timeout=0.5, exclusive=True)
                framer = Framer()
                opened = time.monotonic()
                last_seq = None
                with self.lock:
                    self.connected, self.port, self.error = True, port, ''
                    self.telemetry, self.last_ack = None, None
                    self.received_at = self.last_ack_at = 0
                    self.pending.clear()
                    self.safety_override = False
                    self.reconnects += 1
                LOG.info('Serial connected: %s', port)
                while not self.stop_event.is_set():
                    data = handle.read(min(handle.in_waiting or 1, 4096))
                    now = time.monotonic()
                    old_errors = framer.errors
                    packets = framer.feed(data)
                    telemetry_received = False
                    if framer.errors != old_errors:
                        LOG.warning('Invalid serial framing: %d new rejected line(s)', framer.errors - old_errors)
                    with self.lock:
                        self.bad_packets += framer.errors - old_errors
                    for packet in packets:
                        if packet.get('type') == 'telemetry' and telemetry_valid(packet):
                            seq = packet['seq']
                            if last_seq is not None and not 0 < ((seq - last_seq) & 0xffffffff) < 0x80000000:
                                continue
                            last_seq = seq
                            telemetry_received = True
                            with self.lock:
                                self.telemetry, self.received_at = packet, now
                        elif packet.get('type') == 'ack':
                            seq = packet.get('seq')
                            with self.lock:
                                expected = self.pending.get(seq) if isinstance(seq, int) and not isinstance(seq, bool) else None
                                if expected and ack_matches(packet, expected[1]):
                                    self.last_ack, self.last_ack_at = packet, now
                                    self.safety_override = (expected[1]['device_enable'] and not packet['device_enable']
                                                            and not automatic_temperature_stop(packet))
                                    self.pending = {k: v for k, v in self.pending.items() if v[0] > expected[0]}
                                else:
                                    self.bad_packets += 1
                                    LOG.warning('Rejected ACK: seq=%r session=%r accepted=%r state=%r vent=%r run=%r pending=%s',
                                                seq, packet.get('session'), packet.get('accepted'), packet.get('state'),
                                                packet.get('vent'), packet.get('device_enable'), bool(expected))
                        else:
                            with self.lock:
                                self.bad_packets += 1
                            LOG.warning('Rejected serial packet: type=%r seq=%r', packet.get('type'), packet.get('seq'))
                    try:
                        # No writes while the Mega bootloader is starting, or
                        # between telemetry slots during DHT interrupt masking.
                        if not telemetry_received:
                            raise queue.Empty
                        message = self.outbox.get_nowait()
                        handle.write(encode(message))
                        with self.lock:
                            self.pending[message['seq']] = (now, message)
                    except queue.Empty:
                        pass
                    with self.lock:
                        sample_time = self.received_at or opened
                        ack_expired = bool(self.pending) and now - min(v[0] for v in self.pending.values()) > self.cfg['ack_seconds']
                    if now - sample_time > self.cfg['stale_seconds']:
                        raise IOError('Telemetry timeout ({:.1f}s)'.format(now - sample_time))
                    if ack_expired:
                        raise IOError('Command ACK timeout')
            except (OSError, serial.SerialException, ValueError) as exc:
                with self.lock:
                    self.error, self.connected = str(exc), False
                LOG.warning('Serial retry: %s', exc)
            finally:
                if handle:
                    handle.close()
                with self.lock:
                    self.connected = False
            self.stop_event.wait(self.cfg['retry_seconds'])

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)


def _camera_capture(cfg, frames, stopped, vision):
    """Capture continuously; infer on the latest frame in a separate thread.

    Preview timestamps never stand in for detection timestamps. Both remain
    inside a killable process so a stalled camera/CUDA call can be recovered.
    """
    from .inference import PersonDetector
    cap = None
    finished, failed = threading.Event(), threading.Event()
    changed = threading.Condition()
    latest = [None]
    detection = [None, None]
    inference = None

    def detect():
        detector = None
        recognizer = None
        previous = None
        try:
            # Construct and use TensorRT/CUDA on the same thread.
            detector = PersonDetector(vision)
            if vision.get('faces', {}).get('enabled'):
                from .faces import FaceRecognizer
                recognizer = FaceRecognizer(vision['faces'])
            while not stopped.is_set() and not finished.is_set():
                with changed:
                    changed.wait_for(lambda: finished.is_set() or (latest[0] is not None and latest[0][0] != previous), timeout=0.1)
                    if finished.is_set() or stopped.is_set():
                        break
                    if latest[0] is None or latest[0][0] == previous:
                        continue
                    stamp, frame = latest[0]
                started = time.monotonic()
                result = detector.inspect(frame)
                if recognizer:
                    result.update(recognizer.inspect(frame, result['boxes'], result['box']))
                    result['inference_ms'] = (time.monotonic() - started) * 1000
                with changed:
                    detection[:] = [stamp, result]
                previous = stamp
        except Exception as exc:
            failed.set()
            LOG.exception('Inference thread: %s', exc)
        finally:
            if detector:
                detector.close()
            if recognizer:
                recognizer.close()

    try:
        cap = cv2.VideoCapture(cfg['device'], cv2.CAP_V4L2)
        if not cap.isOpened():
            return
        if cfg.get('fourcc'):
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cfg['fourcc']))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg['width'])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg['height'])
        cap.set(cv2.CAP_PROP_FPS, cfg.get('capture_fps', cfg['fps']))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        inference = threading.Thread(target=detect, name='inference', daemon=True)
        inference.start()
        failures = 0
        while not stopped.is_set() and not failed.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                if failures >= 5:
                    return
                stopped.wait(0.1)
                continue
            failures = 0
            captured_at = time.monotonic()
            with changed:
                latest[0] = (captured_at, frame)
                detected_at, result = detection
                changed.notify()
            try:
                frames.put_nowait((captured_at, frame, detected_at, result))
            except queue.Full:
                pass
    except Exception as exc:
        LOG.exception('Camera/inference worker: %s', exc)
    finally:
        finished.set()
        with changed:
            changed.notify_all()
        if cap:
            cap.release()
        if inference:
            inference.join(timeout=0.2)


class Camera:
    def __init__(self, cfg, vision):
        self.cfg = cfg
        self.vision = vision
        self.ctx = mp.get_context('spawn')
        self.process = None
        self.frames = None
        self.stopped = None
        self.started_at = 0
        self.ready = False
        self.received_at = None
        self.frame_at = None
        self.next_start = 0
        self.frame = None
        self.result = None
        self.generation = 0
        self.error = 'Waiting for camera'

    def poll(self, now):
        fresh = False
        if self.process:
            try:
                while True:
                    self.frame_at, self.frame, detected_at, result = self.frames.get_nowait()
                    if detected_at is not None and detected_at != self.received_at:
                        self.received_at, self.result = detected_at, result
                        fresh = True
                        self.error = ''
            except queue.Empty:
                pass
            # A cold GPU can return an already-old first inference. Keep the
            # startup grace until a genuinely current inference arrives;
            # otherwise repeated model reloads can prevent recovery forever.
            # Runtime still sees the original timestamp and blocks old data.
            if self.received_at is not None and now - self.received_at <= self.cfg['stale_seconds']:
                self.ready = True
            age = now - (self.received_at if self.ready else self.started_at)
            timeout = self.cfg['stale_seconds'] if self.ready else self.cfg['startup_seconds']
            if not self.process.is_alive() or age > timeout:
                reason = 'worker exited' if not self.process.is_alive() else 'inference timeout ({:.1f}s)'.format(age)
                self.close()
                self.received_at = None
                self.frame_at = None
                self.frame = None
                self.result = None
                fresh = False
                self.error = 'Camera unavailable; retrying'
                self.next_start = now + self.cfg['retry_seconds']
                LOG.warning('%s: %s', self.error, reason)
        if not self.process and now >= self.next_start:
            # Allow one packet being read plus the next captured frame. A
            # single slot dropped frames while the previous image was in IPC.
            self.frames = self.ctx.Queue(maxsize=2)
            self.stopped = self.ctx.Event()
            self.process = self.ctx.Process(target=_camera_capture, args=(self.cfg, self.frames, self.stopped, self.vision), daemon=True)
            self.process.start()
            self.started_at = now
            self.generation += 1
        return self.frame, self.received_at, fresh

    def close(self):
        if self.process:
            self.stopped.set()
            self.process.join(timeout=0.2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=0.5)
            self.frames.cancel_join_thread()
            self.frames.close()
            self.process = None
        self.received_at = self.frame_at = None
        self.frame = self.result = None
        self.ready = False
