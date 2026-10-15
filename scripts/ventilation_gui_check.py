#!/usr/bin/env python3
"""Real Tk widgets, simulated combined inputs; no hardware is opened."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / '.vendor'))
from app.config import load
from app.runtime import Runtime
from app.ui import Dashboard, COLORS

r = Runtime(load(ROOT / 'config/ventilation.json'), True, 'warm_intrusion')
d = Dashboard(r)
try:
    now = time.monotonic()
    for n in range(45): r.tick(now + n * 0.1)
    snap = r.last_snapshot
    assert snap['decision']['state'] == 'WARNING' and snap['decision']['settings_locked']
    with patch('app.ui.time.monotonic', return_value=800.1): d.render(snap)
    assert d.state_label.cget('fg') == COLORS['WARNING']
    with patch('app.ui.time.monotonic', return_value=800.5): d.render(snap)
    assert d.state_label.cget('fg') == COLORS['DANGER']
    assert all(str(b.cget('state')) == 'disabled' for b in d.settings_buttons)
    d.begin_roi(SimpleNamespace(x=20, y=20))
    assert d.drag_start is None
    d.root.update_idletasks()
    subprocess.check_call(['import', '-window', str(d.root.winfo_id()), str(ROOT / 'artifacts/ventilation-dashboard.png')])
    r.action('stop')
    assert r.tick(now + 5)['decision']['fan'] == 'OFF'
    r.access.approve(now + 5)
    for n in range(35): snap = r.tick(now + 5.1 + n * 0.1)
    d.render(snap)
    assert not snap['decision']['settings_locked']
    assert all(str(b.cget('state')) == 'normal' for b in d.settings_buttons)
    assert d.state_label.cget('text') == '긴급 정지'
    r.manual_vent(None)
    d.render(r.tick(now + 9))
    assert d.state_label.cget('fg') == COLORS['WARNING']
    print('PASS: combined orange/red display, settings widgets/ROI locked, STOP, admin approval recovery.')
finally:
    d.close()
