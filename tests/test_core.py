import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.vendor'))
from app.access import AccessPolicy, make_pin_hash, verify_pin
from app.config import load, validate
from app.control import Controller
from app.inference import decode_yolo
from app.protocol import Framer, MAX_LINE, command, encode, telemetry_valid
from app.runtime import Runtime
import numpy as np


def sample(seq=1, **changes):
    obj = {'v': 1, 'type': 'telemetry', 'seq': seq, 'temperature': 26.0, 'humidity': 50.0,
           'gas_raw': 180, 'ir_detected': False, 'sensor_ok': True, 'hardware_ready': True}
    obj.update(changes)
    return obj


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load()
        self.controller = Controller(self.cfg, True)

    def evaluate(self, now, data=None, vision='CLEAR', **kw):
        return self.controller.evaluate(data or sample(), now, vision, now, now, **kw)

    def normal(self):
        self.evaluate(1)
        return self.evaluate(3.1)

    def test_startup_recovery_delay(self):
        self.assertEqual(self.evaluate(1)['state'], 'FAULT')
        self.assertEqual(self.evaluate(2)['state'], 'FAULT')
        self.assertEqual(self.evaluate(3.1)['state'], 'NORMAL')

    def test_intrusion_immediately_alarms(self):
        self.normal()
        d = self.evaluate(4, vision='UNAUTHORIZED')
        self.assertEqual(d['state'], 'DANGER')
        self.assertTrue(d['buzzer'])
        self.assertIn('UNAUTHORIZED_PERSON', d['reasons'])

    def test_gas_hysteresis_and_recovery(self):
        self.normal()
        self.assertEqual(self.evaluate(4, sample(gas_raw=650))['state'], 'DANGER')
        self.assertEqual(self.evaluate(5, sample(gas_raw=570))['state'], 'DANGER')
        self.assertEqual(self.evaluate(6, sample(gas_raw=500))['state'], 'DANGER')
        self.assertEqual(self.evaluate(8.1, sample(gas_raw=500))['state'], 'WARNING')

    def test_stale_samples_never_normal(self):
        self.normal()
        d = self.controller.evaluate(sample(), 1, 'CLEAR', 7, 7)
        self.assertEqual(d['state'], 'FAULT')
        self.assertIn('COMM_ERROR', d['faults'])

    def test_camera_failure_blocks(self):
        self.normal()
        d = self.controller.evaluate(sample(), 4, 'CLEAR', None, 4)
        self.assertEqual(d['state'], 'FAULT')
        self.assertIn('CAMERA_ERROR', d['faults'])

    def test_nan_sensor_is_fault(self):
        self.normal()
        d = self.evaluate(4, sample(temperature=float('nan')))
        self.assertIn('SENSOR_ERROR', d['faults'])

    def test_manual_cannot_close_danger_vent(self):
        self.normal()
        self.controller.manual_vent('CLOSED', 4)
        d = self.evaluate(4, sample(temperature=45))
        self.assertEqual(d['vent'], 'OPEN')

    def test_environment_danger_ventilates_during_comm_fault(self):
        self.normal()
        d = self.evaluate(4, sample(gas_raw=700), comm_ok=False)
        self.assertEqual(d['state'], 'FAULT')
        self.assertEqual(d['vent'], 'OPEN')

    def test_live_unconfigured_hardware_blocked(self):
        c = Controller(self.cfg, False)
        d = c.evaluate(sample(), 1, 'CLEAR', 1, 1)
        self.assertIn('CONFIG_REQUIRED', d['faults'])


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.access = AccessPolicy(load()['access'])

    def test_latched_intrusion_cannot_clear_itself(self):
        self.assertEqual(self.access.observe(1, 1), 'UNAUTHORIZED')
        for n in range(10):
            self.assertEqual(self.access.observe(0, n + 2), 'UNAUTHORIZED')
        self.access.reset()
        self.assertEqual(self.access.observe(0, 20), 'CLEAR')

    def test_approval_expiration_alarms(self):
        self.access.observe(1, 1)
        self.access.approve(2)
        self.assertEqual(self.access.observe(1, 3), 'AUTHORIZED')
        self.assertEqual(self.access.observe(1, 33), 'UNAUTHORIZED')

    def test_second_person_revokes_approval(self):
        self.access.observe(1, 1)
        self.access.approve(2)
        self.assertEqual(self.access.observe(2, 3), 'UNAUTHORIZED')
        self.assertEqual(self.access.granted_until, 0)

    def test_camera_fault_revokes_and_prevents_restart(self):
        self.access.observe(1, 1)
        self.access.approve(2)
        self.access.device_requested = True
        self.access.observe(None, 3)
        self.assertFalse(self.access.device_requested)

    def test_start_requires_safe_state(self):
        with self.assertRaises(ValueError):
            self.access.request_start({'state': 'DANGER', 'target': 'DANGER'}, 'AUTHORIZED')

    def test_clear_requires_distinct_frames(self):
        self.access.observe(0, 1)
        for _ in range(20):
            self.assertEqual(self.access.observe(0, 2, fresh=False), 'UNKNOWN')

    def test_pin_hash(self):
        stored = make_pin_hash('946237')
        self.assertTrue(verify_pin('946237', stored))
        self.assertFalse(verify_pin('000000', stored))
        self.assertFalse(verify_pin('946237', ''))


class ProtocolTests(unittest.TestCase):
    def test_split_packets_and_resync(self):
        f = Framer()
        data = encode(sample())
        self.assertEqual(f.feed(data[:15]), [])
        self.assertEqual(f.feed(data[15:])[0]['temperature'], 26)
        packets = f.feed(b'bad json\n' + b'x' * (MAX_LINE + 1) + b'\n' + data)
        self.assertEqual(len(packets), 1)
        self.assertEqual(f.errors, 2)

    def test_invalid_values_rejected(self):
        for bad in [float('nan'), True, 999, '26']:
            self.assertFalse(telemetry_valid(sample(temperature=bad)))
        self.assertTrue(telemetry_valid(sample(temperature=None, sensor_ok=False)))

    def test_missing_values_rejected(self):
        obj = sample()
        del obj['gas_raw']
        self.assertFalse(telemetry_valid(obj))

    def test_interlock_command_defaults_off(self):
        obj = command(1, 'NORMAL', 'CLOSED', False)
        self.assertFalse(obj['device_enable'])
        self.assertEqual(json.loads(encode(obj)), obj)


class ConfigAndInferenceTests(unittest.TestCase):
    def test_invalid_roi_and_thresholds(self):
        for mutate in [lambda c: c['vision'].update(roi=[0.8, 0, 0.5, 1]), lambda c: c['thresholds'].update(temp_warning=42, temp_danger=38)]:
            cfg = load()
            mutate(cfg)
            with self.assertRaises(ValueError):
                validate(cfg)

    def test_yolo_nms_and_person_class_filter(self):
        output = np.zeros((1, 4, 85), dtype=np.float32)
        output[0, 0, :4] = [100, 100, 50, 100]
        output[0, 1, :4] = [101, 100, 50, 100]
        output[0, :2, 4:6] = 0.9
        output[0, 2, 4] = 0.9
        output[0, 2, 7] = 0.95  # Non-person class.
        output[0, 3, 0] = float('nan')
        boxes = decode_yolo(output, 0.6, 1, 0, 0, (0, 0, 640, 640))
        self.assertEqual(len(boxes), 1)
        self.assertGreater(boxes[0]['confidence'], 0.8)

    def test_full_simulated_intrusion_and_recovery(self):
        runtime = Runtime(load(), True)
        try:
            for n in range(35):
                snap = runtime.tick(1 + n * 0.11)
            self.assertEqual(snap['decision']['state'], 'NORMAL')
            runtime.access.request_start(snap['decision'], snap['vision']['state'])
            snap = runtime.tick(5)
            self.assertTrue(snap['decision']['device_enable'])
            runtime.set_scenario('intrusion')
            snap = runtime.tick(5.2)
            self.assertEqual(snap['decision']['state'], 'DANGER')
            self.assertTrue(snap['decision']['buzzer'])
            self.assertFalse(snap['decision']['device_enable'])
            runtime.set_scenario('normal')
            for n in range(12):
                snap = runtime.tick(6 + n * 0.11)
            self.assertEqual(snap['decision']['state'], 'DANGER')
            runtime.access.reset()
            runtime.tick(8)
            snap = runtime.tick(10.1)
            self.assertEqual(snap['decision']['state'], 'NORMAL')
            self.assertFalse(snap['decision']['device_enable'])
        finally:
            runtime.close()


if __name__ == '__main__':
    unittest.main()
