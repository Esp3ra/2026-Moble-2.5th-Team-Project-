#!/usr/bin/env python3
"""Real Tk nearest-person display with synthetic inputs; opens no hardware."""
import copy
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / '.vendor'))
from app.config import load
from app.runtime import Runtime, simulation_frame
from app.ui import Dashboard, cv2


def main():
    runtime = Runtime(load(ROOT / 'config/ventilation.json'), simulation=True, scenario='intrusion')
    dashboard = Dashboard(runtime)
    try:
        now = time.monotonic()
        for i in range(40): snapshot = runtime.tick(now + i * .1)
        frame, boxes = simulation_frame(2, 640, 480)
        snapshot['frame'] = frame
        snapshot['vision'].update(count=2, boxes=boxes, selection='nearest', target_index=1,
                                 target_basis='face_size', target_recognized=False, recognized_names=[])
        dashboard.render(snapshot)
        assert '전체 2명' in dashboard.labels['persons'].cget('text')
        assert all(str(b.cget('state')) == 'disabled' for b in dashboard.settings_buttons)
        approved = dict(snapshot, decision=dict(snapshot['decision']), vision=dict(snapshot['vision']), face_authorized=True)
        approved['decision'].update(state='NORMAL', target='NORMAL', settings_locked=False, access_alert=False,
                                    buzzer=False, reasons=[], fan='LOW', device_enable=True)
        approved['vision'].update(state='AUTHORIZED', target_index=0, target_recognized=True, recognized_names=['시험 승인자'])
        with patch('app.ui.cv2.rectangle', wraps=cv2.rectangle) as rectangles:
            dashboard.render(approved)
            assert rectangles.call_count == 2, 'Only selected person and ROI should be drawn'
            expected = (int(boxes[0]['box'][0]), int(boxes[0]['box'][1] * .75))
            assert rectangles.call_args_list[0][0][1] == expected
        assert '승인: 시험 승인자' in dashboard.labels['persons'].cget('text')
        assert all(str(b.cget('state')) == 'normal' for b in dashboard.settings_buttons)
        dashboard.root.update_idletasks()
        for button in dashboard.settings_buttons + [dashboard.reset_button]:
            assert button.winfo_ismapped() and button.winfo_width() >= button.winfo_reqwidth()
        subprocess.check_call(['import', '-window', str(dashboard.root.winfo_id()), str(ROOT / 'artifacts/nearest-person-dashboard.png')])
        print('PASS: total count, nearest person only highlighted, Korean approval, settings lock and recovery; no hardware opened.')
    finally:
        dashboard.close()


if __name__ == '__main__':
    main()
