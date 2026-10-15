# Jetson과 Mega 통신 규격

현재 `ventilation` 프로필은 이 문서 끝의 **ventilation 확장 (정책 버전 6)**를 함께 적용합니다. 기존 장치 차단 규칙과 다른 환기 우선순위는 [연속 환기 안내](VENTILATION.md)를 참고하세요.

USB 시리얼 115200 baud, UTF-8로 표현 가능한 ASCII JSON을 한 줄에 한 패킷씩 전송합니다. 줄 끝은 LF이며 CRLF도 수신 가능합니다. 버전은 `v:1`입니다.

## 센서 보고

```json
{"v":1,"type":"telemetry","seq":10,"uptime_ms":5000,"temperature":26.0,"humidity":50.0,"gas_raw":180,"ir_detected":null,"sensor_ok":true,"hardware_ready":true,"profile":"bench","gas_guard":false,"bench_run_ms":10000,"state":"NORMAL","vent":"CLOSED","device_enable":false,"fault":""}
```

Mega는 500ms마다 전송하고 DHT11·가스는 2500ms마다 측정합니다. 잘못되거나 미연결인 측정값은 `null`로 보내며 `sensor_ok=false`입니다. 온도는 DHT11 범위 0~50°C, 습도는 0~100%, 가스는 ADC 0~1023 범위를 검증합니다. MQ의 레일 부근 값은 펌웨어에서 센서 오류로 취급합니다. IR이 비활성화되면 `null`입니다.

위 예시는 실물 점검용 bench 프로필입니다. `gas_guard=false`는 가스 경보가 적용되지 않는다는 뜻이며 ADC 수신만 검증합니다. `bench_run_ms=10000`은 MCU의 독립 구동 제한입니다. production은 `profile="production"`, `gas_guard=true`, `bench_run_ms=0`이며 하드웨어 준비·가스 예열 및 보정 조건을 별도로 충족해야 합니다.

## 출력 명령

```json
{"v":1,"type":"command","seq":20,"session":12345,"state":"DANGER","vent":"OPEN","buzzer":true,"device_enable":false}
```

- `state`: NORMAL / WARNING / DANGER / FAULT
- `vent`: CLOSED / PARTIAL / OPEN / SAFE
- `device_enable`: NORMAL이고 센서·하드웨어가 준비된 경우에만 true 적용
- `session`: 프로그램 시작마다 생성되는 세션 번호
- `seq`: 같은 세션에서 단조 증가. 중복·역순은 거부

호스트는 500ms마다 최신 명령을 준비하고 센서 보고를 받은 직후 한 개를 전송합니다. Mega는 DHT 읽기와 LCD 갱신을 센서 보고 전에 끝내 명령 수신 중 긴 작업을 피합니다. 유효 명령을 3초간 못 받으면 독립적으로 차단합니다. 새 세션의 첫 명령은 `device_enable=false`여야 합니다.

## 응답

```json
{"v":1,"type":"ack","seq":20,"session":12345,"accepted":true,"state":"DANGER","vent":"OPEN","device_enable":false,"fault":""}
```

ACK의 상태는 펌웨어가 적용한 결과입니다. MCU의 센서 오류나 자체 위험 판단이 명령보다 우선하면 요청과 달라질 수 있습니다. 호스트는 세션·순번이 일치하고 명령을 수락한 응답 중, 요청한 상태·환기·구동과 일치하는 결과 또는 명시적인 MCU 차단을 확인 처리합니다. MCU 차단은 `device_enable=false`와 WARNING/DANGER/FAULT 상태 또는 `fault="BENCH_LIMIT"`으로 표시합니다. 요청하지 않은 RUN 응답은 거부합니다. ACK 부재 또는 불일치가 이어지면 재연결하고 장치를 차단합니다.

bench 구동 중 반복 RUN 명령은 10초 제한을 연장하지 않습니다. MCU 차단 응답을 받으면 호스트도 START 요청을 취소하고, 이후 새 운전은 별도 STOP 및 명시적 START가 필요합니다.

이 ACK는 소프트웨어 출력 확인입니다. 서보 위치 센서나 릴레이 접점 피드백을 대신하지 않습니다.
# ventilation 확장 (정책 버전 6)

현재 연속 환기 모드의 명령에는 `profile:"ventilation"`, `fan:"OFF|LOW|HIGH"`, `settings_locked:boolean`, `access_alert:boolean`, `vent_mode:"AUTO|OPEN|CLOSED"`, `emergency_stop:boolean`, `alarm_acknowledged:boolean`을 추가합니다. `WARNING`은 환경 경고, `DANGER`는 미승인만 있는 상태입니다. 동시 경보는 `WARNING`과 `access_alert:true`를 함께 보내며 MCU가 주황/빨강 400ms 교대 점멸합니다. 환경 환기 동작과 출입 잠금을 별도로 보존합니다.

텔레메트리는 `policy_rev:6`, `gas_mode:"raw_demo"`, `bench_run_ms:0`, 온도 경고/해제 27/27·위험 28과 원시 가스 경고/해제 250/210, `fan`, `environment_alert`, `settings_locked`, `access_alert`를 보고합니다. `environment_alert`는 MCU 자체 센서 조건이며 호스트가 명령한 WARNING과 별개입니다. 호스트는 프로필·정책·임계값 불일치 시 차단합니다.

ACK는 위 fan/권한 필드 및 실제 적용 state/vent/device_enable을 반환합니다. MCU 자체 환경 경고 때문에 이미 허가된 LOW가 HIGH로 바뀌는 ACK는 허용하지만, OFF 명령에 대한 RUN 응답은 거부합니다. STOP과 FAULT는 환경 고속 운전보다 우선합니다. 시작 세션의 첫 명령은 OFF여야 하고, 3초 하트비트 시간 초과 시 OFF입니다. 기존 JSON Lines v1 프레이밍과 순서 번호 검사는 유지합니다.

정상 자동 운전은 CLOSED(0°), 환경 경고는 OPEN(90°)입니다. 미승인만 있을 때는 초록/빨강을 400ms 교대로 표시합니다. 수동 vent_mode는 설정 잠금이 없을 때만 적용하고 AUTO는 센서 기준으로 돌아갑니다. emergency_stop=true이면 fan=OFF·device_enable=false·vent=CLOSED이어야 하며 LED·부저도 끕니다. alarm_acknowledged는 현재 경보음을 해제하되 상태·출입 잠금을 해제하지 않습니다. 이 세 필드는 ACK와 텔레메트리에도 포함합니다. 새 환경 원인은 MCU에서도 경보음을 재활성화합니다.

LCD는 NORMAL / CAUTION / UNAUTHORIZED / DANGER / STOPPED / DEVICE ERROR를 표시합니다. UI와 LCD 문구는 통신 내부 상태 코드와 구분합니다.


부저 음량 조정 후 ventilation 텔레메트리에 `buzzer_duty_percent:5`이 추가됩니다. 진단용 파형 듀티 값이며 체감 음량이나 dB 측정값이 아닙니다. JSON v1과 정책 버전 6은 유지합니다.

## 온도 자동 정지 필드 (정책 버전 6)

ventilation 명령은 `temperature_stop:boolean`을 필수로 포함합니다. true이면 `device_enable:false`, `fan:"OFF"`, `vent:"CLOSED"`여야 합니다. 이 필드는 수동 `emergency_stop`과 독립적입니다. MCU는 로컬 센서 정지와 호스트 정지 중 하나라도 true이면 수동 OPEN보다 우선해 D9 0°·D10 OFF를 적용합니다. 빨강은 유지하고 부저는 끕니다. LCD는 TEMP AUTO STOP입니다.

텔레메트리는 `temp_red:28`, `temp_restart_ms:5000`, `local_temperature_stop`(MCU 자체 온도 정지), `temperature_stop`(MCU 자체 또는 호스트 요청으로 적용된 온도 정지)를 보고합니다. ACK의 `temperature_stop`도 적용 결과입니다. 호스트는 자기 요청의 반향이 복귀를 영구 차단하지 않도록 자체 타이머와 `local_temperature_stop`으로 판단합니다. ACK가 명시한 온도 정지이고 장치 오류·수동 긴급 정지가 없을 때만 자동 복귀 대상으로 구분합니다. 기타 MCU 차단은 기존처럼 수동 복귀가 필요합니다.

28°C 이상에서 즉시 정지하고, 유효한 27°C 미만 값이 5초 이상 유지되면 해제합니다. MCU는 새 측정 때만 복귀를 평가합니다. 온도 자동 정지는 주황 구간으로 내려와도 유지되고, 수동 긴급 정지·장치 오류는 온도 복귀로 해제되지 않습니다. Python 수신 프레이밍 최대 길이는 새 텔레메트리를 수용하도록 1024바이트이며 MCU 명령 버퍼는 384바이트입니다.
