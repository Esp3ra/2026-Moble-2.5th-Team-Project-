#!/usr/bin/env python3
"""Generate the proposed circuit guide in docs/WIRING.md (not live firmware)."""
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
FONT = "Noto Sans CJK KR"
parts = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1490" viewBox="0 0 1440 1490">',
    '<title>Jetson Nano와 Mega 2560 회로 제작용 배선 계획</title>',
    '<desc>MQ-9, DHT11, I2C LCD 2004A, 서보 2개, RGB LED와 부저. 실물 핀 순서가 아닌 신호 연결도.</desc>',
    '<rect width="1440" height="1490" fill="#f3f6fa"/>',
]


def text(x, y, value, size=19, bold=False, color="#17324b", anchor="start"):
    parts.append(
        '<text x="{}" y="{}" font-family="{}" font-size="{}" font-weight="{}" '
        'fill="{}" text-anchor="{}">{}</text>'.format(
            x, y, FONT, size, "bold" if bold else "normal", color, anchor, escape(value)))


def box(x, y, w, h, title, lines=(), fill="#ffffff"):
    parts.append(
        '<rect x="{}" y="{}" width="{}" height="{}" rx="12" fill="{}" '
        'stroke="#b8c9d8" stroke-width="1.5"/>'.format(x, y, w, h, fill))
    text(x + 20, y + 33, title, 23, True)
    for index, line in enumerate(lines):
        text(x + 20, y + 62 + index * 26, line, 18)


def line(x0, y0, x1, y1, color="#247f9b", dashed=False):
    parts.append(
        '<path d="M {} {} L {} {}" fill="none" stroke="{}" stroke-width="3" {}/>'.format(
            x0, y0, x1, y1, color, 'stroke-dasharray="8 5"' if dashed else ""))


def signal(y, label, right=False, pending=False):
    x0, x1 = (910, 1000) if right else (440, 530)
    line(x0, y, x1, y, "#ad7720" if pending else "#247f9b", pending)
    text((x0 + x1) / 2, y - 10, label, 17, True, anchor="middle")


text(35, 47, "Jetson Nano + Mega 2560  |  신호·전원 연결도", 32, True)
text(35, 82, "2026-10-14 · 회로 제작 계획 · 실물 핀의 좌우 순서가 아닌, 단자 이름 기준 연결", 19)
box(35, 120, 340, 105, "카메라", ["Jetson USB에 연결", "미승인 인원 검출용"])
box(530, 120, 380, 105, "Jetson Nano", ["기존 전원 사용 / GPU 사람 검출", "Mega는 USB 데이터 케이블로 연결"], "#e4f2ec")
line(375, 172, 530, 172)
text(452, 160, "USB", 18, True, anchor="middle")
line(720, 225, 720, 282)
text(740, 260, "USB A ↔ USB B", 18)
box(1000, 120, 405, 105, "연결 기준", ["청록 실선: 신호 배정", "갈색 점선: 실물·코드 확인 필요"], "#fff4df")

box(530, 282, 380, 680, "Arduino Mega 2560", [], "#e3edf7")
text(550, 355, "5V 로직 · USB 시리얼 115200", 20)
text(550, 405, "센서 입력", 22, True)
for i, value in enumerate(["D2  온습도", "D3  미사용 (IR 제외)", "A0  가스 ADC", "D20 / D21  LCD I2C"]):
    text(550, 440 + i * 32, value, 20)
text(550, 605, "출력", 22, True)
for i, value in enumerate(["D9   환기구 서보", "D10 연속 회전 서보", "D28 부저", "D26 / D22 / D24  RGB"]):
    text(550, 640 + i * 32, value, 20)
text(550, 810, "D30: 선택 허가 LED", 20, True)
text(550, 842, "D30 → 330Ω → LED +", 18)
text(550, 868, "LED − → 공통 GND", 18)
text(550, 916, "Jetson 40핀 GPIO는 미사용", 19, True)

box(35, 295, 405, 130, "DHT11", [
    "DATA / S → D2", "VCC → Mega 5V, GND → 공통 GND",
    "단품: DATA–5V 사이 10kΩ 풀업"])
signal(360, "D2")
box(35, 455, 405, 130, "HW-201  ·  적외선 센서", [
    "사용자 요청으로 미사용", "배선하지 않음 / D3 입력 비활성",
    "필수 센서 검사에서도 제외"], "#eef0f3")
box(35, 615, 405, 150, "LCD 2004A  ·  I2C 20×4", [
    "SDA → D20, SCL → D21",
    "VCC → Mega 5V, GND → 공통 GND",
    "5V / 4핀 백팩 사용자 확인 완료",
    "실측 0x27 / 온습도 글자 표시 확인"])
signal(690, "20 / 21")
box(35, 795, 405, 167, "MQ-9  ·  FLYING FISH 모듈", [
    "AO → A0, DO는 미연결",
    "5V 모듈이면 VCC → 외부 5V",
    "GND → 공통 GND / 단자·히터 확인",
    "5V 고정 원시값 시연 ≠ CO ppm 측정"], "#fff8e9")
signal(880, "A0", pending=True)

box(1000, 295, 405, 130, "일반 SG90  ·  환기구 개폐", [
    "신호 S → D9",
    "전원 + → 외부 5V, GND → 공통 GND",
    "작은 각도 이동 확인 / 기구 각도 미보정"])
signal(360, "D9", right=True)
box(1000, 455, 405, 130, "SG90 360  ·  시연 장치 회전", [
    "신호 S → D10",
    "전원 + → 외부 5V, GND → 공통 GND",
    "1600µs 회전 / 1500µs 정지 확인"], "#e4f2ec")
signal(520, "D10", right=True)
box(1000, 615, 405, 150, "MH-FMD  ·  부저 모듈", [
    "S / IN / I/O → D28",
    "VCC → 5V 전원",
    "GND → 공통 GND",
    "2kHz 주파수 구동으로 소리 확인"], "#e4f2ec")
signal(690, "D28", right=True)
box(1000, 795, 405, 167, "HW-479  ·  RGB LED", [
    "D26 → R / D22 → G / D24 → B",
    "모듈 내장 저항 사용 (사용자 확인)",
    "사용자 확인 공통 음극: − → GND",
    "빨강·초록·파랑·노랑·꺼짐 시험 통과"], "#e4f2ec")
signal(880, "26/22/24", right=True)

text(35, 1010, "전원 분리 — +5V 두 선은 합치지 않고, GND만 공통 연결", 26, True)
box(35, 1035, 630, 135, "Mega 5V  ·  USB에서 공급", [
    "DHT11 + LCD (HW-201 미사용)",
    "서보는 이 전원에 연결하지 않음",
    "외부 +5V를 Mega 5V 핀에 병렬 연결하지 않음"], "#e8f3fb")
box(775, 1035, 630, 135, "서보 시험 전원  ·  외부 5V 2A 확인", [
    "10초 동시 구동: 두 서보 움직임 확인",
    "서보는 전원 분배 단자에서 각각 분기",
    "최종 정격은 실제 소비 전류·배선 허용 전류로 선정"], "#fff0e8")
line(665, 1100, 775, 1100, "#ba4a48", True)
text(720, 1080, "연결 금지", 17, True, "#ba4a48", "middle")
line(350, 1170, 350, 1205, "#596a78")
line(1090, 1170, 1090, 1205, "#596a78")
line(350, 1205, 1090, 1205, "#596a78")
box(35, 1225, 1370, 65, "공통 GND: Mega GND = 외부 전원 − = 모든 센서·서보 GND", [], "#e5eaf0")
line(720, 1205, 720, 1225, "#596a78")
box(35, 1315, 1370, 140, "배선 완료 후 코드 조정·부품별 시험", [
    "10초 무부하 동시 시험: 두 서보·LCD·부저 안정성 확인. 실제 기구 부하의 전원 여유는 별도 검증합니다.",
    "MQ-9 ADC 원시값 수신 확인. 표준 CO 측정은 히터 전압 주기와 보정이 별도로 필요합니다.",
    "단자 위치·극성은 실물 표기를 따르세요. 상세 배선·전원 조건·시험 순서: docs/WIRING.md"
], "#fff4df")
parts.append("</svg>")
(ROOT / "docs/wiring.svg").write_text("\n".join(parts), encoding="utf-8")
