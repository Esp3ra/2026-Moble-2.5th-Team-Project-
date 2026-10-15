#!/usr/bin/env python3
"""Exercise Korean selectors and modal dialogs on real Tk, with simulated inputs."""
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / '.vendor'))
from app.config import load
from app.runtime import Runtime, SCENARIOS
from app.ui import Dashboard, PinDialog, messagebox


def widgets(root):
    for child in root.winfo_children():
        yield child
        yield from widgets(child)


def main():
    runtime = Runtime(load(ROOT / 'config/ventilation.json'), simulation=True)
    dashboard = Dashboard(runtime)
    root = dashboard.root
    errors = []
    try:
        root.update()
        for index, code in enumerate(SCENARIOS):
            dashboard.scenario_box.current(index)
            dashboard.scenario_box.event_generate('<<ComboboxSelected>>')
            root.update()
            assert runtime.scenario == code, 'Translated selection changed the scenario mapping'
        dashboard.scenario_box.current(SCENARIOS.index('two_people'))
        dashboard.scenario_box.event_generate('<<ComboboxSelected>>')
        snap = runtime.tick()
        dashboard.render(snap)
        with patch('app.ui.messagebox.showerror') as error_dialog:
            dashboard.perform('approve')
            assert error_dialog.called, 'Two people must not be approved'
            assert '한 명' in error_dialog.call_args[0][1]
        assert runtime.access.granted_until == 0

        for action in ('confirm', 'cancel'):
            def interact(action=action):
                dialog = next(w for w in root.winfo_children() if isinstance(w, PinDialog))
                try:
                    assert dialog.entry.cget('show') == '*', 'PIN must remain masked'
                    buttons = {w.cget('text'): w for w in widgets(dialog) if w.winfo_class() == 'TButton'}
                    assert set(buttons) == {'확인', '취소'}
                    dialog.entry.insert(0, '123456')  # Test-only value, never persisted.
                    if action == 'confirm':
                        buttons['확인'].invoke()
                    else:
                        dialog.entry.focus_force()
                        dialog.event_generate('<Escape>')
                except Exception as exc:
                    errors.append(str(exc))
                    dialog.cancel()
            root.after(150, interact)
            guard = root.after(3000, lambda: [w.cancel() for w in root.winfo_children() if isinstance(w, PinDialog)])
            result = PinDialog(root, '입력창 동작 점검', '시험용 입력창입니다. 실제 PIN을 입력하지 마세요.').result
            root.after_cancel(guard)
            assert result == ('123456' if action == 'confirm' else None)

        def close_message():
            path = '.__tk__messagebox.ok'
            try:
                assert root.tk.call(path, 'cget', '-text') == '확인', 'Native error button is not Korean'
            except Exception as exc:
                errors.append(str(exc))
            finally:
                root.tk.call('set', '::tk::Priv(button)', 'ok')
        root.after(200, close_message)
        messagebox.showerror('오류 안내 점검', '한글 오류 안내와 확인 버튼을 점검합니다.', parent=root)
        assert not errors, '; '.join(errors)

        runtime.set_scenario('warm_intrusion')
        dashboard.scenario_box.current(SCENARIOS.index('warm_intrusion'))
        now = time.monotonic()
        for i in range(35):
            snap = runtime.tick(now + i * 0.1)
        dashboard.render(snap)
        root.update_idletasks()
        for widget in widgets(root):
            if widget.winfo_class() in ('TButton', 'Button'):
                assert widget.winfo_ismapped(), 'Control is hidden'
                assert widget.winfo_width() >= widget.winfo_reqwidth(), 'Button clipped'
        assert all(str(button.cget('state')) == 'disabled' for button in dashboard.settings_buttons)
        assert str(dashboard.reset_button.cget('state')) == 'normal'
        texts = [str(w.cget('text')) for w in widgets(root) if w.winfo_class() in ('TButton', 'Button', 'Label')]
        assert '유입구 닫기' in texts and '승인자 얼굴 등록' in texts and '등록자 관리' in texts
        assert not any('팬 운전 재개' in text or '적외선' in text for text in texts)
        chart = dashboard.sensor_charts['temp']
        for i in range(65): chart.update_value(26 + i * .12, now + i, True)
        assert len(chart.samples) == 61
        assert any(chart.chart.type(item) == 'line' for item in chart.chart.find_all())
        chart.update_value(100, now + 66, False)
        assert chart.value.cget('text') == '수신 대기' and chart.samples[-1][1] is None
        chart.update_value(34, now + 67, True)
        subprocess.check_call(['import', '-window', str(root.winfo_id()), str(ROOT / 'artifacts/korean-dashboard.png')])
        stop = next(w for w in widgets(root) if w.winfo_class() == 'Button' and w.cget('text') == '긴급 정지')
        stop.invoke()
        assert runtime.tick(now + 4)['decision']['fan'] == 'OFF'
        print('PASS: Korean scenario selections, blocked approval, masked PIN confirmation/Escape, '
              'native error button, visible controls, combined alarm lock and emergency stop; no hardware opened.')
    finally:
        dashboard.close()


if __name__ == '__main__':
    main()
