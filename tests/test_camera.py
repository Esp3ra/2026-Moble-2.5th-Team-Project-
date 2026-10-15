"""Prove that a hung capture process is killed and restarted without hardware."""
from pathlib import Path
import sys
import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.vendor'))
from app.devices import Camera, _camera_capture


def capture_then_hang(cfg, frames, stopped, vision):
    stamp = time.monotonic()
    frames.put((stamp, 'test-frame', stamp, {'count': 0, 'boxes': []}))
    # Deliberately ignore the stop Event, as a wedged native driver would.
    time.sleep(20)


def preview_with_frozen_detection(cfg, frames, stopped, vision):
    detected_at = time.monotonic()
    while not stopped.is_set():
        try:
            frames.put_nowait((time.monotonic(), 'preview', detected_at, {'count': 1, 'boxes': []}))
        except queue.Full:
            pass
        stopped.wait(0.01)


class CameraRecoveryTests(unittest.TestCase):
    def test_cold_first_result_does_not_end_startup_grace(self):
        camera = Camera({'stale_seconds': 3, 'retry_seconds': 2, 'startup_seconds': 30}, {})
        camera.process, camera.frames, camera.stopped = Mock(), queue.Queue(), Mock()
        camera.process.is_alive.return_value = True
        camera.started_at = 100
        camera.frames.put((110, 'preview', 103, {'count': 1}))
        _, received, _ = camera.poll(110)
        self.assertEqual(received, 103)  # Never relabel old AI data as current.
        self.assertFalse(camera.ready)
        camera.process.terminate.assert_not_called()
        camera.frames.put((111, 'preview', 110.9, {'count': 1}))
        camera.poll(111)
        self.assertTrue(camera.ready)
        with patch.object(camera, 'close') as close:
            camera.poll(114.1)
            close.assert_called_once_with()  # The normal 3s watchdog remains.

    def test_only_stale_first_results_still_exhaust_startup_grace(self):
        camera = Camera({'stale_seconds': 3, 'retry_seconds': 2, 'startup_seconds': 30}, {})
        camera.process, camera.frames, camera.stopped = Mock(), queue.Queue(), Mock()
        camera.process.is_alive.return_value = True
        camera.started_at = 100
        camera.frames.put((131, 'preview', 103, {'count': 1}))
        with patch.object(camera, 'close') as close:
            camera.poll(131)
            close.assert_called_once_with()

    def test_preview_cannot_keep_stalled_inference_healthy(self):
        camera = Camera({'stale_seconds': 0.25, 'retry_seconds': 0.1, 'startup_seconds': 10}, {})
        fresh_count = 0
        preview_stamps = set()
        try:
            with patch('app.devices._camera_capture', preview_with_frozen_detection):
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    _, _, fresh = camera.poll(time.monotonic())
                    fresh_count += int(fresh)
                    if camera.frame_at is not None:
                        preview_stamps.add(camera.frame_at)
                    if camera.generation >= 2:
                        self.assertEqual(fresh_count, 1)
                        self.assertGreater(len(preview_stamps), 3)
                        self.assertIsNone(camera.received_at)
                        return
                    time.sleep(0.02)
                self.fail('Live preview incorrectly masked frozen inference')
        finally:
            camera.close()

    def test_slow_inference_does_not_block_capture(self):
        class Capture:
            def __init__(self, *args): pass
            def isOpened(self): return True
            def set(self, *args): return True
            def read(self):
                time.sleep(0.01)
                return True, object()
            def release(self): pass
        class Detector:
            def __init__(self, *args): pass
            def inspect(self, frame):
                time.sleep(0.08)
                return {'count': 0, 'boxes': []}
            def close(self): pass
        frames, stopped = queue.Queue(maxsize=1), threading.Event()
        records = []
        cfg = {'device': 0, 'width': 640, 'height': 480, 'fps': 30}
        with patch('app.devices.cv2.VideoCapture', Capture), patch('app.inference.PersonDetector', Detector):
            worker = threading.Thread(target=_camera_capture, args=(cfg, frames, stopped, {}))
            worker.start()
            try:
                until = time.monotonic() + 0.6
                while time.monotonic() < until:
                    try: records.append(frames.get(timeout=0.03))
                    except queue.Empty: pass
            finally:
                stopped.set(); worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        detections = {p[2] for p in records if p[2] is not None}
        self.assertGreaterEqual(len(records), 20)
        self.assertGreaterEqual(len(detections), 2)
        self.assertGreater(len(records), 2 * len(detections))
        self.assertTrue(all(p[2] is None or p[2] <= p[0] for p in records))

    def test_hung_process_restart(self):
        camera = Camera({'stale_seconds': 0.25, 'retry_seconds': 0.1, 'startup_seconds': 10}, {})
        saw_frame = False
        old_pid = None
        try:
            with patch('app.devices._camera_capture', capture_then_hang):
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    frame, received, fresh = camera.poll(time.monotonic())
                    if fresh:
                        saw_frame = True
                        old_pid = old_pid or camera.process.pid
                    if camera.generation >= 2 and camera.process and camera.process.pid != old_pid:
                        self.assertTrue(saw_frame)
                        return
                    time.sleep(0.04)
                self.fail('Capture worker did not recover from a stalled read')
        finally:
            camera.close()


if __name__ == '__main__':
    unittest.main()
