"""Bench profile boundaries, MCU override handling and independent run limit."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_core import sample
from app.config import ROOT, load, save_pin_hash
from app.control import Controller
from app.devices import SerialLink
from app.protocol import ack_matches, command
from app.runtime import Runtime


def bench_sample(**changes):
    return sample(profile='bench', gas_guard=False, bench_run_ms=10000, fault='', **changes)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load(ROOT / 'config/integration.json')

    def settled(self, c, data, vision='CLEAR'):
        c.evaluate(data, 1, vision, 1, 1)
        return c.evaluate(data, 4, vision, 4, 4)

    def test_bench_does_not_claim_gas_calibrated(self):
        self.assertFalse(self.cfg['hardware']['gas_calibrated'])
        result = self.settled(Controller(self.cfg), bench_sample(gas_raw=800))
        self.assertEqual(result['state'], 'NORMAL')
        self.assertNotIn('GAS_RESPONSE', result['reasons'])

    def test_old_ack_is_not_healthy_when_command_producer_stalls(self):
        link = SerialLink(self.cfg['serial'])
        link.connected = True
        link.last_ack = {'accepted': True, 'device_enable': False}
        link.last_ack_at = 10
        # A paused UI can leave no pending commands. The old ACK must expire.
        self.assertTrue(link.snapshot(10.1)['healthy'])
        self.assertFalse(link.snapshot(10 + self.cfg['serial']['ack_seconds'] + 0.1)['healthy'])

    def test_bench_still_blocks_heat_intrusion_and_sensor_fault(self):
        for data, vision, expected in [(bench_sample(temperature=40), 'CLEAR', 'DANGER'),
                                       (bench_sample(), 'UNAUTHORIZED', 'DANGER'),
                                       (bench_sample(sensor_ok=False), 'CLEAR', 'FAULT')]:
            self.assertEqual(self.settled(Controller(self.cfg), data, vision)['state'], expected)

    def test_profile_and_independent_limit_must_match(self):
        for field, value, expected in [('profile', 'production', 'FIRMWARE_PROFILE_MISMATCH'),
                                       ('gas_guard', True, 'BENCH_LIMIT_NOT_CONFIRMED'),
                                       ('bench_run_ms', 0, 'BENCH_LIMIT_NOT_CONFIRMED')]:
            data = bench_sample(); data[field] = value
            self.assertIn(expected, self.settled(Controller(self.cfg), data)['faults'])

    def test_production_calibration_is_still_required(self):
        self.cfg['hardware']['profile'] = 'production'
        self.assertIn('CONFIG_REQUIRED', self.settled(Controller(self.cfg), sample())['faults'])

    def test_mcu_fault_propagates(self):
        data = bench_sample(); data['fault'] = 'BAD_COMMAND'
        self.assertIn('MCU_BAD_COMMAND', self.settled(Controller(self.cfg), data)['faults'])

    def test_ack_accepts_safe_override_but_never_extra_run(self):
        expected = command(5, 'NORMAL', 'CLOSED', False, True, 42)
        ack = dict(expected, type='ack', accepted=True, state='DANGER', vent='OPEN', device_enable=False)
        self.assertTrue(ack_matches(ack, expected))
        ack.update(state='NORMAL', vent='CLOSED', fault='BENCH_LIMIT')
        self.assertTrue(ack_matches(ack, expected))
        ack['session'] = 99
        self.assertFalse(ack_matches(ack, expected))
        expected['device_enable'] = False
        ack.update(session=42, device_enable=True, fault='')
        self.assertFalse(ack_matches(ack, expected))

    def test_initial_pin_persistence_preserves_settings_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'local.json'
            path.write_text('{"camera":{"device":2}}')
            save_pin_hash('test-hash', path)
            self.assertEqual(json.loads(path.read_text())['camera']['device'], 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_runtime_expiry_and_mcu_override_drop_start_latch(self):
        class Camera:
            result = {'count': 0, 'boxes': [], 'inference_ms': 0}
            error = ''
            def __init__(self, *args): pass
            def poll(self, now): return None, now, True
            def close(self): pass
        class Link:
            override = False
            def __init__(self, *args): pass
            def start(self): pass
            def submit(self, *args): pass
            def close(self): pass
            def snapshot(self, now):
                return dict(telemetry=bench_sample(), received_at=now, healthy=True,
                            connected=True, error='', port='FAKE', ack=None,
                            bad_packets=0, reconnects=0, safety_override=self.override)
        with patch('app.runtime.Camera', Camera), patch('app.runtime.SerialLink', Link):
            self.cfg['access']['pin_hash'] = 'configured-test-only'
            r = Runtime(self.cfg)
            try:
                for n in range(40): r.tick(1 + n * 0.1)
                r.access.device_requested = True; r.bench_until = 10
                self.assertTrue(r.tick(9)['decision']['device_enable'])
                self.assertFalse(r.tick(10)['decision']['device_enable'])
                self.assertFalse(r.tick(11)['decision']['device_enable'])
                r.access.device_requested = True; r.bench_until = 20
                r.link.override = True
                self.assertFalse(r.tick(12)['decision']['device_enable'])
            finally:
                r.close()

    def test_actual_mcu_limiter_cannot_be_extended_and_handles_wrap(self):
        compiler = shutil.which('g++')
        if not compiler: self.skipTest('g++ missing')
        source = '''
#include <assert.h>
#include "bench_policy.h"
int main() {
  BenchRunLimit limit;
  assert(!limit.allow(true, 0));
  assert(!limit.allow(false, 0));
  for (unsigned t=100; t<10100; t+=100) assert(limit.allow(true,t));
  assert(!limit.allow(true,10100));
  assert(!limit.allow(true,20000));
  limit.allow(false,20001);
  assert(limit.allow(true,20002));
  limit.trip(); assert(!limit.allow(true,20003));
  limit.allow(false,0xfffffff0U);
  assert(limit.allow(true,0xfffffff0U));
  assert(limit.allow(true,100U));
  assert(!limit.allow(true,10000U));
}
'''
        with tempfile.TemporaryDirectory() as folder:
            cpp = Path(folder) / 'limit.cpp'; binary = Path(folder) / 'limit'
            cpp.write_text(source)
            subprocess.check_call([compiler, '-std=c++11', '-Wall', '-Wextra', '-Werror',
                                   '-I', str(ROOT / 'firmware/mega_controller'), str(cpp), '-o', str(binary)])
            subprocess.check_call([str(binary)])
