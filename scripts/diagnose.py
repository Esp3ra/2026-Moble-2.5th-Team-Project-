"""Read-only readiness report. Does not flash, calibrate or energize outputs."""
import glob
import importlib
import json
import os
from pathlib import Path
import platform

from app.config import ROOT


def diagnose(cfg):
    import cv2
    report = {'architecture': platform.machine(), 'python': platform.python_version(),
              'opencv': cv2.__version__, 'camera_devices': glob.glob('/dev/video*'),
              'serial_devices': glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*'),
              'serial_permissions': {p: os.access(p, os.R_OK | os.W_OK) for p in glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')},
              'hardware_confirmed': cfg['hardware']['confirmed'],
              'gas_calibrated': cfg['hardware']['gas_calibrated'],
              'admin_pin_configured': bool(cfg['access']['pin_hash'])}
    for name in ['serial', 'tensorrt', 'tkinter']:
        try:
            module = importlib.import_module(name)
            report[name] = getattr(module, '__version__', 'available')
        except ImportError as exc:
            report[name] = str(exc)
    path = Path(cfg['vision']['engine'])
    report['engine_exists'] = (path if path.is_absolute() else ROOT / path).exists()
    print(json.dumps(report, indent=2))
    return 0
