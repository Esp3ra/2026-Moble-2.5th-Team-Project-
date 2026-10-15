"""Korean presentation text; protocol and recorded state codes stay unchanged."""

STATES = {'NORMAL': '정상 운전', 'WARNING': '환경 경고', 'DANGER': '위험 경보', 'FAULT': '장치 오류'}
ACCESS = {'UNKNOWN': '확인 불가', 'CLEARING': '빈 구역 확인 중', 'CLEAR': '감시 구역 비어 있음',
          'AUTHORIZED': '승인된 인원', 'UNAUTHORIZED': '미승인 경보',
          'GREEN': '정상 표식', 'RED': '이상 표식'}
FANS = {'OFF': '정지', 'LOW': '기본 속도', 'HIGH': '고속'}
VENTS = {'OPEN': '열림', 'CLOSED': '닫힘', 'PARTIAL': '부분 열림', 'SAFE': '현재 위치 유지'}
MODES = {'AUTO': '자동', 'MANUAL': '수동', 'STOP': '긴급 정지', 'TEMP_STOP': '온도 자동 정지'}
SCENARIOS = {'normal': '정상', 'intrusion': '미승인 인원', 'two_people': '두 명 감지',
             'warm': '온도 주의', 'hot': '온도 위험', 'gas': '가스 경고', 'warm_intrusion': '온도 주의 + 미승인',
             'hot_intrusion': '온도 위험 + 미승인',
             'gas_intrusion': '가스 경고 + 미승인', 'sensor_error': '센서 오류',
             'comm_error': '통신 오류', 'camera_error': '카메라 오류'}

REASONS = {
    'TEMPERATURE_AUTO_STOP': '온도 위험으로 자동 정지',
    'TEMPERATURE_COOLING_WAIT': '27°C 미만 안정 상태 확인 중',
    'COMM_ERROR': '아두이노 통신 끊김', 'CAMERA_ERROR': '카메라 연결 또는 영상 처리 오류',
    'VISION_UNKNOWN': '카메라 인원 확인 대기', 'CONFIG_REQUIRED': '하드웨어 설정·보정 필요',
    'SENSOR_ERROR': '센서값 수신 오류', 'HARDWARE_NOT_READY': '센서·LCD 연결 확인 필요',
    'FIRMWARE_PROFILE_MISMATCH': '프로그램과 아두이노 펌웨어의 운영 모드 불일치',
    'BENCH_LIMIT_NOT_CONFIRMED': '시험 운전 시간 제한 확인 필요',
    'VENTILATION_POLICY_MISMATCH': '프로그램과 아두이노의 환기 설정 불일치',
    'IR_ERROR': '적외선 센서 오류', 'LOG_ERROR': '점검 기록 저장 실패',
    'ADMIN_PIN_REQUIRED': '관리자 PIN 최초 설정 필요', 'HIGH_TEMPERATURE': '온도 기준 초과',
    'GAS_RESPONSE': '가스 센서 원시값 기준 초과', 'IR_DETECTED': '적외선 센서 감지',
    'VISUAL_ABNORMAL': '영상 이상 감지', 'UNAUTHORIZED_PERSON': '미승인 인원 경보',
    'DANGER_CONDITION': '위험 조건 감지', 'RECOVERY_WAIT': '정상 복귀 확인 중',
    'STARTUP': '초기화 중', 'BAD_COMMAND': '제어 명령 형식 오류',
    'BAD_FAN_COMMAND': '팬 제어 명령 오류', 'REPLAY_COMMAND': '중복·이전 제어 명령 거부',
    'SESSION_NOT_ARMED': '통신 초기화 확인 필요', 'LINE_OVERFLOW': '통신 메시지 길이 초과',
    'LCD_I2C_ERROR': 'LCD 통신 오류', 'BENCH_LIMIT': '시험 운전 시간 종료',
}

ERRORS = {
    'Use at least 6 numeric digits': 'PIN은 숫자 6자리 이상으로 입력해 주세요.',
    'Wait before retrying administrator PIN': 'PIN 입력을 여러 번 실패했습니다. 잠시 기다린 뒤 다시 시도해 주세요.',
    'Invalid PIN; configure it with --set-pin': '관리자 PIN이 일치하지 않습니다. 설정한 PIN을 다시 입력해 주세요.',
    'An administrator PIN is already configured': '관리자 PIN이 이미 설정돼 있습니다.',
    'Fresh camera observation required': '최신 카메라 영상이 확인된 뒤 인원을 승인할 수 있습니다.',
    'Approval requires exactly one visible person': '감시 구역에 한 명만 보일 때 승인할 수 있습니다.',
    'Clear the monitored area before resetting': '감시 구역에 사람이 없는지 확인한 뒤 경보를 해제해 주세요.',
    'Start blocked: clear all alarms and faults first': '시작할 수 없습니다. 경보와 장치 오류를 먼저 해제해 주세요.',
    'Wait for device health': '센서와 장치 연결 상태를 확인하고 있습니다. 잠시 기다려 주세요.',
    'Already running; STOP before starting another bench run': '이미 시험 운전 중입니다. 먼저 정지한 뒤 다시 시작해 주세요.',
    'Invalid manual vent target': '유입구 제어 위치가 올바르지 않습니다.',
    'Unknown action': '지원하지 않는 조작입니다.', 'Unknown scenario': '지원하지 않는 시연 상황입니다.',
    'ROI must be [x, y, width, height]': '감시 구역의 위치와 크기가 올바르지 않습니다.',
    'ROI is outside the frame': '감시 구역은 영상 안에서 지정해 주세요.',
}


def reason_text(code):
    if code.startswith('MCU_'):
        return '아두이노: ' + reason_text(code[4:])
    return REASONS.get(code, '알 수 없는 상태 ({})'.format(code))


def error_text(error):
    text = str(error)
    if text in ERRORS:
        return ERRORS[text]
    if any('\uac00' <= c <= '\ud7a3' for c in text):
        return text
    if isinstance(error, OSError):
        return '설정을 저장하지 못했습니다. 저장 공간과 파일 접근 권한을 확인해 주세요.'
    return '처리 중 오류가 발생했습니다. 다시 시도하고, 계속되면 점검 기록을 확인해 주세요.'
