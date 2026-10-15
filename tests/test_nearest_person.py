"""Nearest-person selection, recognition and the real runtime access decision."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / '.vendor'))
from app.access import AccessPolicy
from app.config import load
from app.faces import FaceRecognizer
from app.identities import IdentityStore
from app.proximity import nearest_person
from app.runtime import Runtime
from test_ventilation import ventilation_sample


def vector(index):
    values = np.zeros(128, np.float32)
    values[index] = 1
    return values


class NearestPersonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = IdentityStore(Path(self.temp.name) / 'identities.json')
        self.identifier = self.store.enroll('시험 승인자', [vector(0)] * 8)
        self.recognizer = FaceRecognizer.__new__(FaceRecognizer)
        self.recognizer.cfg = {'min_face_pixels': 60}
        self.recognizer.store = self.store
        self.recognizer.recognizer = Mock()
        self.frame = np.random.RandomState(2).randint(0, 256, (480, 640, 3)).astype('uint8')
        self.people = [{'box': [0, 0, 280, 480]}, {'box': [300, 0, 600, 480]}]
        self.faces = []
        self.recognizer.detect = lambda _: self.faces

    def inspect(self, people=None, roi=(0, 0, 640, 480), blurry=False):
        def align(frame, tag):
            self.recognizer.recognizer.run.return_value = {'fc1': vector(0 if tag == 'known' else 1)[None, :]}
            return np.zeros((112, 112, 3), np.uint8) if blurry else frame[:112, :112]
        with patch('app.faces.align_face', side_effect=align):
            return self.recognizer.inspect(self.frame, self.people if people is None else people, roi)

    def test_registered_front_unknown_behind_uses_one_recognition(self):
        self.faces = [([40, 20, 120, 120], 'known'), ([360, 20, 70, 70], 'unknown')]
        result = self.inspect()
        self.assertEqual((result['count'], result['target_index']), (2, 0))
        self.assertEqual(result['recognized_ids'], [self.identifier])
        self.assertTrue(result['target_recognized'])
        self.assertEqual(self.recognizer.recognizer.run.call_count, 1)
        self.assertIsNone(result['_enrollment'])

    def test_unknown_front_does_not_search_background_for_registered_person(self):
        self.faces = [([40, 20, 70, 70], 'known'), ([360, 20, 120, 120], 'unknown')]
        result = self.inspect()
        self.assertEqual(result['target_index'], 1)
        self.assertFalse(result['target_recognized'])
        self.assertEqual(result['recognized_ids'], [])
        self.assertEqual(result['recognized_names'], [])
        self.assertEqual(self.recognizer.recognizer.run.call_count, 1)

    def test_larger_turned_away_person_is_not_ignored(self):
        self.faces = [([40, 20, 70, 70], 'known')]
        people = [{'box': [0, 0, 220, 460]}, {'box': [250, 0, 640, 480]}]
        result = self.inspect(people)
        self.assertEqual((result['target_index'], result['target_basis']), (1, 'body_size'))
        self.assertFalse(result['target_recognized'])
        self.recognizer.recognizer.run.assert_not_called()

    def test_small_background_body_does_not_revoke_front_person(self):
        self.faces = [([40, 20, 100, 100], 'known')]
        result = self.inspect([self.people[0], {'box': [400, 150, 480, 400]}])
        self.assertEqual(result['target_index'], 0)
        self.assertTrue(result['target_recognized'])

    def test_no_face_or_poor_face_does_not_fall_back_to_background(self):
        self.faces = [([40, 20, 80, 80], 'known'), ([360, 20, 120, 120], 'unknown')]
        result = self.inspect(blurry=True)
        self.assertEqual(result['target_index'], 1)
        self.assertFalse(result['target_recognized'])
        self.recognizer.recognizer.run.assert_not_called()

    def test_head_only_detection_and_roi(self):
        self.faces = [([40, 20, 80, 80], 'known'), ([360, 20, 120, 120], 'unknown')]
        result = self.inspect(people=[], roi=(0, 0, 250, 480))
        self.assertEqual((result['count'], result['target_index']), (1, 0))
        self.assertTrue(result['target_recognized'])
        self.assertIsNotNone(result['_enrollment'])

    def test_empty_and_malformed_geometry_have_no_target(self):
        self.assertIsNone(nearest_person([], {})['index'])
        self.assertIsNone(nearest_person([{'box': [0, 0, 0, 10]}], {})['index'])
        self.assertIsNone(nearest_person([{'box': [0, 0, float('nan'), 10]}], {})['index'])

    def test_equal_scale_keeps_a_person_without_a_visible_face_in_contention(self):
        boxes = [{'box': [0, 0, 200, 420]}, {'box': [210, 0, 450, 420]}]
        self.assertEqual(nearest_person(boxes, {0: [30, 20, 80, 80]})['index'], 1)

    def test_permission_tracks_the_selected_identity_not_total_count(self):
        access = AccessPolicy(load()['access'])
        for i in range(3):
            state = access.observe_nearest(2, 0, [self.identifier], i, True, 3)
        self.assertEqual(state, 'AUTHORIZED')
        self.assertEqual(access.count, 2)
        self.assertEqual(access.observe_nearest(3, 2, [self.identifier], 4, True, 3), 'AUTHORIZED')
        self.assertEqual(access.observe_nearest(3, 0, [], 5, True, 3), 'UNAUTHORIZED')
        self.assertFalse(access.face_authorized)
        for i in range(2):
            self.assertEqual(access.observe_nearest(2, 0, [self.identifier], 6+i, True, 3), 'UNAUTHORIZED')
        self.assertEqual(access.observe_nearest(2, 0, [self.identifier], 8, True, 3), 'AUTHORIZED')
        self.assertEqual(access.observe_nearest(None, 0, [self.identifier], 20, False, 3), 'UNKNOWN')

    def test_invalid_target_or_multiple_identity_results_cannot_authorize(self):
        for target, ids in [(None, [self.identifier]), (-1, [self.identifier]), (2, [self.identifier]),
                            (True, [self.identifier]), (0, [self.identifier, 'background'])]:
            access = AccessPolicy(load()['access'])
            for i in range(5): state = access.observe_nearest(2, target, ids, i, True, 3)
            self.assertEqual(state, 'UNAUTHORIZED')

    def test_runtime_alarm_lock_and_environment_with_two_people(self):
        cfg = load(ROOT / 'config/ventilation.json')
        cfg['vision']['faces']['database'] = str(self.store.path)
        cfg['access']['pin_hash'] = 'synthetic-test-marker'
        camera, link = Mock(), Mock()
        camera.error = ''
        camera.frame_at = None
        link.snapshot.side_effect = lambda now: dict(telemetry=ventilation_sample(temperature=temperature[0]),
            received_at=now, healthy=True, connected=True, error='', port='TEST', ack=None,
            bad_packets=0, reconnects=0, safety_override=False)
        temperature = [26]
        with patch('app.runtime.Camera', return_value=camera), patch('app.runtime.SerialLink', return_value=link):
            runtime = Runtime(cfg)
        # No hardware resources were created. Avoid Runtime.close's real wait.
        self.addCleanup(lambda: setattr(runtime, 'link', None))
        now = time.monotonic()
        def step(result, seconds):
            camera.result = result
            camera.frame_at = now + seconds
            camera.poll.return_value = (self.frame, now + seconds, True)
            return runtime.tick(now + seconds)
        self.faces = [([40, 20, 120, 120], 'known'), ([360, 20, 70, 70], 'unknown')]
        result = self.inspect()
        for i in range(40): snap = step(result, i * .1)
        self.assertEqual(snap['vision']['count'], 2)
        self.assertEqual(snap['vision']['state'], 'AUTHORIZED')
        self.assertEqual(snap['decision']['state'], 'NORMAL')
        self.assertFalse(snap['decision']['buzzer'])
        self.assertFalse(snap['decision']['settings_locked'])
        self.faces = [([40, 20, 70, 70], 'known'), ([360, 20, 120, 120], 'unknown')]
        snap = step(self.inspect(), 5)
        self.assertEqual(snap['decision']['state'], 'DANGER')
        self.assertFalse(snap['decision']['buzzer'])
        self.assertTrue(snap['decision']['settings_locked'])
        self.faces = [([40, 20, 120, 120], 'known'), ([360, 20, 70, 70], 'unknown')]
        result = self.inspect()
        temperature[0] = 27
        for i in range(40): snap = step(result, 6+i*.1)
        self.assertEqual(snap['vision']['state'], 'AUTHORIZED')
        self.assertEqual(snap['decision']['state'], 'WARNING')
        self.assertTrue(snap['decision']['buzzer'])
        self.assertFalse(snap['decision']['settings_locked'])


if __name__ == '__main__':
    unittest.main()
