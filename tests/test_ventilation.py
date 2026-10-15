"""Ventilation priorities, real permission guards, STOP and firmware contracts."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from test_core import sample
from app.access import make_pin_hash
from app.config import ROOT, load
from app.control import Controller
from app.protocol import ack_matches, automatic_temperature_stop, command, encode
from app.runtime import Runtime


def ventilation_sample(**changes):
    data = sample(profile='ventilation', policy_rev=6, gas_mode='raw_demo',
                  temperature_stop=False, local_temperature_stop=False, temp_restart_ms=5000,
                  gas_guard=False, bench_run_ms=0, temp_trip=27, gas_trip=250,
                  temp_release=27, temp_red=28, gas_release=210, fault='')
    data.update(changes)
    return data


class VentilationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load(ROOT / 'config/ventilation.json')

    def evaluate(self, controller, now, vision='CLEAR', **data):
        return controller.evaluate(ventilation_sample(**data), now, vision, now, now)

    def settled(self, vision='CLEAR', **data):
        c = Controller(self.cfg)
        self.evaluate(c, 1, vision, **data)
        return c, self.evaluate(c, 4, vision, **data)

    def test_priority_matrix_at_inclusive_thresholds(self):
        for intrusion in (False, True):
            for temp, gas, environment in [(26.9, 249, False), (27, 180, True),
                                            (26, 250, True), (40, 700, True)]:
                with self.subTest(intrusion=intrusion, temp=temp, gas=gas):
                    _, d = self.settled('UNAUTHORIZED' if intrusion else 'AUTHORIZED',
                                        temperature=temp, gas_raw=gas)
                    self.assertEqual(d['state'], 'WARNING' if environment else 'DANGER' if intrusion else 'NORMAL')
                    stopped = temp >= 28
                    self.assertEqual(d['vent'], 'OPEN' if environment and not stopped else 'CLOSED')
                    self.assertEqual(d['fan'], 'OFF' if stopped else 'HIGH' if environment else 'LOW')
                    self.assertEqual(d['settings_locked'], intrusion)
                    self.assertEqual(d['access_alert'], intrusion)
                    self.assertEqual(d['buzzer'], environment and not stopped)

    def test_environment_immediately_overrides_intrusion_and_recovers_to_red(self):
        c, _ = self.settled('UNAUTHORIZED')
        self.assertEqual(self.evaluate(c, 5, 'UNAUTHORIZED', temperature=27)['state'], 'WARNING')
        self.assertEqual(self.evaluate(c, 6, 'UNAUTHORIZED', temperature=27)['state'], 'WARNING')
        d = self.evaluate(c, 7, 'UNAUTHORIZED', temperature=26.9)
        self.assertEqual((d['state'], d['vent'], d['fan']), ('DANGER', 'CLOSED', 'LOW'))
        self.assertTrue(d['settings_locked'])
        self.assertFalse(d['buzzer'])

    def test_temperature_stop_waits_below_27_for_five_seconds(self):
        c, _ = self.settled('AUTHORIZED')
        for now, temp, fan in [(5,26.9,'LOW'), (6,27,'HIGH'), (7,27.9,'HIGH'),
                               (8,28,'OFF'), (9,29,'OFF'), (10,27.9,'OFF'),
                               (11,27,'OFF'), (12,26.9,'OFF'), (16.9,26.9,'OFF'), (17,26.9,'LOW')]:
            d = self.evaluate(c, now, 'AUTHORIZED', temperature=temp)
            self.assertEqual(d['temperature_danger'], temp >= 28)
            self.assertEqual(d['fan'], fan)
            self.assertEqual(d['temperature_stop'], fan == 'OFF')
            self.assertEqual(d['buzzer'], fan == 'HIGH')
            self.assertNotIn('RECOVERY_WAIT', d['reasons'])

    def test_cooling_below_27_does_not_clear_gas_alarm_or_access_lock(self):
        c, _ = self.settled('UNAUTHORIZED', temperature=28, gas_raw=250)
        d = self.evaluate(c, 5, 'UNAUTHORIZED', temperature=26.9, gas_raw=220)
        self.assertEqual(d['state'], 'WARNING')
        self.assertFalse(d['temperature_danger'])
        self.assertEqual(d['fan'], 'OFF')
        d = self.evaluate(c, 10, 'UNAUTHORIZED', temperature=26.9, gas_raw=220)
        self.assertTrue(d['buzzer'])
        self.assertEqual(d['fan'], 'HIGH')
        self.assertTrue(d['settings_locked'])

    def test_temperature_recovery_window_restarts_on_heat_invalid_or_stale_data(self):
        for fault in ('heat', 'sensor', 'stale'):
            c, _ = self.settled(temperature=28)
            self.evaluate(c, 5, temperature=26)
            if fault == 'heat': self.evaluate(c, 8, temperature=27)
            elif fault == 'sensor': self.evaluate(c, 8, temperature=None, sensor_ok=False)
            else: c.evaluate(ventilation_sample(temperature=26), 0, 'CLEAR', 8, 8)
            for now in (9, 12, 13.9):
                self.assertEqual(self.evaluate(c, now, temperature=26)['fan'], 'OFF')
            self.assertFalse(self.evaluate(c, 14, temperature=26)['temperature_stop'])

    def test_mcu_latch_cannot_be_cleared_by_cool_host_sample(self):
        c, _ = self.settled(temperature=26, temperature_stop=True, local_temperature_stop=True)
        self.assertEqual(self.evaluate(c, 10, temperature=26, temperature_stop=True, local_temperature_stop=True)['fan'], 'OFF')
        # An echoed host stop must not feed back into its own recovery latch.
        self.assertEqual(self.evaluate(c, 11, temperature=26, temperature_stop=True, local_temperature_stop=False)['fan'], 'LOW')

    def test_automatic_stop_restarts_without_pin_but_preserves_manual_stop(self):
        for manual_stop in (False, True):
            r, now = self.runtime_settled('normal')
            r.set_scenario('hot')
            d = r.tick(now + 1)['decision']
            self.assertEqual((d['fan'],d['vent'],d['buzzer']),('OFF','CLOSED',False))
            self.assertFalse(d['operator_stopped'])
            with self.assertRaises(ValueError): r.action('start')
            with self.assertRaises(ValueError): r.manual_vent('OPEN')
            with self.assertRaises(ValueError): r.manual_vent(None)
            if manual_stop: r.action('stop')
            r.set_scenario('normal')
            for n in range(61): d = r.tick(now + 2 + n * .1)['decision']
            self.assertFalse(d['temperature_stop'])
            self.assertEqual(d['fan'],'OFF' if manual_stop else 'LOW')
            self.assertEqual(d['emergency_stop'],manual_stop)

    def test_fault_during_automatic_stop_still_requires_operator_resume(self):
        r, now = self.runtime_settled('normal')
        r.set_scenario('hot'); r.tick(now+1)
        r.set_scenario('sensor_error'); r.tick(now+2)
        r.set_scenario('normal')
        for n in range(100): d=r.tick(now+3+n*.1)['decision']
        self.assertFalse(d['temperature_stop'])
        self.assertEqual(d['fan'],'OFF')
        self.assertTrue(d['operator_stopped'])

    def test_temperature_danger_does_not_override_fault_or_emergency_stop(self):
        _, d = self.settled('AUTHORIZED', temperature=28, sensor_ok=False)
        self.assertEqual((d['state'], d['fan']), ('FAULT', 'OFF'))
        r, now = self.runtime_settled('hot_intrusion')
        self.assertTrue(r.last_snapshot['decision']['temperature_danger'])
        r.action('stop')
        d = r.tick(now + 1)['decision']
        self.assertEqual((d['fan'], d['vent'], d['buzzer']), ('OFF', 'CLOSED', False))

    def test_raw_gas_release_boundary_and_delay(self):
        c, _ = self.settled(gas_raw=250)
        self.assertTrue(self.evaluate(c, 5, gas_raw=210)['environment_alert'])
        self.assertFalse(self.evaluate(c, 6, gas_raw=209)['environment_alert'])
        self.assertEqual(self.evaluate(c, 9, gas_raw=209)['state'], 'NORMAL')

    def test_threshold_or_profile_mismatch_stops_fan(self):
        for key, wrong in [('profile', 'bench'), ('policy_rev', 5), ('temp_trip', 32), ('temp_red', 38),
                           ('temp_restart_ms',0), ('temperature_stop',None),
                           ('gas_trip', 251), ('temp_release', 29), ('gas_release', 200),
                           ('gas_mode', 'ppm'), ('bench_run_ms', 10000)]:
            _, d = self.settled(**{key: wrong})
            self.assertEqual((d['state'], d['fan']), ('FAULT', 'OFF'))
            self.assertTrue(d['settings_locked'])

    def runtime_settled(self, scenario):
        r = Runtime(self.cfg, simulation=True, scenario=scenario)
        self.addCleanup(r.close)
        start = time.monotonic()
        for n in range(45):
            r.tick(start + n * 0.1)
        return r, start + 4.4

    def test_continuous_fan_and_approval_expiry(self):
        r, now = self.runtime_settled('intrusion')
        r.access.approve(now)
        self.assertTrue(r.tick(now + 1)['decision']['device_enable'])
        after = r.tick(now + 45)
        self.assertEqual(after['vision']['state'], 'UNAUTHORIZED')
        self.assertEqual(after['decision']['fan'], 'LOW')
        self.assertTrue(after['decision']['device_enable'])
        self.assertTrue(after['decision']['settings_locked'])

    def test_stop_wins_over_combined_alarm_and_locked_resume_is_denied(self):
        r, now = self.runtime_settled('gas_intrusion')
        self.assertEqual(r.last_snapshot['decision']['fan'], 'HIGH')
        r.action('stop')
        d = r.tick(now + 1)['decision']
        self.assertEqual((d['state'], d['vent'], d['fan']), ('WARNING', 'CLOSED', 'OFF'))
        self.assertFalse(d['buzzer'])
        with self.assertRaises(ValueError): r.action('start')
        self.assertFalse(r.tick(now + 2)['decision']['device_enable'])

    def test_fault_latches_stop_and_requires_explicit_resume(self):
        r, now = self.runtime_settled('normal')
        self.assertTrue(r.last_snapshot['decision']['device_enable'])
        r.set_scenario('camera_error')
        self.assertEqual(r.tick(now + 1)['decision']['fan'], 'OFF')
        r.set_scenario('normal')
        for n in range(50): r.tick(now + 2 + n * 0.1)
        self.assertEqual(r.last_snapshot['decision']['state'], 'NORMAL')
        self.assertEqual(r.last_snapshot['decision']['fan'], 'OFF')
        r.action('start')
        self.assertEqual(r.tick(now + 8)['decision']['fan'], 'LOW')

    def test_supervisor_crash_recovery_does_not_restart_fan(self):
        with patch.dict('os.environ', {'MOBLE_RECOVERED_AFTER_CRASH': '1'}):
            r, now = self.runtime_settled('normal')
        self.assertEqual(r.last_snapshot['decision']['state'], 'NORMAL')
        self.assertEqual(r.last_snapshot['decision']['fan'], 'OFF')
        r.action('start')
        self.assertEqual(r.tick(now + 1)['decision']['fan'], 'LOW')

    def test_approved_person_leaving_does_not_trip_camera_fault(self):
        r, now = self.runtime_settled('intrusion')
        r.access.approve(now)
        for n in range(35): r.tick(now + 0.2 + n * 0.1)
        self.assertEqual(r.last_snapshot['decision']['state'], 'NORMAL')
        r.set_scenario('normal')  # Fresh camera observes zero people.
        snap = r.tick(now + 4)
        self.assertEqual(snap['vision']['state'], 'CLEARING')
        self.assertTrue(snap['decision']['settings_locked'])
        self.assertEqual(snap['decision']['fan'], 'LOW')
        self.assertNotIn('VISION_UNKNOWN', snap['decision']['faults'])
        self.assertFalse(r.fan_stopped)
        for n in range(10): snap = r.tick(now + 4.2 + n * 0.2)
        self.assertEqual(snap['vision']['state'], 'CLEAR')
        self.assertTrue(snap['decision']['device_enable'])
        self.assertFalse(snap['decision']['settings_locked'])
        r.set_scenario('camera_error')
        snap = r.tick(now + 7)
        self.assertEqual(snap['decision']['fan'], 'OFF')
        self.assertIn('CAMERA_ERROR', snap['decision']['faults'])

    def test_correct_pin_cannot_bypass_combined_alarm_setting_lock(self):
        r, now = self.runtime_settled('warm_intrusion')
        r.cfg['access']['pin_hash'] = make_pin_hash('246810')  # Synthetic test credential.
        r.simulation = False  # Exercise actual PIN authentication and freshness guard.
        original_roi = list(r.cfg['vision']['roi'])
        with patch('app.runtime.time.monotonic', return_value=now):
            for action in [lambda: r.manual_vent('OPEN', '246810'),
                           lambda: r.update_roi([0, 0, 0.5, 0.5], '246810'),
                           lambda: r.action('start', '246810')]:
                with self.assertRaisesRegex(ValueError, '설정 잠금'): action()
            r.action('stop')  # No PIN required for STOP.
            r.action('approve', '246810')  # Admin recovery remains available.
        self.assertEqual(r.cfg['vision']['roi'], original_roi)
        self.assertIsNone(r.controller.manual)
        self.assertTrue(r.fan_stopped)
        self.assertGreater(r.access.granted_until, now)

    def test_stale_camera_and_expired_grant_cannot_use_old_unlocked_snapshot(self):
        r, now = self.runtime_settled('intrusion')
        r.access.approve(now)
        r.tick(now + 1)
        r.cfg['access']['pin_hash'] = make_pin_hash('246810')
        r.simulation = False
        with patch('app.runtime.time.monotonic', return_value=now + 1):
            r.require_settings_access('246810')
        with patch('app.runtime.time.monotonic', return_value=now + 10):
            with self.assertRaises(ValueError): r.require_settings_access('246810')
        r.last_snapshot['camera_at'] = now + 100
        with patch('app.runtime.time.monotonic', return_value=now + 100):
            with self.assertRaises(ValueError): r.require_settings_access('246810')

    def test_mcu_local_boost_ack_and_combined_flags(self):
        expected = command(1, 'DANGER', 'CLOSED', True, True, 42,
                           fan='LOW', settings_locked=True, access_alert=True)
        ack = dict(expected, type='ack', accepted=True, state='WARNING', vent='OPEN',
                   fan='HIGH', environment_alert=True)
        self.assertTrue(ack_matches(ack, expected))
        ack['access_alert'] = False
        self.assertFalse(ack_matches(ack, expected))
        ack['access_alert'] = True
        expected.update(device_enable=False, fan='OFF')
        self.assertFalse(ack_matches(ack, expected))
        ack.update(device_enable=False, fan='OFF')
        self.assertTrue(ack_matches(ack, expected))
        self.assertLess(len(encode(expected)), 384)

    def test_local_temperature_stop_ack_is_separate_from_a_fault_stop(self):
        expected=command(1,'NORMAL','CLOSED',False,True,42,fan='LOW')
        ack=dict(expected,type='ack',accepted=True,state='WARNING',fan='OFF',device_enable=False,
                 temperature_stop=True,environment_alert=True,fault='')
        self.assertTrue(ack_matches(ack,expected))
        self.assertTrue(automatic_temperature_stop(ack))
        for change in ({'fault':'SENSOR_ERROR'},{'state':'FAULT'},{'temperature_stop':False},
                       {'emergency_stop':True},{'temperature_stop':'true'}):
            self.assertFalse(automatic_temperature_stop(dict(ack,**change)))
        for change in ({'fan':'HIGH','device_enable':True},{'vent':'OPEN'},{'temperature_stop':'true'}):
            self.assertFalse(ack_matches(dict(ack,**change),expected))
        stopped=command(2,'WARNING','CLOSED',False,False,42,fan='OFF',
                        settings_locked=True,access_alert=True,vent_mode='OPEN',temperature_stop=True)
        self.assertLess(len(encode(stopped)),384)
        response=dict(stopped,type='ack',accepted=True)
        self.assertTrue(ack_matches(response,stopped))
        self.assertFalse(ack_matches(dict(response,temperature_stop=False),stopped))
        with self.assertRaises(ValueError):
            command(3,'WARNING','OPEN',False,False,42,fan='OFF',temperature_stop=True)

    def test_native_firmware_priority_stop_fault_and_led_timing(self):
        compiler = shutil.which('g++')
        if not compiler: self.skipTest('g++ missing')
        source = r'''
#include <assert.h>
#include <initializer_list>
#include "ventilation_policy.h"
int main() {
  TemperatureStop guard;
  guard.update(27.9,true,0,28,27,5000); assert(!guard.active);
  guard.update(28,true,1,28,27,5000); assert(guard.active);
  guard.update(26,true,1000,28,27,5000);
  guard.update(27,true,5999,28,27,5000); assert(guard.active && !guard.cooling);
  guard.update(26,true,6000,28,27,5000);
  guard.update(26,false,10999,28,27,5000); assert(guard.active && !guard.cooling);
  guard.update(26,true,11000,28,27,5000);
  guard.update(26,true,15999,28,27,5000); assert(guard.active);
  guard.update(26,true,16000,28,27,5000); assert(!guard.active);
  guard.update(28,true,0xfffffff0u,28,27,5000);
  guard.update(26,true,0xfffffff1u,28,27,5000);
  guard.update(26,true,0xfffffff1u+5000u,28,27,5000); assert(!guard.active);
  for (const char* state : {"NORMAL","WARNING","DANGER","FAULT"}) {
    auto p=planVentilation(state,true,true,true,1500,1600,1800,"OPEN",false,true);
    assert(!p.enabled && p.pulseUs==1500 && strcmp(p.fan,"OFF")==0 && strcmp(p.vent,"CLOSED")==0);
    assert(strcmp(p.state,strcmp(state,"FAULT")==0 ? "FAULT" : "WARNING")==0);
  }
  assert(strcmp(ventilationStatus("WARNING",true,false,false,true),"TEMP AUTO STOP")==0);
  assert(strcmp(ventilationStatus("WARNING",true,true,false,true),"STOPPED")==0);
  assert(ventilationTemperatureLevel(26.9,27,28)==0);
  assert(ventilationTemperatureLevel(27,27,28)==1);
  assert(ventilationTemperatureLevel(27.9,27,28)==1);
  assert(ventilationTemperatureLevel(28,27,28)==2);
  assert(ventilationTemperatureLevel(29,27,28)==2);
  assert(strcmp(ventilationStatus("WARNING",false,false,true),"DANGER")==0);
  assert(strcmp(ventilationStatus("WARNING",true,true,true),"STOPPED")==0);
  assert(strcmp(ventilationStatus("FAULT",true,false,true),"DEVICE ERROR")==0);
  for (uint32_t t=0; t<5600; ++t) {
    for (bool access : {false,true}) {
      assert(ventilationRedPhase("WARNING",access,t,true));
      assert(!ventilationOrangePhase("WARNING",access,t,true));
    }
    assert(ventilationBuzzerHz("DANGER",t)==0);
    assert(ventilationBuzzerHz("NORMAL",t)==0);
    auto phase=t%2000;
    assert(ventilationBuzzerHz("WARNING",t)==((phase<200 || (phase>=400 && phase<600)) ? 1800 : 0));
    assert(ventilationBuzzerHz("FAULT",t)==(phase<300 ? 2000 : 0));
    for (const char* s : {"DANGER","WARNING","FAULT"}) {
      assert(ventilationBuzzerHz(s,t,true,false)==0);
      assert(ventilationBuzzerHz(s,t,false,true)==0);
    }
  }
  for (const char* state : {"NORMAL", "DANGER", "WARNING", "FAULT", "INVALID"})
    for (bool env : {false, true}) for (bool ready : {false, true})
      for (bool run : {false, true}) {
        auto p = planVentilation(state, env, ready, run, 1490, 1600, 1800);
        bool fault = !ready || strcmp(state,"FAULT")==0 || strcmp(state,"INVALID")==0;
        bool high = env || strcmp(state,"WARNING")==0;
        if (fault) {
          assert(!p.enabled && p.pulseUs==1490 && strcmp(p.state,"FAULT")==0);
        } else {
          assert(p.enabled==run && p.pulseUs==(!run ? 1490 : high ? 1800 : 1600));
          assert(strcmp(p.fan, !run ? "OFF" : high ? "HIGH" : "LOW")==0);
          assert(strcmp(p.vent, high ? "OPEN" : "CLOSED")==0);
        }
      }
  for (const char* state : {"NORMAL", "DANGER", "WARNING", "FAULT"})
    for (bool env : {false, true}) for (bool ready : {false, true}) {
      auto stopped = planVentilation(state, env, ready, true, 1490, 1600, 1800, "OPEN", true);
      assert(!stopped.enabled && stopped.pulseUs == 1490);
      assert(strcmp(stopped.vent, "CLOSED") == 0);
      assert(strcmp(ventilationStatus(state, true, true), "STOPPED") == 0);
    }
  assert(strcmp(planVentilation("NORMAL",false,true,true,1500,1600,1800,"OPEN").vent,"OPEN")==0);
  assert(strcmp(planVentilation("WARNING",true,true,true,1500,1600,1800,"CLOSED").vent,"CLOSED")==0);
  assert(strcmp(ventilationStatus("NORMAL",false,false), "NORMAL")==0);
  assert(strcmp(ventilationStatus("WARNING",false,false), "CAUTION")==0);
  assert(strcmp(ventilationStatus("DANGER",true,false), "UNAUTHORIZED")==0);
  assert(strcmp(ventilationStatus("WARNING",true,false), "DANGER")==0);
  for (unsigned cycle=0; cycle<100; ++cycle) {
    assert(ventilationOrangePhase("WARNING",true,cycle*800));
    assert(ventilationOrangePhase("WARNING",true,cycle*800+399));
    assert(!ventilationOrangePhase("WARNING",true,cycle*800+400));
    assert(!ventilationOrangePhase("WARNING",true,cycle*800+799));
    assert(ventilationOrangePhase("WARNING",false,cycle*800+799));
    for (const char* state : {"NORMAL","DANGER","FAULT"})
      assert(!ventilationOrangePhase(state,true,cycle*800));
    assert(!ventilationRedPhase("DANGER",true,cycle*800+399));
    assert(ventilationRedPhase("DANGER",true,cycle*800+400));
    assert(!ventilationRedPhase("WARNING",true,cycle*800+399));
    assert(ventilationRedPhase("WARNING",true,cycle*800+400));
  }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, binary = Path(directory) / 'policy.cpp', Path(directory) / 'policy'
            cpp.write_text(source)
            subprocess.check_call([compiler, '-std=c++11', '-Wall', '-Wextra', '-Werror',
                                   '-I', str(ROOT / 'firmware/mega_controller'), str(cpp), '-o', str(binary)])
            subprocess.check_call([str(binary)])
