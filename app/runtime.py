"""Sensor fusion + supervised access interlock, simulation and local CSV logs."""
import csv
import copy
import datetime
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time

import cv2
import numpy as np

from .access import AccessPolicy, make_pin_hash, verify_pin
from .config import ROOT, save_pin_hash, validate
from .control import Controller
from .devices import Camera, SerialLink
from .identities import IdentityStore
from .protocol import command

SCENARIOS = ('normal', 'intrusion', 'two_people', 'warm', 'hot', 'gas', 'warm_intrusion', 'hot_intrusion', 'gas_intrusion', 'sensor_error', 'comm_error', 'camera_error')


def setup_logging(cfg):
    directory = Path(cfg['logging']['directory'])
    if not directory.is_absolute():
        directory = ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler = RotatingFileHandler(str(directory / 'monitor.log'), maxBytes=2 * 1024 * 1024, backupCount=3)
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    return directory


class CsvLog:
    FIELDS = ['time', 'simulation', 'temperature', 'humidity', 'gas_raw', 'ir_detected',
              'persons', 'access', 'state', 'vent_command', 'device_command', 'ack_device', 'faults', 'reasons']

    def __init__(self, directory):
        self.directory = directory
        self.stream = None
        self.index = 0
        self.prefix = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.open()

    def open(self):
        if self.stream:
            self.stream.close()
        self.stream = (self.directory / ('samples_{}_{}.csv'.format(self.prefix, self.index))).open('w', newline='')
        self.writer = csv.DictWriter(self.stream, fieldnames=self.FIELDS)
        self.writer.writeheader()

    def write(self, snap):
        t = snap['telemetry'] or {}
        row = {k: t.get(k) for k in ['temperature', 'humidity', 'gas_raw', 'ir_detected']}
        row.update(time=datetime.datetime.now().isoformat(), simulation=snap['simulation'],
                   persons=snap['vision']['count'], access=snap['vision']['state'],
                   state=snap['decision']['state'], vent_command=snap['decision']['vent'],
                   device_command=snap['decision']['device_enable'],
                   ack_device=(snap.get('ack') or {}).get('device_enable'),
                   faults='|'.join(snap['decision']['faults']), reasons='|'.join(snap['decision']['reasons']))
        self.writer.writerow(row)
        self.stream.flush()
        status = {k: snap[k] for k in ('simulation', 'profile', 'decision', 'telemetry',
                                      'healthy', 'connected', 'port', 'ack', 'bad_packets',
                                      'reconnects', 'camera_error', 'bench_seconds')}
        status['vision'] = {k: snap['vision'][k] for k in ('state', 'count', 'backend', 'inference_ms')}
        for key in ('selection', 'target_index', 'target_scale', 'target_basis', 'target_recognized'):
            if key in snap['vision']:
                status['vision'][key] = snap['vision'][key]
        status['timestamp'] = row['time']
        status['camera_age_seconds'] = None if snap['camera_at'] is None else max(0, time.monotonic() - snap['camera_at'])
        temporary = self.directory / '.status.json.tmp'
        temporary.write_text(json.dumps(status, indent=2) + '\n')
        os.replace(str(temporary), str(self.directory / 'status.json'))
        if self.stream.tell() > 5 * 1024 * 1024:
            self.index += 1
            self.open()
        files = sorted(self.directory.glob('samples_*.csv'), key=lambda p: p.stat().st_mtime)
        for old in files[:-20]:
            old.unlink()

    def close(self):
        if self.stream:
            self.stream.close()


def simulation_frame(count, width, height):
    frame = np.full((height, width, 3), 28, dtype=np.uint8)
    boxes = []
    for i in range(count):
        x = int(width * (0.35 + 0.3 * i))
        y = height // 3
        cv2.circle(frame, (x, y), 22, (210, 190, 150), -1)
        cv2.rectangle(frame, (x - 25, y + 23), (x + 25, height - 40), (120, 150, 190), -1)
        boxes.append({'box': [x - 30, y - 25, x + 30, height - 35], 'confidence': 1.0})
    # The Tk canvas adds the Korean simulation label using a Hangul-capable font.
    return frame, boxes


class Runtime:
    def __init__(self, cfg, simulation=False, scenario='normal', directory=None, camera_only=False):
        self.cfg, self.simulation, self.scenario = cfg, simulation, scenario
        self.camera_only = camera_only
        self.controller = Controller(cfg, simulation)
        self.access = AccessPolicy(cfg['access'])
        self.camera = None if simulation else Camera(cfg['camera'], cfg['vision'])
        self.link = None if simulation or camera_only else SerialLink(cfg['serial'])
        self.sequence = 0
        self.session = int.from_bytes(os.urandom(4), 'big') or 1
        self.next_command = self.next_log = self.next_frame = 0
        self.last_state = None
        self.last_vision = {'state': 'UNKNOWN', 'count': None, 'boxes': [], 'backend': 'Simulation' if simulation else 'TensorRT GPU FP16', 'inference_ms': 0, 'box': (0, 0, 0, 0)}
        self.last_frame = None
        self.camera_at = None
        self.frame_at = None
        self.last_snapshot = None
        self.csv = CsvLog(directory) if directory else None
        self.log_fault = False
        self.closed = False
        self.failed_pins = 0
        self.pin_locked_until = 0
        self.bench = not simulation and cfg['hardware']['profile'] == 'bench'
        self.ventilation = cfg['hardware']['profile'] == 'ventilation'
        self.fan_stopped = self.ventilation and os.environ.get('MOBLE_RECOVERED_AFTER_CRASH') == '1'
        self.fan_ready_seen = False
        self.bench_until = 0
        self.emergency_stop = False
        self.alarm_ack_key = None
        self.identities = None
        self.enrollment = None
        self.enrollment_message = ''
        if cfg['access']['method'] == 'face':
            database = Path(cfg['vision']['faces']['database'])
            self.identities = IdentityStore(database if database.is_absolute() else ROOT / database,
                                            cfg['vision']['faces']['threshold'])
        if self.link:
            self.link.start()

    def set_scenario(self, value):
        if value not in SCENARIOS:
            raise ValueError('Unknown scenario')
        self.scenario = value

    def authenticate(self, pin):
        now = time.monotonic()
        if self.simulation:
            return
        if now < self.pin_locked_until:
            raise ValueError('Wait before retrying administrator PIN')
        if not verify_pin(pin, self.cfg['access']['pin_hash']):
            self.failed_pins += 1
            if self.failed_pins >= 3:
                self.pin_locked_until = now + 10
                self.failed_pins = 0
            raise ValueError('Invalid PIN; configure it with --set-pin')
        self.failed_pins = 0

    def set_initial_pin(self, pin):
        if self.cfg['access']['pin_hash']:
            raise ValueError('An administrator PIN is already configured')
        stored = make_pin_hash(pin)
        save_pin_hash(stored)
        self.cfg['access']['pin_hash'] = stored

    def require_settings_access(self, pin):
        self.authenticate(pin)
        if not self.ventilation:
            return
        snap = self.last_snapshot
        if (not snap or snap['decision'].get('settings_locked', True)
                or snap['camera_at'] is None
                or (not self.simulation and time.monotonic() - snap['camera_at'] > self.cfg['camera']['stale_seconds'])
                or snap['vision']['state'] not in ('CLEAR', 'AUTHORIZED')
                or (snap['vision']['state'] == 'AUTHORIZED' and not self.access.face_authorized
                    and time.monotonic() >= self.access.granted_until)):
            raise ValueError('설정 잠금: 미승인 인원 또는 확인되지 않은 카메라 상태입니다.')

    def manual_vent(self, target, pin=''):
        self.require_settings_access(pin)
        if self.ventilation and self.last_snapshot['decision'].get('temperature_stop'):
            raise ValueError('온도 자동 정지 중입니다. 27°C 미만이 5초 이상 유지되면 자동 복귀합니다.')
        if self.ventilation and target is None:
            if self.last_snapshot['decision']['faults']:
                raise ValueError('장치 오류가 해제된 뒤 자동 제어로 복귀할 수 있습니다.')
            self.fan_stopped = self.emergency_stop = False
        elif self.emergency_stop:
            raise ValueError('긴급 정지 중입니다. 자동 제어로 복귀한 뒤 유입구를 조작해 주세요.')
        self.controller.manual_vent(target, time.monotonic())
        self.next_command = 0

    def start_enrollment(self, name, pin):
        self.authenticate(pin)
        if self.simulation or self.identities is None:
            raise ValueError('얼굴 등록은 실제 카메라가 연결된 운영 화면에서 진행해 주세요.')
        self.identities.reload()
        name = name.strip()
        if not 1 <= len(name) <= 24 or any(ord(c) < 32 for c in name):
            raise ValueError('등록자 이름은 1~24자로 입력해 주세요.')
        if any(p['name'] == name for p in self.identities.people):
            raise ValueError('같은 이름이 이미 등록돼 있습니다.')
        self.enrollment = {'name': name, 'samples': [], 'last_at': None, 'last_sample_time': 0,
                           'deadline': time.monotonic() + 30}
        self.enrollment_message = '카메라를 정면으로 바라봐 주세요. 한 명만 보여야 합니다.'

    def remove_identity(self, identifier, pin):
        self.authenticate(pin)
        if self.simulation or self.identities is None:
            raise ValueError('등록자 삭제는 실제 운영 화면에서 진행해 주세요.')
        self.identities.remove(identifier)
        self.access.revoke()
        if self.camera:
            self.camera.close()
        self.camera_at = self.frame_at = None
        self.last_snapshot = None

    def collect_enrollment(self, now, fresh):
        if not self.enrollment:
            return
        job = self.enrollment
        if now > job['deadline']:
            self.enrollment_message = '등록 시간이 초과됐습니다. 얼굴을 가까이 비추고 다시 시도해 주세요.'
            self.enrollment = None
            return
        sample = (self.camera.result or {}).get('_enrollment') if self.camera else None
        if fresh and sample is None:
            self.enrollment_message = ('카메라에 한 명만 보이도록 해주세요.' if self.last_vision.get('count', 0) != 1
                                       else '얼굴을 가까이, 정면으로 비춰주세요. 선명한 얼굴을 기다리는 중입니다.')
        if not fresh or sample is None or now - job['last_sample_time'] < 0.3:
            return
        if job['samples'] and float(np.dot(job['samples'][0], sample)) < self.cfg['vision']['faces']['threshold']:
            self.enrollment_message = '등록 중 얼굴이 바뀌었습니다. 한 명만 보이는 상태에서 다시 등록해 주세요.'
            self.enrollment = None
            return
        job['samples'].append(sample)
        job['last_sample_time'] = now
        self.enrollment_message = '{} 등록 중: {}/8'.format(job['name'], len(job['samples']))
        if len(job['samples']) >= 8:
            try:
                self.identities.enroll(job['name'], job['samples'])
                self.enrollment_message = '{} 등록 완료 · 재실행 후에도 유지됩니다.'.format(job['name'])
            except (ValueError, OSError) as exc:
                self.enrollment_message = str(exc)
            self.enrollment = None

    def update_roi(self, roi, pin=''):
        self.require_settings_access(pin)
        candidate = copy.deepcopy(self.cfg)
        candidate['vision']['roi'] = roi
        validate(candidate)
        self.cfg['vision']['roi'] = list(roi)
        self.access.revoke()
        self.last_snapshot = None
        if self.camera:
            self.camera.close()
            self.camera.received_at = None
            self.camera.frame_at = None
            self.camera.frame = None

    def action(self, name, pin=''):
        now = time.monotonic()
        if name == 'stop':
            self.fan_stopped = True
            self.emergency_stop = self.ventilation
            self.controller.manual = None
            self.access.device_requested = False
            self.bench_until = 0
            self.next_command = 0
            return
        self.authenticate(pin)
        if name == 'approve':
            if not self.last_snapshot or self.last_snapshot['vision']['count'] is None or self.last_snapshot['camera_at'] is None or now - self.last_snapshot['camera_at'] > self.cfg['camera']['stale_seconds']:
                raise ValueError('Fresh camera observation required')
            self.access.approve(now)
        elif name == 'revoke':
            self.access.revoke()
        elif name == 'reset':
            if self.ventilation:
                if not self.last_snapshot:
                    raise ValueError('장치 상태가 확인된 뒤 경보를 해제해 주세요.')
                if self.access.count == 0 and self.access.clear_count >= self.cfg['access']['clear_frames']:
                    self.access.reset()
                d = self.last_snapshot['decision']
                self.alarm_ack_key = tuple(sorted(d['faults'] + [r for r in d['reasons'] if r != 'RECOVERY_WAIT']))
            else:
                self.access.reset()
        elif name == 'start':
            if not self.last_snapshot:
                raise ValueError('Wait for device health')
            if self.ventilation:
                self.require_settings_access(pin)
                if self.last_snapshot['decision'].get('temperature_stop'):
                    raise ValueError('온도 자동 정지 중입니다. 정상 온도가 유지될 때까지 기다려 주세요.')
                if self.last_snapshot['decision']['faults'] or self.last_snapshot['decision']['state'] == 'FAULT':
                    raise ValueError('센서·통신 오류가 해제된 뒤 팬을 재개할 수 있습니다.')
                self.fan_stopped = False
                self.emergency_stop = False
            elif self.bench and self.access.device_requested:
                raise ValueError('Already running; STOP before starting another bench run')
            if not self.ventilation:
                self.access.request_start(self.last_snapshot['decision'], self.last_snapshot['vision']['state'])
            if self.bench:
                self.bench_until = now + 10
        else:
            raise ValueError('Unknown action')
        self.next_command = 0
        logging.info('Operator action: %s', name)

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if self.simulation:
            scenario = self.scenario
            count = 2 if scenario == 'two_people' else 1 if scenario in ('intrusion', 'warm_intrusion', 'hot_intrusion', 'gas_intrusion') else 0
            warm_temperature = (self.cfg['thresholds']['temp_warning'] + self.cfg['thresholds']['temp_danger']) / 2
            hot_temperature = self.cfg['thresholds']['temp_danger'] + 0.5
            t = {'v': 1, 'type': 'telemetry', 'seq': self.sequence,
                 'temperature': hot_temperature if scenario in ('hot', 'hot_intrusion') else
                                warm_temperature if scenario in ('warm', 'warm_intrusion') else 26.0, 'humidity': 52.0,
                 'gas_raw': 700 if scenario in ('gas', 'gas_intrusion') else 180, 'ir_detected': False,
                 'sensor_ok': scenario != 'sensor_error', 'hardware_ready': True}
            if scenario == 'sensor_error':
                t['temperature'] = None
            serial_status = {'telemetry': t, 'received_at': now, 'healthy': scenario != 'comm_error',
                             'connected': scenario != 'comm_error', 'error': '', 'port': 'SIMULATION',
                             'ack': None, 'bad_packets': 0, 'reconnects': 0}
            fresh = now >= self.next_frame and scenario != 'camera_error'
            if fresh:
                self.last_frame, boxes = simulation_frame(count, self.cfg['camera']['width'], self.cfg['camera']['height'])
                self.last_vision.update(count=count, boxes=boxes)
                self.camera_at = now
                self.frame_at = now
                self.next_frame = now + 1.0 / self.cfg['camera']['fps']
            if scenario == 'camera_error':
                self.camera_at, self.frame_at, self.last_frame = None, None, None
            camera_error = 'Simulated camera failure' if scenario == 'camera_error' else ''
        else:
            serial_status = self.link.snapshot(now) if self.link else dict(
                telemetry=None, received_at=0, healthy=False, connected=False,
                error='Camera-only preview', port='', ack=None, bad_packets=0, reconnects=0, safety_override=False)
            self.last_frame, self.camera_at, fresh = self.camera.poll(now)
            self.frame_at = getattr(self.camera, 'frame_at', self.camera_at)
            if fresh and self.camera.result:
                self.last_vision.update(self.camera.result)
            camera_error = self.camera.error
        observed = self.last_vision['count'] if self.camera_at is not None and now - self.camera_at <= self.cfg['camera']['stale_seconds'] else None
        if not self.simulation and self.cfg['access']['method'] == 'face':
            index = self.last_vision.get('target_index') if self.last_vision.get('selection') == 'nearest' else None
            access_state = self.access.observe_nearest(observed, index, self.last_vision.get('recognized_ids', []), now, fresh,
                                                      self.cfg['vision']['faces']['confirm_frames'])
        else:
            access_state = self.access.observe(observed, now, fresh)
        self.collect_enrollment(now, fresh)
        # Fresh empty frames are a clearance debounce, not a camera failure.
        # Keep settings locked until the required empty-frame count is reached.
        if self.ventilation and observed == 0 and access_state == 'UNKNOWN':
            access_state = 'CLEARING'
        self.last_vision['state'] = access_state
        if observed is None:
            self.last_vision['count'] = None
        extra = ['LOG_ERROR'] if self.log_fault else []
        if serial_status.get('safety_override'):
            self.access.device_requested = False
            self.bench_until = 0
            if self.ventilation:
                self.fan_stopped = True
        if self.bench and ((self.bench_until and now >= self.bench_until)
                           or (serial_status.get('ack') or {}).get('fault') == 'BENCH_LIMIT'):
            self.access.device_requested = False
            self.bench_until = 0
        if not self.simulation and not self.cfg['access']['pin_hash']:
            extra.append('ADMIN_PIN_REQUIRED')
        decision = self.controller.evaluate(serial_status['telemetry'], serial_status['received_at'],
                                            access_state, self.camera_at, now, serial_status['healthy'], extra)
        if self.ventilation:
            if decision['state'] == 'FAULT' and self.fan_ready_seen:
                self.fan_stopped = True
            elif decision['state'] != 'FAULT':
                self.fan_ready_seen = True
            decision['device_enable'] = (decision['state'] != 'FAULT' and not self.fan_stopped
                                         and not decision['temperature_stop'])
            if not decision['device_enable']:
                decision['fan'] = 'OFF'
            decision['operator_stopped'] = self.fan_stopped
            decision['emergency_stop'] = self.emergency_stop
            if self.emergency_stop:
                decision.update(vent='CLOSED', buzzer=False, mode='STOP')
            elif decision['temperature_stop']:
                decision.update(vent='CLOSED', buzzer=False, mode='TEMP_STOP')
            key = tuple(sorted(decision['faults'] + [r for r in decision['reasons'] if r != 'RECOVERY_WAIT']))
            if key != self.alarm_ack_key:
                self.alarm_ack_key = None
            decision['alarm_acknowledged'] = bool(key) and key == self.alarm_ack_key
            if decision['alarm_acknowledged']:
                decision['buzzer'] = False
        else:
            decision['device_enable'] = self.access.device_enabled(decision, access_state)
        if decision['state'] != self.last_state:
            logging.info('State -> %s; faults=%s reasons=%s', decision['state'], decision['faults'], decision['reasons'])
            self.last_state = decision['state']
        if now >= self.next_command:
            self.sequence = (self.sequence + 1) & 0x7fffffff
            msg = command(self.sequence, decision['state'], decision['vent'], decision['buzzer'], decision['device_enable'], self.session,
                          fan=decision.get('fan'), settings_locked=decision.get('settings_locked', False),
                          access_alert=decision.get('access_alert', False),
                          vent_mode=self.controller.manual or 'AUTO', emergency_stop=self.emergency_stop,
                          alarm_acknowledged=decision.get('alarm_acknowledged', False),
                          temperature_stop=decision.get('temperature_stop', False))
            if self.link:
                self.link.submit(msg)
            self.next_command = now + self.cfg['control']['command_seconds']
        if self.simulation:
            serial_status['ack'] = dict(accepted=True, state=decision['state'], vent=decision['vent'], device_enable=decision['device_enable'], simulated=True)
            if self.ventilation:
                serial_status['ack'].update(fan=decision['fan'], profile='ventilation')
        snap = dict(serial_status, simulation=self.simulation, decision=decision, vision=dict(self.last_vision),
                    frame=self.last_frame, camera_error=camera_error, camera_at=self.camera_at, frame_at=self.frame_at,
                    grant_seconds=max(0, self.access.granted_until - now))
        snap['vision'].pop('_enrollment', None)
        snap['face_authorized'] = self.access.face_authorized
        snap['enrollment_message'] = self.enrollment_message
        snap['enrollment_active'] = self.enrollment is not None
        snap['profile'] = self.cfg['hardware']['profile']
        snap['bench_seconds'] = max(0, self.bench_until - now) if self.bench else None
        self.last_snapshot = snap
        if self.csv and now >= self.next_log:
            try:
                self.csv.write(snap)
                self.log_fault = False
            except OSError as exc:
                logging.error('CSV write failed: %s', exc)
                self.log_fault = True
            self.next_log = now + self.cfg['logging']['csv_seconds']
        return snap

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.link:
            self.sequence += 1
            self.link.submit(command(self.sequence, 'FAULT', 'CLOSED' if self.emergency_stop else 'SAFE', True, False, self.session,
                                     fan='OFF' if self.ventilation else None, settings_locked=True,
                                     emergency_stop=self.emergency_stop))
            # Commands are sent after the next 500ms telemetry slot.
            time.sleep(0.7)
            self.link.close()
        if self.camera:
            self.camera.close()
        if self.csv:
            self.csv.close()
