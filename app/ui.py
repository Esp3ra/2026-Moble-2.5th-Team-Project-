"""Local Tk dashboard; camera and GPU workers never block the event loop."""
from collections import deque
import logging
import math
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import cv2

from .runtime import SCENARIOS
from .korean import ACCESS, FANS, MODES, STATES, VENTS, SCENARIOS as SCENARIO_LABELS, error_text, reason_text

COLORS = {'NORMAL': '#25c98b', 'WARNING': '#ff9d32', 'DANGER': '#ff637b', 'FAULT': '#c295ff'}
FONT = 'Noto Sans CJK KR'


class PinDialog(simpledialog.Dialog):
    """Masked PIN entry with Korean buttons and standard Return/Escape support."""
    def __init__(self, parent, title, prompt, masked=True):
        self.prompt = prompt
        self.masked = masked
        super().__init__(parent, title)

    def body(self, master):
        tk.Label(master, text=self.prompt, wraplength=400, justify='left').pack(padx=12, pady=10)
        self.entry = ttk.Entry(master, show='*' if self.masked else '', width=28)
        self.entry.pack(padx=12, pady=(0, 10))
        return self.entry

    def buttonbox(self):
        box = tk.Frame(self)
        ttk.Button(box, text='확인', command=self.ok).pack(side='left', padx=5)
        ttk.Button(box, text='취소', command=self.cancel).pack(side='left', padx=5)
        box.pack(pady=10)
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)

    def apply(self):
        self.result = self.entry.get()


class SensorChart(tk.Frame):
    """A bounded 60-second history; stale/invalid samples create visible gaps."""
    def __init__(self, parent, title, unit, maximum, color, threshold=None):
        super().__init__(parent, bg='#1b2635', padx=14, pady=8)
        self.unit, self.maximum, self.color, self.threshold = unit, maximum, color, threshold
        self.samples = deque(maxlen=61)
        self.sample_at = None
        tk.Label(self, text=title, bg='#1b2635', fg='#8fa4be', font=(FONT, 9, 'bold')).pack(anchor='w')
        self.value = tk.Label(self, text='--', bg='#1b2635', fg='#edf3fc', font=(FONT, 18, 'bold'))
        self.value.pack(anchor='w')
        self.chart = tk.Canvas(self, height=52, bg='#141e2b', highlightthickness=0)
        self.chart.pack(fill='x')
        self.chart.bind('<Configure>', lambda _: self.draw())

    def update_value(self, value, now, valid):
        valid = valid and isinstance(value, (float, int)) and math.isfinite(value)
        self.value.configure(text=('{:.1f} {}'.format(value, self.unit) if self.unit != '원시값' else '{} / 1023'.format(value)) if valid else '수신 대기')
        if self.sample_at is None or now - self.sample_at >= 1:
            self.sample_at = now
            self.samples.append((now, float(value) if valid else None))
            self.draw()

    def draw(self):
        canvas = self.chart
        canvas.delete('all')
        width, height = max(100, canvas.winfo_width()), 52
        canvas.create_text(5, height-3, text='최근 60초', fill='#7890ae', anchor='sw', font=(FONT, 8))
        if self.threshold is not None:
            y = 4 + (1 - self.threshold / self.maximum) * 31
            canvas.create_line(0, y, width, y, fill='#805e35', dash=(3, 4))
            canvas.create_text(width-4, height-3, text='경고 {}'.format(self.threshold), fill='#dba459', anchor='se', font=(FONT, 8))
        if not self.samples:
            return
        end = self.samples[-1][0]
        segment = []
        for stamp, value in self.samples:
            if value is None or end - stamp > 60:
                if len(segment) >= 4:
                    canvas.create_line(*segment, fill=self.color, width=2)
                segment = []
                continue
            segment.extend([4 + (stamp - end + 60) / 60 * (width-8),
                            4 + (1 - max(0, min(self.maximum, value)) / self.maximum) * 31])
        if len(segment) >= 4:
            canvas.create_line(*segment, fill=self.color, width=2)


class Dashboard:
    def __init__(self, runtime):
        self.runtime = runtime
        cv2.setNumThreads(1)
        self.root = tk.Tk()
        self.root.title('Moble | 환경·출입 관리자 콘솔')
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont'):
            self.root.tk.call('font', 'configure', name, '-family', FONT, '-size', 10)
        self.root.tk.call('::msgcat::mclocale', 'ko')
        for source, translated in (('&OK', '확인'), ('&Cancel', '취소'), ('&Yes', '예'), ('&No', '아니요')):
            self.root.tk.call('::msgcat::mcset', 'ko', source, translated)
        self.root.geometry('1280x900')
        self.root.minsize(1180, 860)
        self.root.configure(bg='#101721')
        self.closed = False
        self.last_snapshot = None
        self.drag_start = self.roi_item = None
        self.failed_at = self.fatal_error = None
        self.tick_count = 0
        self.started = time.monotonic()
        self.photo = self.last_image_key = self.last_displayed_camera_at = None
        self.display_times = deque(maxlen=30)
        self.labels, self.sensor_charts, self.vent_buttons = {}, {}, {}
        self.settings_buttons = []
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TButton', font=(FONT, 10), padding=7)
        style.configure('Active.TButton', background='#20645a', foreground='white')
        style.map('Active.TButton', background=[('disabled', '#394252'), ('active', '#29796c')])
        header = tk.Frame(self.root, bg='#101721')
        header.pack(fill='x', padx=24, pady=(16, 10))
        tk.Label(header, text='환경·출입 관리자 콘솔', font=(FONT, 20, 'bold'), fg='#edf3fc', bg='#101721').pack(side='left')
        badge = '시뮬레이션 · 실제 장치 미구동' if runtime.simulation else '카메라 점검 · 출력 연결 없음' if getattr(runtime, 'camera_only', False) else '실시간 감시 · GPU'
        self.badge = tk.Label(header, text=badge, bg='#234137', fg='#60e9b2', padx=12, pady=8)
        self.badge.pack(side='right')
        tk.Label(self.root, text='온도 {:.0f}°C 주의 / {:.0f}°C 위험 · 가스 원시값 {:.0f} · 가까운 1명 판정 (크기 추정) · 미승인 시 조작 잠금'.format(
            runtime.cfg['thresholds']['temp_warning'], runtime.cfg['thresholds']['temp_danger'], runtime.cfg['thresholds']['gas_warning']),
            bg='#1b2635', fg='#b8cadf', font=(FONT, 10), pady=7).pack(fill='x', padx=24)
        body = tk.Frame(self.root, bg='#101721')
        body.pack(fill='both', expand=True, padx=24, pady=(10, 0))
        left = tk.Frame(body, bg='#101721')
        left.pack(side='left', anchor='n')
        tk.Label(left, text='실시간 카메라 · 감시 구역', fg='#a9b8cd', bg='#101721', font=(FONT, 10, 'bold')).pack(anchor='w', pady=(0, 6))
        self.canvas = tk.Canvas(left, width=640, height=360, bg='#0a0e14', highlightthickness=0)
        self.canvas.pack()
        self.image_item = self.canvas.create_image(0, 0, anchor='nw')
        if runtime.simulation:
            self.canvas.create_text(16, 12, anchor='nw', text='시뮬레이션 영상', fill='#edf3fc', font=(FONT, 11))
        self.canvas.bind('<ButtonPress-1>', self.begin_roi)
        self.canvas.bind('<B1-Motion>', self.drag_roi)
        self.canvas.bind('<ButtonRelease-1>', self.finish_roi)
        self.details = tk.Label(left, text='카메라 연결 확인 중', fg='#7890ae', bg='#101721', anchor='w', justify='left', font=(FONT, 9))
        self.details.pack(fill='x', pady=6)
        summary = tk.Frame(left, bg='#101721')
        summary.pack(fill='x', pady=(0, 8))
        for i, (key, title) in enumerate((('persons', '출입 상태'), ('device', '배기팬'), ('vent', '유입구·운전 모드'))):
            panel = tk.Frame(summary, bg='#1b2635', padx=10, pady=6)
            panel.grid(row=0, column=i, sticky='nsew', padx=(0, 6) if i < 2 else 0)
            summary.columnconfigure(i, weight=1, uniform='summary')
            tk.Label(panel, text=title, bg='#1b2635', fg='#8fa4be', font=(FONT, 9)).pack(anchor='w')
            self.labels[key] = tk.Label(panel, text='--', bg='#1b2635', fg='#edf3fc', justify='left', anchor='w', wraplength=190, font=(FONT, 9))
            self.labels[key].pack(fill='x')
        controls = tk.Frame(left, bg='#101721')
        controls.pack(fill='x', pady=(0, 8))
        tk.Button(controls, text='긴급 정지', command=lambda: self.perform('stop'), bg='#8e263c', fg='white', font=(FONT, 11, 'bold'), padx=14, pady=8).pack(side='left', padx=(0, 10))
        if not runtime.ventilation:
            start = ttk.Button(controls, text='10초 시험 운전' if runtime.bench else '장치 시작', command=lambda: self.perform('start'))
            start.pack(side='left', padx=(0, 6))
            self.settings_buttons.append(start)
        for text, target in [('유입구 열기', 'OPEN'), ('유입구 닫기', 'CLOSED'), ('자동 제어', None)]:
            button = ttk.Button(controls, text=text, command=lambda t=target: self.manual_vent(t))
            button.pack(side='left', padx=(0, 6))
            self.settings_buttons.append(button)
            self.vent_buttons[target] = button
        actions = tk.Frame(left, bg='#101721')
        actions.pack(fill='x')
        self.reset_button = ttk.Button(actions, text='경보 해제', command=lambda: self.perform('reset'))
        self.reset_button.pack(side='left', padx=(0, 8))
        if runtime.cfg['access']['method'] == 'face':
            ttk.Button(actions, text='승인자 얼굴 등록', command=self.enroll_person).pack(side='left', padx=(0, 8))
            ttk.Button(actions, text='등록자 관리', command=self.manage_people).pack(side='left', padx=(0, 8))
        else:
            for text, action in [('1명 승인', 'approve'), ('승인 취소', 'revoke')]:
                ttk.Button(actions, text=text, command=lambda a=action: self.perform(a)).pack(side='left', padx=(0, 8))
        self.pin_setup = None
        if not runtime.simulation and not runtime.cfg['access']['pin_hash']:
            self.pin_setup = ttk.Button(actions, text='관리자 PIN 설정', command=self.setup_pin)
            self.pin_setup.pack(side='left')
        self.lock_label = tk.Label(left, text='', bg='#101721', fg='#ffca66', anchor='w', justify='left', wraplength=630, font=(FONT, 9))
        self.lock_label.pack(fill='x', pady=7)
        self.enrollment_label = tk.Label(left, text='얼굴 등록은 관리자 PIN 확인 후 진행합니다.', bg='#101721', fg='#8fa4be', anchor='w', justify='left', wraplength=630, font=(FONT, 9))
        self.enrollment_label.pack(fill='x')
        if runtime.simulation:
            demo = tk.Frame(left, bg='#101721')
            demo.pack(fill='x', pady=8)
            tk.Label(demo, text='시연 상황', fg='#a9b8cd', bg='#101721').pack(side='left')
            self.scenario = tk.StringVar(value=SCENARIO_LABELS[runtime.scenario])
            self.scenario_box = ttk.Combobox(demo, textvariable=self.scenario, values=[SCENARIO_LABELS[k] for k in SCENARIOS], state='readonly', width=22)
            self.scenario_box.pack(side='left', padx=10)
            self.scenario_box.bind('<<ComboboxSelected>>', self.select_scenario)
        right = tk.Frame(body, bg='#101721')
        right.pack(side='right', fill='both', expand=True, padx=(20, 0))
        self.state_label = tk.Label(right, text='연결 확인 중', font=(FONT, 23, 'bold'), fg=COLORS['FAULT'], bg='#1b2635', pady=14)
        self.state_label.pack(fill='x', pady=(0, 8))
        for key, title, unit, maximum, color, threshold in (
            ('temp', '실내 온도', '°C', 50, '#68b9ff', runtime.cfg['thresholds']['temp_warning']),
            ('humidity', '실내 습도', '%', 100, '#60d4b0', None),
            ('gas', 'MQ-9 가스 센서 · 미보정 원시값', '원시값', 1023, '#ffb458', runtime.cfg['thresholds']['gas_warning'])):
            chart = SensorChart(right, title, unit, maximum, color, threshold)
            chart.pack(fill='x', pady=(0, 8))
            self.sensor_charts[key] = chart
            self.labels[key] = chart.value
        self.labels['health'] = tk.Label(right, text='연결 확인 중', fg='#8fa4be', bg='#1b2635', anchor='w', justify='left', padx=12, pady=10, font=(FONT, 10))
        self.labels['health'].pack(fill='x')
        self.events = tk.Label(self.root, text='', bg='#182230', fg='#ffca66', anchor='w', justify='left', wraplength=1200, padx=14, pady=8, font=(FONT, 10))
        self.events.pack(fill='x', padx=24, pady=(6, 12))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.report_callback_exception = self.callback_error

    def select_scenario(self, _event=None):
        selected = self.scenario_box.current()
        if selected >= 0:
            self.runtime.set_scenario(SCENARIOS[selected])

    def pin(self, action='설정 변경'):
        if self.runtime.simulation:
            return ''
        return PinDialog(self.root, action, '처음 설정한 관리자 PIN을 입력하세요.').result

    def setup_pin(self):
        first = PinDialog(self.root, '관리자 PIN 설정', '숫자 6자리 이상의 PIN을 입력하세요. 이 기기에만 저장됩니다.').result
        if first is None:
            return
        second = PinDialog(self.root, 'PIN 확인', '같은 PIN을 한 번 더 입력하세요.').result
        if second is None:
            return
        try:
            if first != second:
                raise ValueError('PIN이 서로 다릅니다.')
            self.runtime.set_initial_pin(first)
            self.pin_setup.destroy()
            self.pin_setup = None
        except (ValueError, OSError) as exc:
            logging.warning('PIN setup failed: %s', exc)
            messagebox.showerror('PIN 설정 실패', error_text(exc), parent=self.root)

    def enroll_person(self):
        pin = self.pin('승인자 얼굴 등록')
        if pin is None:
            return
        name = PinDialog(self.root, '등록자 이름', '등록할 사람의 이름을 입력하세요. 얼굴 특징값은 이 기기에 저장됩니다.', masked=False).result
        if name is None:
            return
        try:
            self.runtime.start_enrollment(name, pin)
        except (ValueError, OSError) as exc:
            messagebox.showerror('얼굴 등록 실패', error_text(exc), parent=self.root)

    def manage_people(self):
        pin = self.pin('등록자 관리')
        if pin is None:
            return
        try:
            self.runtime.authenticate(pin)
            store = self.runtime.identities
            if store is None:
                raise ValueError('얼굴 등록 기능이 설정되지 않았습니다.')
            store.reload()
        except (ValueError, OSError) as exc:
            messagebox.showerror('등록자 관리', error_text(exc), parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title('승인자 등록 관리')
        window.transient(self.root)
        window.geometry('420x360')
        tk.Label(window, text='등록 정보는 프로그램을 다시 실행해도 유지됩니다.').pack(padx=15, pady=12)
        listing = tk.Listbox(window, exportselection=False)
        listing.pack(fill='both', expand=True, padx=15)
        people = []
        def refresh():
            store.reload()
            people[:] = list(store.people)
            listing.delete(0, 'end')
            for person in people:
                listing.insert('end', person['name'])
        def remove():
            selected = listing.curselection()
            if not selected:
                return
            person = people[selected[0]]
            if not messagebox.askyesno('등록 삭제', '{} 님의 얼굴 등록을 삭제할까요?'.format(person['name']), parent=window):
                return
            credential = self.pin('등록자 삭제')
            if credential is None:
                return
            try:
                self.runtime.remove_identity(person['id'], credential)
                refresh()
            except (ValueError, OSError) as exc:
                messagebox.showerror('삭제 실패', error_text(exc), parent=window)
        ttk.Button(window, text='선택한 등록자 삭제', command=remove).pack(pady=12)
        refresh()

    def perform(self, action):
        pin = '' if action == 'stop' else self.pin({'approve': '인원 승인', 'revoke': '승인 취소', 'reset': '경보 해제', 'start': '운전 재개'}.get(action, action))
        if pin is None:
            return
        try:
            self.runtime.action(action, pin)
        except ValueError as exc:
            logging.warning('Operator action blocked: %s (%s)', action, exc)
            messagebox.showerror('조작할 수 없음', error_text(exc), parent=self.root)

    def manual_vent(self, target):
        pin = self.pin()
        if pin is None:
            return
        try:
            self.runtime.manual_vent(target, pin)
        except ValueError as exc:
            logging.warning('Manual vent blocked: %s', exc)
            messagebox.showerror('조작할 수 없음', error_text(exc), parent=self.root)

    def begin_roi(self, event):
        if self.runtime.ventilation and (not self.last_snapshot or self.last_snapshot['decision'].get('settings_locked', True)):
            return
        self.drag_start = (max(0, min(640, event.x)), max(0, min(360, event.y)))

    def drag_roi(self, event):
        if not self.drag_start:
            return
        if self.roi_item:
            self.canvas.delete(self.roi_item)
        self.roi_item = self.canvas.create_rectangle(*self.drag_start, event.x, event.y, outline='#ffca66', width=2)

    def finish_roi(self, event):
        if not self.drag_start:
            return
        x0, y0 = self.drag_start
        x1, y1 = max(0, min(640, event.x)), max(0, min(360, event.y))
        self.drag_start = None
        if self.roi_item:
            self.canvas.delete(self.roi_item)
            self.roi_item = None
        if abs(x1 - x0) < 20 or abs(y1 - y0) < 20:
            return
        roi = [min(x0, x1) / 640, min(y0, y1) / 360, abs(x1 - x0) / 640, abs(y1 - y0) / 360]
        pin = self.pin('감시 구역 변경')
        if pin is None:
            return
        try:
            self.runtime.update_roi(roi, pin)
        except ValueError as exc:
            logging.warning('ROI change blocked: %s', exc)
            messagebox.showerror('감시 구역 변경 실패', error_text(exc), parent=self.root)
            return
        self.events.configure(text='감시 구역을 변경했습니다. 이번 실행 중에만 적용됩니다.')

    def render(self, snap):
        self.last_snapshot = snap
        d, v, t = snap['decision'], snap['vision'], snap['telemetry'] or {}
        now = time.monotonic()
        self.state_label.configure(text=STATES[d['state']], fg=COLORS[d['state']])
        if self.runtime.ventilation:
            self.state_label.configure(text={'WARNING': '주의', 'DANGER': '미승인 인원 감지', 'NORMAL': '정상', 'FAULT': '장치 오류'}[d['state']])
            if d['state'] != 'FAULT' and d.get('temperature_stop'):
                self.state_label.configure(text='온도 위험 · 자동 정지', fg=COLORS['DANGER'])
            elif d['state'] == 'WARNING' and d.get('temperature_danger'):
                self.state_label.configure(text='온도 위험 · 미승인' if d.get('access_alert') else '온도 위험', fg=COLORS['DANGER'])
            elif d['state'] == 'DANGER' or (d['state'] == 'WARNING' and d.get('access_alert')):
                base = 'WARNING' if d['state'] == 'WARNING' else 'NORMAL'
                color = COLORS[base] if int(now / 0.4) % 2 == 0 else COLORS['DANGER']
                self.state_label.configure(text='위험 · 미승인' if base == 'WARNING' else '미승인 인원 감지', fg=color)
            if d.get('emergency_stop'):
                self.state_label.configure(text='긴급 정지', fg=COLORS['DANGER'])
            locked = d.get('settings_locked', True)
            self.lock_label.configure(text='조작 잠금 · 미승인 또는 장치 확인 필요\n경보 해제·등록 관리에는 관리자 PIN이 필요합니다.' if locked else '관리자 조작 가능 · 수동 개폐와 자동 복귀에는 PIN이 필요합니다.')
            for button in self.settings_buttons:
                button.configure(state='disabled' if locked or d.get('temperature_stop') else 'normal')
        for target, button in self.vent_buttons.items():
            active = not d.get('emergency_stop') and not d.get('temperature_stop') and (self.runtime.controller.manual == target)
            button.configure(style='Active.TButton' if active else 'TButton')
        enabled = d['device_enable']
        ack_enabled = (snap.get('ack') or {}).get('device_enable')
        self.labels['device'].configure(text='제어: {} / 응답: {}'.format('운전' if enabled else '차단', '대기' if ack_enabled is None else '운전' if ack_enabled else '정지'), fg=COLORS['NORMAL'] if enabled else COLORS['DANGER'])
        if self.runtime.ventilation:
            self.labels['device'].configure(text='배기팬: {} / 응답: {}'.format(FANS.get(d['fan'], '확인 중'), FANS.get((snap.get('ack') or {}).get('fan'), '대기')))
        approval = '자동 승인: ' + ', '.join(v.get('recognized_names', [])) if snap.get('face_authorized') else '임시 승인 {:.0f}초'.format(snap['grant_seconds']) if snap['grant_seconds'] else '등록된 얼굴 자동 확인'
        self.labels['persons'].configure(text='{} / {}명\n{}'.format(ACCESS.get(v['state'], '확인 불가'), '--' if v['count'] is None else v['count'], approval))
        if v.get('selection') == 'nearest':
            target_text = '판정 1명' if v.get('target_index') is not None else '대상 없음'
            name = ', '.join(v.get('recognized_names', []))
            target_status = '승인: ' + (name if len(name) <= 10 else name[:10] + '…') if snap.get('face_authorized') else ACCESS.get(v['state'], '확인 불가')
            self.labels['persons'].configure(text='전체 {}명 · {}\n{}'.format('--' if v['count'] is None else v['count'], target_text, target_status))
        valid = snap['healthy'] and t.get('sensor_ok') is True and (self.runtime.simulation or now - snap['received_at'] <= self.runtime.cfg['serial']['stale_seconds'])
        for key, field in [('temp', 'temperature'), ('humidity', 'humidity'), ('gas', 'gas_raw')]:
            self.sensor_charts[key].update_value(t.get(field), now, valid)
        self.labels['vent'].configure(text='{} · {}\n부저 {}'.format(VENTS[d['vent']], MODES[d['mode']], '경보' if d['buzzer'] else '꺼짐'))
        self.labels['health'].configure(text='아두이노: {}\n카메라: {}'.format('정상' if snap['healthy'] else '오류', '정상' if snap['camera_at'] is not None and not snap['camera_error'] else '오류'))
        default_event = '정상 · 유입구 0° / 팬 기본 속도 · 환경 경고 시 유입구 90° / 팬 고속' if self.runtime.ventilation else '감시 중입니다. 장치를 운전하려면 시작 버튼을 눌러 주세요.'
        event = ' | '.join(reason_text(code) for code in d['faults'] + d['reasons']) or default_event
        if d.get('emergency_stop'):
            event = '긴급 정지 · 팬 정지 / 유입구 0° · 상태 확인 후 자동 제어로 복귀하세요. '
        elif d.get('temperature_stop') and d['state'] != 'FAULT':
            event = '온도 자동 정지 · 팬 정지 / 유입구 0° / 부저 꺼짐 · 27°C 미만이 5초 이상 유지되면 자동 재가동합니다.'
            if d.get('access_alert'):
                event += ' 미승인 인원: 조작 잠금 유지.'
        elif d.get('alarm_acknowledged'):
            event = '경보음 해제 · 원인이 남으면 표시와 조작 잠금은 유지됩니다. ' + event
        self.events.configure(text=event)
        self.enrollment_label.configure(text=snap.get('enrollment_message') or '영상을 드래그하면 감시 구역을 변경할 수 있습니다. 얼굴 등록은 한 명씩 진행하세요.')
        frame_at = snap.get('frame_at', snap['camera_at'])
        image_key = (frame_at, v['state'], v.get('target_index'), tuple(self.runtime.cfg['vision']['roi']))
        if snap['frame'] is not None and image_key != self.last_image_key:
            frame = cv2.resize(snap['frame'], (640, 360))
            scale_x, scale_y = 640.0 / snap['frame'].shape[1], 360.0 / snap['frame'].shape[0]
            for index, box in enumerate(v['boxes']):
                if v.get('selection') == 'nearest' and index != v.get('target_index'):
                    continue
                a, b, c, e = box['box']
                cv2.rectangle(frame, (int(a * scale_x), int(b * scale_y)), (int(c * scale_x), int(e * scale_y)), (70, 220, 80) if v['state'] == 'AUTHORIZED' else (80, 80, 255), 3)
            x, y, w, h = self.runtime.cfg['vision']['roi']
            cv2.rectangle(frame, (int(x * 640), int(y * 360)), (int((x + w) * 640) - 1, int((y + h) * 360) - 1), (220, 170, 70), 1)
            # Tk reads binary PPM directly. PNG compression + base64 cost ~75ms
            # per frame on this Nano; RGB/PPM takes ~3ms at the same display size.
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ppm = b'P6\n640 360\n255\n' + rgb.tobytes()
            if self.photo is None:
                self.photo = tk.PhotoImage(master=self.root, data=ppm, format='PPM')
                self.canvas.itemconfigure(self.image_item, image=self.photo)
            else:
                # Replacing the Canvas image incurred a ~35ms X11 round trip
                # per frame on this Nano. Update the existing image in place.
                self.photo.configure(data=ppm, format='PPM')
            self.last_image_key = image_key
            if frame_at != self.last_displayed_camera_at:
                self.display_times.append(time.monotonic())
                self.last_displayed_camera_at = frame_at
        elif snap['frame'] is None:
            if self.photo is not None:
                self.canvas.itemconfigure(self.image_item, image='')
            self.photo = None
            self.last_image_key = self.last_displayed_camera_at = None
            self.display_times.clear()
        span = self.display_times[-1] - self.display_times[0] if len(self.display_times) > 1 else 0
        fps = (len(self.display_times) - 1) / span if span > 0 and time.monotonic() - self.display_times[-1] < 1 else 0
        backend = '시뮬레이션' if self.runtime.simulation else 'GPU 인원 감지'
        port = '가상 연결' if self.runtime.simulation else snap['port'] or '연결 대기'
        self.details.configure(text='{} | 화면 {:.1f} FPS | 인식 처리 {:.1f} ms\n아두이노 {} | 거부된 통신 데이터: {} | 재연결: {}'.format(
            backend, fps, v['inference_ms'], port, snap['bad_packets'], snap['reconnects']))

    def callback_error(self, kind, value, tb):
        logging.error('GUI callback error', exc_info=(kind, value, tb))
        self.runtime.action('stop')
        self.events.configure(text='화면 처리 오류로 장치를 정지했습니다. ' + error_text(value))

    def tick(self):
        if self.closed:
            return
        started = time.monotonic()
        try:
            self.render(self.runtime.tick())
            self.failed_at = None
        except Exception as exc:
            logging.exception('Dashboard tick failed')
            self.runtime.action('stop')
            self.state_label.configure(text='장치 오류', fg=COLORS['FAULT'])
            self.events.configure(text='내부 오류로 장치를 정지했습니다. 복구를 재시도합니다. ' + error_text(exc))
            if self.failed_at is None:
                self.failed_at = time.monotonic()
            if time.monotonic() - self.failed_at > 5:
                self.fatal_error = exc
                self.close()
                return
        self.tick_count += 1
        # Rendering time is part of the frame interval, not an extra delay.
        # Poll faster than the source to avoid dropping frames at the 30fps
        # boundary. Cached images are not re-encoded on these extra ticks.
        remaining = 1.0 / (2 * self.runtime.cfg['camera']['fps']) - (time.monotonic() - started)
        self.root.after(max(1, int(math.ceil(remaining * 1000))), self.tick)

    def close(self):
        if not self.closed:
            self.closed = True
            self.runtime.close()
            self.root.destroy()

    def run(self, seconds=0):
        self.tick()
        if seconds:
            self.root.after(int(seconds * 1000), self.close)
        self.root.mainloop()
        if self.fatal_error:
            raise RuntimeError('Persistent dashboard error') from self.fatal_error
