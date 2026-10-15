"""Load and validate settings before any device is opened."""
import copy
import json
import math
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def merge(base, changes):
    for key, value in changes.items():
        if key not in base:
            raise ValueError("Unknown setting: " + key)
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError("Expected object: " + key)
            merge(base[key], value)
        else:
            base[key] = value
    return base


def number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Invalid {}: {} ({}..{})".format(name, value, low, high))


def validate(cfg):
    for section, keys in {
        'serial': ['stale_seconds', 'ack_seconds', 'retry_seconds'],
        'camera': ['stale_seconds', 'retry_seconds', 'startup_seconds'],
        'control': ['recovery_seconds', 'command_seconds', 'manual_seconds'],
        'logging': ['csv_seconds'],
        'access': ['grant_seconds']
    }.items():
        for key in keys:
            number(cfg[section][key], 0.1, 120, section + '.' + key)
    if cfg['control']['command_seconds'] > 1:
        raise ValueError('Heartbeat must be <= 1 second for the firmware watchdog')
    if cfg['access']['method'] not in ('manual', 'face'):
        raise ValueError('Unsupported access method')
    faces = cfg['vision']['faces']
    if not isinstance(faces['enabled'], bool) or faces['enabled'] != (cfg['access']['method'] == 'face'):
        raise ValueError('Face recognition and access method must agree')
    for key in ('detector_engine', 'recognizer_engine', 'database'):
        if not isinstance(faces[key], str) or not faces[key]:
            raise ValueError('Invalid face model/database path')
    number(faces['threshold'], 0.35, 0.95, 'face threshold')
    for key, bounds in [('min_face_pixels', (40, 200)), ('confirm_frames', (2, 20))]:
        number(faces[key], *bounds, name=key)
        if not isinstance(faces[key], int):
            raise ValueError(key + ' must be integer')
    if not isinstance(cfg['access']['pin_hash'], str):
        raise ValueError('access.pin_hash must be a string')
    number(cfg['access']['clear_frames'], 1, 100, 'clear_frames')
    if not isinstance(cfg['access']['clear_frames'], int):
        raise ValueError('clear_frames must be integer')
    if cfg['vision']['backend'] != 'tensorrt':
        raise ValueError('Live detection requires the configured TensorRT GPU backend')
    number(cfg['vision']['confidence'], 0.1, 1.0, 'confidence')
    if cfg['vision']['input_size'] != 320:
        raise ValueError('This engine is built for input_size=320')
    for key in ['confirmed', 'gas_calibrated', 'require_ir']:
        if not isinstance(cfg['hardware'][key], bool):
            raise ValueError('hardware.' + key + ' must be boolean')
    if cfg['hardware']['profile'] not in ('production', 'bench', 'ventilation'):
        raise ValueError('hardware.profile must be production, bench or ventilation')
    t = cfg['thresholds']
    for prefix, limits in [('temp', (0, 50)), ('gas', (0, 1023))]:
        for suffix in ['warning', 'danger', 'hysteresis']:
            number(t[prefix + '_' + suffix], *limits, name=prefix + '_' + suffix)
        if not t[prefix + '_warning'] < t[prefix + '_danger']:
            raise ValueError(prefix + ': warning must be below danger')
        direct_temperature = cfg['hardware']['profile'] == 'ventilation' and prefix == 'temp'
        if not (0 <= t[prefix + '_hysteresis'] < t[prefix + '_warning']
                and (direct_temperature or t[prefix + '_hysteresis'] > 0)):
            raise ValueError(prefix + ': invalid hysteresis')
    roi = cfg['vision']['roi']
    if not isinstance(roi, list) or len(roi) != 4:
        raise ValueError('ROI must be [x, y, width, height]')
    for v in roi:
        number(v, 0, 1, 'ROI')
    x, y, w, h = roi
    if w <= 0 or h <= 0 or x + w > 1.00001 or y + h > 1.00001:
        raise ValueError('ROI is outside the frame')
    for key, bounds in [('width', (160, 1920)), ('height', (120, 1080)), ('fps', (1, 30))]:
        number(cfg['camera'][key], *bounds, name=key)
        if not isinstance(cfg['camera'][key], int):
            raise ValueError(key + ' must be integer')
    number(cfg['camera']['capture_fps'], 1, 120, 'camera.capture_fps')
    if not isinstance(cfg['camera']['capture_fps'], int):
        raise ValueError('camera.capture_fps must be integer')
    if cfg['camera']['fourcc'] not in ('MJPG', 'YUYV'):
        raise ValueError('camera.fourcc must be MJPG or YUYV')
    if not isinstance(cfg['serial']['port'], str) or not cfg['serial']['port']:
        raise ValueError('Serial port must be a path or auto')
    number(cfg['serial']['baud'], 9600, 1000000, 'baud')
    if not isinstance(cfg['serial']['baud'], int):
        raise ValueError('baud must be integer')
    if not isinstance(cfg['camera']['device'], (str, int)) or isinstance(cfg['camera']['device'], bool):
        raise ValueError('camera.device must be an integer or path')
    if not isinstance(cfg['logging']['directory'], str) or not cfg['logging']['directory']:
        raise ValueError('logging.directory must be a path')
    return cfg


def load(path=None):
    cfg = json.loads((ROOT / 'config/default.json').read_text())
    local = ROOT / 'config/local.json'
    if local.exists():
        merge(cfg, json.loads(local.read_text()))
    if path:
        merge(cfg, json.loads(Path(path).read_text()))
    return validate(copy.deepcopy(cfg))


def save_pin_hash(stored, path=None):
    """Keep the local credential out of shareable profile files."""
    path = Path(path) if path else ROOT / 'config/local.json'
    cfg = json.loads(path.read_text()) if path.exists() else {}
    cfg.setdefault('access', {})['pin_hash'] = stored
    fd, temporary = tempfile.mkstemp(prefix='.pin-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(cfg, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
