#!/usr/bin/env python3
"""Verify real Tk temperature colors using synthetic inputs; no hardware."""
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / '.vendor'))
from app.config import load
from app.runtime import Runtime
from app.ui import Dashboard, COLORS


def main():
    runtime = Runtime(load(ROOT / 'config/ventilation.json'), simulation=True)
    dashboard = Dashboard(runtime)
    now = time.monotonic()
    try:
        for i in range(40): runtime.tick(now + i * .1)
        for i, scenario, color, label, fan in [
                (5,'normal','NORMAL','정상','LOW'), (6,'warm','WARNING','주의','HIGH'),
                (7,'hot','DANGER','온도 위험 · 자동 정지','OFF'),
                (8,'warm','DANGER','온도 위험 · 자동 정지','OFF'),
                (9,'normal','DANGER','온도 위험 · 자동 정지','OFF'),
                (13.9,'normal','DANGER','온도 위험 · 자동 정지','OFF'),
                (14,'normal','NORMAL','정상','LOW')]:
            runtime.set_scenario(scenario)
            snap = runtime.tick(now + i)
            dashboard.render(snap)
            assert dashboard.state_label.cget('fg') == COLORS[color], scenario
            assert dashboard.state_label.cget('text') == label, scenario
            assert snap['decision']['fan'] == fan
            assert snap['decision']['buzzer'] == (fan == 'HIGH')
            if fan == 'OFF':
                assert snap['decision']['vent'] == 'CLOSED'
                assert all(str(b.cget('state')) == 'disabled' for b in dashboard.settings_buttons)
        for scenario in ('warm_intrusion', 'hot_intrusion'):
            runtime.set_scenario(scenario)
            snap = runtime.tick(now + 15 if scenario == 'warm_intrusion' else now + 16)
            for phase in (800.1, 800.5):
                with patch('app.ui.time.monotonic', return_value=phase): dashboard.render(snap)
                expected = 'WARNING' if scenario == 'warm_intrusion' and phase == 800.1 else 'DANGER'
                assert dashboard.state_label.cget('fg') == COLORS[expected]
            assert all(str(b.cget('state')) == 'disabled' for b in dashboard.settings_buttons)
        dashboard.root.update_idletasks()
        subprocess.check_call(['import', '-window', str(dashboard.root.winfo_id()), str(ROOT / 'artifacts/temperature-stop-dashboard.png')])
        runtime.action('stop')
        dashboard.render(runtime.tick(now + 17))
        assert dashboard.state_label.cget('text') == '긴급 정지'
        assert not runtime.last_snapshot['decision']['buzzer']
        runtime.set_scenario('normal')
        for n in range(70): snap=runtime.tick(now+18+n*.1)
        dashboard.render(snap)
        assert dashboard.state_label.cget('text') == '긴급 정지'
        assert not snap['decision']['temperature_stop'] and snap['decision']['fan'] == 'OFF'
        print('PASS: 28C auto stop, red cooling latch, five-second normal recovery, access lock and persistent manual STOP; synthetic inputs, no hardware.')
    finally:
        dashboard.close()


if __name__ == '__main__':
    main()
