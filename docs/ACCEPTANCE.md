# 시연 시험 절차

모든 시험은 먼저 `--simulate`에서 실행합니다. 실물은 핀·전원·센서 설정 확인 후 같은 항목을 반복합니다.

현재 실물 점검은 [bench 연동 안내](INTEGRATION.md)를 따릅니다. MQ-9은 원시값 표시만 하므로 아래 가스 경보 항목은 시뮬레이션 또는 보정 완료 후 production에만 적용합니다. bench의 환기구 명령은 75/90/105도 점검 동작이며 실제 기구 개폐 검증이 아닙니다.

| 시험 | 입력 | 기대 결과 |
|---|---|---|
| 시작 | 정상값, 빈 구역 | 복구 대기 후 NORMAL, 장치 OFF 유지 |
| 명시적 시작 | 정상 상태에서 START | 장치 허가 ON |
| bench 구동 제한 | START 10s 후 같은 RUN 반복 | 최대 10초 후 OFF, 자동 재시작 없음 |
| 미승인 출입 | intrusion | DANGER, 부저 ON, 장치 허가 OFF |
| 임시 승인 | 한 명을 관리자가 확인하고 Approve | 승인 시간 표시, 복구 후 NORMAL, START 전까지 장치 OFF |
| 추가 인원 | 승인 중 two_people | 승인 취소, 경보·장치 차단 |
| 승인 만료 | 30초 동안 사람 유지 | 미승인 경보·차단 |
| 인원 퇴장 | intrusion 다음 normal | 경보 유지; 빈 구역 확인 후 Reset 필요 |
| 온도 상승 | warm | WARNING, 환기구 부분 개방, 장치 OFF |
| 가스 이상 | gas | DANGER, 부저, 환기구 개방, 장치 OFF |
| 센서 오류 | sensor_error | SENSOR_ERROR, 장치 OFF |
| 시리얼 단절 | comm_error 또는 USB 제거 | COMM_ERROR, 호스트 재연결; Mega도 3초 안에 차단 |
| ACK 부재 | 시험용 MCU가 ACK 중단 | 명령 시간 초과, 재연결 |
| 카메라 단절 | camera_error 또는 카메라 USB 제거 | CAMERA_ERROR, 승인 취소, 장치 OFF |
| 복구 후 | 오류 제거 | 정상으로 복구되어도 장치 자동 재시작 안 함 |
| 종료 | 앱 창 닫기 또는 Ctrl+C | 차단 명령 전송, 카메라·시리얼 종료 |

사람 검출 모델의 현장 정확도는 카메라 거리·조명·가림에 영향을 받습니다. 사용 장소에서 한 명·두 명·가려진 사람·빈 구역을 반복 시험합니다. 실제 출입 인원의 신원 승인은 현재 수동 운영 방식입니다.

최신 자동 검증 기록은 `artifacts/integration-tests.log`, `artifacts/integration-live-result.json`, `artifacts/firmware-integration-build.log`를 확인합니다. 이전 단계 기록은 `artifacts/python-tests.log`, `artifacts/gui-check.log`, `artifacts/firmware-build.log`, `artifacts/gpu-check.json`에 있습니다. GPU 검증의 정지 이미지 결과를 실제 카메라의 정확도나 FPS로 표현하지 않습니다.
