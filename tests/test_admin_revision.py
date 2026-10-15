"""Persistent identity, fail-closed recognition and administrator control contracts."""
import json
from pathlib import Path
import tempfile
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / '.vendor'))

from app.access import AccessPolicy, make_pin_hash
from app.config import ROOT, load
from app.faces import FaceRecognizer, align_face
from app.identities import IdentityStore
from app.protocol import ack_matches, command
from app.runtime import Runtime


def vector(index=0):
    result = np.zeros(128, np.float32)
    result[index] = 1
    return result


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'data' / 'identities.json'
        self.store = IdentityStore(self.path)

    def test_enrollment_survives_restart_and_deletion(self):
        identifier = self.store.enroll('시험 사용자', [vector()] * 8)
        restarted = IdentityStore(self.path)
        self.assertEqual(restarted.match(vector())['id'], identifier)
        self.assertEqual(restarted.people[0]['name'], '시험 사용자')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(restarted.match(vector(1)))
        restarted.remove(identifier)
        self.store.reload()
        self.assertEqual(self.store.people, [])
        self.assertEqual(IdentityStore(self.path).people, [])

    def test_inconsistent_duplicate_and_ambiguous_templates_rejected(self):
        with self.assertRaises(ValueError):
            self.store.enroll('다른 얼굴', [vector()] * 4 + [vector(1)])
        self.store.enroll('같은 이름', [vector()] * 8)
        with self.assertRaises(ValueError):
            self.store.enroll('같은 이름', [vector()] * 8)
        self.store.enroll('중복 특징', [vector()] * 8)
        self.assertIsNone(self.store.match(vector()))

    def test_failed_save_preserves_previous_file(self):
        identifier = self.store.enroll('보존', [vector()] * 8)
        before = self.path.read_bytes()
        with patch('app.identities.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.store.remove(identifier)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.match(vector())['id'], identifier)
        self.assertEqual(list(self.path.parent.glob('.identities-*')), [])

    def test_corrupt_file_is_not_silently_reset(self):
        self.store.enroll('보존', [vector()] * 8)
        self.path.write_text('{broken')
        with self.assertRaises(ValueError):
            self.store.reload()
        self.assertEqual(self.path.read_text(), '{broken')
        with self.assertRaises(ValueError):
            IdentityStore(self.path)

    def test_alignment_rejects_degenerate_points_and_preserves_reference(self):
        frame = np.random.RandomState(1).randint(0, 256, (112, 112, 3)).astype('uint8')
        landmarks = [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                     [41.5493, 92.3655], [70.7299, 92.2041]]
        np.testing.assert_array_equal(align_face(frame, landmarks), frame)
        with self.assertRaises(ValueError):
            align_face(frame, [[0, 0]] * 5)

    def test_only_nearest_person_is_recognized_but_enrollment_still_requires_one(self):
        self.store.enroll('시험', [vector()] * 8)
        recognizer = FaceRecognizer.__new__(FaceRecognizer)
        recognizer.cfg = {'min_face_pixels': 60}
        recognizer.store = self.store
        recognizer.recognizer = Mock()
        recognizer.recognizer.run.return_value = {'fc1': vector()[None, :]}
        frame = np.random.RandomState(1).randint(0, 256, (300, 400, 3)).astype('uint8')
        people = [{'box': [0, 0, 180, 290]}, {'box': [200, 0, 390, 290]}]
        recognizer.detect = lambda _: [([20, 20, 80, 80], [])]
        with patch('app.faces.align_face', return_value=frame[:112, :112]):
            one = recognizer.inspect(frame, people[:1], (0, 0, 400, 300))
            self.assertTrue(one['target_recognized'])
            self.assertIsNotNone(one['_enrollment'])
            two = recognizer.inspect(frame, people, (0, 0, 400, 300))
            self.assertTrue(two['target_recognized'])
            self.assertEqual(len(two['recognized_ids']), 1)
            self.assertEqual(two['target_index'], 0)
            self.assertIsNone(two['_enrollment'])
            recognizer.detect = lambda _: [([20, 20, 80, 80], []), ([220, 20, 80, 80], [])]
            duplicate = recognizer.inspect(frame, people, (0, 0, 400, 300))
            self.assertTrue(duplicate['target_recognized'])
            self.assertEqual(len(duplicate['recognized_ids']), 1)
            head_only = recognizer.inspect(frame, [], (0, 0, 180, 300))
            self.assertEqual(head_only['count'], 1)


class FaceAccessTests(unittest.TestCase):
    def setUp(self):
        self.access = AccessPolicy(load()['access'])

    def observe(self, count, ids, fresh=True):
        return self.access.observe_faces(count, ids, 100, fresh, 3)

    def test_fresh_consecutive_frames_and_immediate_unknown_revocation(self):
        self.assertEqual(self.observe(1, ['a']), 'UNAUTHORIZED')
        for _ in range(10):
            self.assertEqual(self.observe(1, ['a'], False), 'UNAUTHORIZED')
        self.observe(1, ['a'])
        self.assertEqual(self.observe(1, ['a']), 'AUTHORIZED')
        self.assertEqual(self.observe(1, []), 'UNAUTHORIZED')
        self.assertFalse(self.access.face_authorized)
        self.assertEqual(self.observe(None, ['a']), 'UNKNOWN')

    def test_person_swap_duplicates_and_additional_unknown_cannot_inherit_approval(self):
        for _ in range(3): self.observe(1, ['a'])
        self.assertEqual(self.observe(1, ['b']), 'UNAUTHORIZED')
        for _ in range(3): self.observe(2, ['a', 'b'])
        self.assertTrue(self.access.face_authorized)
        self.assertEqual(self.observe(3, ['a', 'b']), 'UNAUTHORIZED')
        self.assertEqual(self.observe(2, ['a', 'a']), 'UNAUTHORIZED')


class AdminControlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cfg = load(ROOT / 'config/ventilation.json')
        self.cfg['vision']['faces']['database'] = str(Path(self.directory.name) / 'identities.json')

    def settled(self, scenario='normal'):
        runtime = Runtime(self.cfg, simulation=True, scenario=scenario)
        self.addCleanup(runtime.close)
        self.now = time.monotonic()
        for n in range(45): runtime.tick(self.now + n * .1)
        self.now += 4.4
        return runtime

    def test_manual_open_close_persist_and_auto_restores_outputs(self):
        runtime = self.settled()
        self.assertEqual(runtime.last_snapshot['decision']['vent'], 'CLOSED')
        runtime.manual_vent('OPEN')
        self.assertEqual(runtime.tick(self.now + 120)['decision']['vent'], 'OPEN')
        runtime.manual_vent('CLOSED')
        self.assertEqual(runtime.tick(self.now + 121)['decision']['vent'], 'CLOSED')
        runtime.set_scenario('warm')
        self.assertEqual(runtime.tick(self.now + 122)['decision']['vent'], 'CLOSED')
        runtime.manual_vent(None)
        self.assertEqual(runtime.tick(self.now + 123)['decision']['vent'], 'OPEN')
        self.assertIsNone(runtime.controller.manual)
        runtime.action('stop')
        d = runtime.tick(self.now + 124)['decision']
        self.assertEqual((d['vent'], d['fan'], d['buzzer']), ('CLOSED', 'OFF', False))
        runtime.manual_vent(None)
        d = runtime.tick(self.now + 125)['decision']
        self.assertEqual((d['vent'], d['fan'], d['emergency_stop']), ('OPEN', 'HIGH', False))

    def test_alarm_mute_keeps_access_lock_and_new_cause_rearms(self):
        runtime = self.settled('intrusion')
        runtime.action('reset')
        d = runtime.tick(self.now + 1)['decision']
        self.assertTrue(d['alarm_acknowledged'])
        self.assertTrue(d['settings_locked'])
        self.assertFalse(d['buzzer'])
        self.assertEqual(d['state'], 'DANGER')
        runtime.set_scenario('warm_intrusion')
        d = runtime.tick(self.now + 2)['decision']
        self.assertTrue(d['buzzer'])
        self.assertFalse(d['alarm_acknowledged'])
        self.assertTrue(d['settings_locked'])

    def test_enrollment_requires_pin_collects_quality_samples_and_persists(self):
        runtime = self.settled()
        runtime.simulation = False
        runtime.cfg['access']['pin_hash'] = make_pin_hash('246810')
        runtime.camera = SimpleNamespace(result={'_enrollment': vector().tolist()}, close=lambda: None)
        with self.assertRaises(ValueError): runtime.start_enrollment('시험', '000000')
        with patch('app.runtime.time.monotonic', return_value=100):
            runtime.start_enrollment('시험', '246810')
        runtime.collect_enrollment(101, False)
        self.assertEqual(runtime.enrollment['samples'], [])
        for n in range(8): runtime.collect_enrollment(102 + n * .4, True)
        self.assertIsNone(runtime.enrollment)
        reloaded = IdentityStore(self.cfg['vision']['faces']['database'])
        self.assertEqual(reloaded.match(vector())['name'], '시험')
        with self.assertRaises(ValueError): runtime.remove_identity(reloaded.people[0]['id'], '000000')
        runtime.remove_identity(reloaded.people[0]['id'], '246810')
        self.assertIsNone(runtime.last_snapshot)
        self.assertEqual(IdentityStore(reloaded.path).people, [])

    def test_snapshot_never_contains_face_template(self):
        runtime = self.settled()
        runtime.last_vision['_enrollment'] = vector().tolist()
        self.assertNotIn('_enrollment', runtime.tick(self.now + 1)['vision'])

    def test_local_environment_boost_respects_manual_override_and_ack_flags(self):
        expected = command(1, 'NORMAL', 'CLOSED', False, True, 42, fan='LOW', vent_mode='CLOSED')
        ack = dict(expected, type='ack', accepted=True, state='WARNING', fan='HIGH', environment_alert=True)
        self.assertTrue(ack_matches(ack, expected))
        for key, value in [('vent_mode', 'OPEN'), ('emergency_stop', True), ('alarm_acknowledged', True)]:
            with self.subTest(key=key):
                self.assertFalse(ack_matches(dict(ack, **{key: value}), expected))
        stop = command(2, 'WARNING', 'CLOSED', False, False, 42, fan='OFF', emergency_stop=True)
        ack = dict(stop, type='ack', accepted=True)
        self.assertTrue(ack_matches(ack, stop))
        self.assertFalse(ack_matches(dict(ack, vent='OPEN'), stop))


if __name__ == '__main__':
    unittest.main()
