#!/usr/bin/env python3
"""Render the actual dashboard and capture only this application's window."""
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.vendor'))
from app.config import load
from app.runtime import Runtime
from app.ui import Dashboard

runtime = Runtime(load(), True)
dashboard = Dashboard(runtime)
errors = []
phase = [0]
started = time.monotonic()


def check():
    try:
        if time.monotonic() - started > 40:
            raise AssertionError('GUI scenario timeout, phase ' + str(phase[0]))
        snap = dashboard.last_snapshot
        if snap and phase[0] == 0 and snap['decision']['state'] == 'NORMAL':
            runtime.action('start')
            runtime.set_scenario('intrusion')
            dashboard.scenario_box.current(1)
            phase[0] = 1
        elif snap and phase[0] == 1 and snap['decision']['state'] == 'DANGER':
            assert not snap['decision']['device_enable'], 'Intrusion must block device'
            assert snap['decision']['buzzer'], 'Intrusion must sound alarm'
            runtime.action('approve')
            dashboard.root.update_idletasks()
            subprocess.check_call(['import', '-window', str(dashboard.root.winfo_id()), str(ROOT / 'artifacts/dashboard.png')])
            phase[0] = 2
        elif snap and phase[0] == 2 and snap['decision']['state'] == 'NORMAL':
            assert snap['vision']['state'] == 'AUTHORIZED', 'Expected approval'
            assert not snap['decision']['device_enable'], 'Must not auto-restart'
            runtime.action('start')
            phase[0] = 3
        elif snap and phase[0] == 3 and snap['decision']['device_enable']:
            runtime.action('stop')
            phase[0] = 4
            dashboard.close()
            return
    except Exception as exc:
        errors.append(repr(exc))
        dashboard.close()
        return
    dashboard.root.after(200, check)


dashboard.root.after(500, check)
dashboard.run()
if errors or phase[0] != 4:
    raise RuntimeError('; '.join(errors) or 'Incomplete GUI scenario')
print('PASS: real Tk rendering, intrusion alarm, interlock, approval, explicit restart; screenshot saved.')
