"""Timed operator authorization. Body detection alone never establishes identity."""
import hashlib
import hmac
import os


def make_pin_hash(pin):
    if not pin.isdigit() or len(pin) < 6:
        raise ValueError('Use at least 6 numeric digits')
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', pin.encode(), bytes.fromhex(salt), 100000).hex()
    return salt + ':' + digest


def verify_pin(pin, stored):
    try:
        salt, expected = stored.split(':')
        actual = hashlib.pbkdf2_hmac('sha256', pin.encode(), bytes.fromhex(salt), 100000).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, AttributeError):
        return False


class AccessPolicy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.granted_until = 0
        self.count = None
        self.clear_count = 0
        self.latched = False
        self.device_requested = False
        self.face_authorized = False
        self.face_streak = 0
        self.face_ids = ()

    def approve(self, now):
        if self.count != 1:
            raise ValueError('Approval requires exactly one visible person')
        self.granted_until = now + self.cfg['grant_seconds']
        self.latched = False
        self.device_requested = False

    def revoke(self):
        self.granted_until = 0
        self.device_requested = False
        self.face_authorized = False
        self.face_streak = 0
        self.face_ids = ()

    def observe_faces(self, count, identifiers, now, fresh, confirm_frames):
        ids = tuple(sorted(identifiers))
        if count is None or count == 0 or len(ids) != count or len(set(ids)) != count:
            self.revoke()
            return self.observe(count, now, fresh)
        self.count, self.clear_count = count, 0
        if fresh:
            self.face_streak = self.face_streak + 1 if ids == self.face_ids else 1
            self.face_ids = ids
        self.face_authorized = self.face_streak >= confirm_frames
        if self.face_authorized:
            self.latched = False
            return 'AUTHORIZED'
        self.latched = True
        return 'UNAUTHORIZED'

    def observe_nearest(self, count, target_index, identifiers, now, fresh, confirm_frames):
        """Authorize the selected person, while retaining the total occupancy."""
        if count is None or count == 0:
            return self.observe_faces(count, [], now, fresh, confirm_frames)
        valid = type(target_index) is int and 0 <= target_index < count and len(identifiers) == 1
        state = self.observe_faces(1, identifiers if valid else [], now, fresh, confirm_frames)
        self.count = count
        return state

    def reset(self):
        if self.count != 0 or self.clear_count < self.cfg['clear_frames']:
            raise ValueError('Clear the monitored area before resetting')
        self.latched = False
        self.revoke()

    def observe(self, count, now, fresh=True):
        self.count = count
        if count is None:
            self.revoke()
            self.clear_count = 0
            return 'UNKNOWN'
        if count == 0:
            # Leaving the image revokes permission, but does not stop a running
            # machine solely because the already-clear area is still empty.
            self.granted_until = 0
            if fresh:
                self.clear_count += 1
            if self.latched:
                return 'UNAUTHORIZED'
            return 'CLEAR' if self.clear_count >= self.cfg['clear_frames'] else 'UNKNOWN'
        self.clear_count = 0
        if count == 1 and now < self.granted_until:
            return 'AUTHORIZED'
        self.revoke()
        self.latched = True
        return 'UNAUTHORIZED'

    def request_start(self, decision, vision):
        if decision['state'] != 'NORMAL' or decision['target'] != 'NORMAL' or vision not in ('CLEAR', 'AUTHORIZED'):
            raise ValueError('Start blocked: clear all alarms and faults first')
        self.device_requested = True

    def device_enabled(self, decision, vision):
        if decision['state'] != 'NORMAL' or decision['target'] != 'NORMAL' or vision not in ('CLEAR', 'AUTHORIZED'):
            self.device_requested = False
        return self.device_requested
