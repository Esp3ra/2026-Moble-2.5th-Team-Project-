# Jetson Nano 설비 안전 및 출입 모니터

[GitHub 저장소](https://github.com/Esp3ra/2026-Moble-2.5th-Team-Project-) · [처음 받기·파일 구성](docs/GITHUB.md) · [현재 운영 정책](docs/VENTILATION.md) · [배선 안내](docs/WIRING.md)

Jetson Nano의 GPU로 감시 구역의 사람을 검출하고, Arduino Mega의 온습도·가스 입력과 함께 경보·환기구·장치 작동 허가를 제어합니다. 원래 기획안의 센서·LCD·LED·부저·서보 기능을 포함하며 카메라 용도를 출입 감시로 변경했습니다. 사용자 요청으로 IR 센서는 사용하지 않습니다.

운영 화면은 한글, LCD 상태는 영어입니다. 센서 숫자·최근 60초 그래프, 얼굴 등록·자동 승인, 경보 해제, 긴급 정지, 유입구 열기·닫기, 자동 제어를 제공합니다. 얼굴 등록 정보는 재실행 후에도 유지합니다. **화면상 크기로 가장 가깝다고 추정한 한 명만 출입 판정**하며, 승인자가 앞이면 뒤의 미승인자로 경보를 발생시키지 않습니다. 미승인자가 더 앞이면 경보·설정 잠금을 적용합니다. 자세한 사용법과 거리 추정의 한계는 [현재 운영 안내](docs/VENTILATION.md)를 참고하세요.

## 바로 실행

이 프로젝트는 `/home/moble/2.5th project`에 있습니다. 현재 보드의 Python 3.6, OpenCV 4.1.1, CUDA 10.2, TensorRT 8.2를 사용합니다.

**현재 운영:** 바탕화면 **Moble 연속 환기** 또는 `DISPLAY=:0 bash run_ventilation.sh`. 정상은 D9 0°·D10 저속·초록, 27°C 이상~28°C 미만 또는 MQ-9 원시값 250 이상은 주황·D9 90°·D10 고속입니다. **28°C 이상에서는 온도 자동 정지: 빨강 유지·D9 0°·D10 정지·부저 꺼짐. 27°C 미만이 5초 이상 유지되면 자동 재가동**합니다. 센서·카메라 감시는 계속됩니다. 미승인만으로 부저를 울리거나 온도 자동 정지하지 않으며, 기존 초록/빨강 점멸·설정 잠금은 유지합니다. 수동 긴급 정지와 장치 오류로 인한 정지는 자동 해제하지 않습니다. **펌웨어 정책 버전 6**과 함께 사용합니다. 자세한 동시 경보·복귀 조건은 [현재 운영 안내](docs/VENTILATION.md)를 따릅니다.

아래는 기존 production/bench 모드의 설치·차단 설명입니다. 현재 ventilation 모드의 동작은 위 안내를 따릅니다. 이전 10초 bench 점검은 별도 펌웨어와 `run_integration.sh`으로 유지하며 [연동 점검 안내](docs/INTEGRATION.md)를 참고합니다.

```bash
cd '/home/moble/2.5th project'
# SSH 터미널에서 센서·카메라 없이 전체 제어 흐름 확인
./run.sh --simulate --headless --seconds 15

# Jetson에 연결된 모니터에서 화면 실행
DISPLAY=:0 ./run.sh --simulate

# 설치·연결 상태 확인
python3 monitor.py --diagnose
```

시뮬레이션 화면에서 `intrusion`을 선택하면 미승인 인원 경보와 장치 차단을 확인할 수 있습니다. `gas`, `warm`, `sensor_error`, `comm_error`, `camera_error`도 제공합니다. 시뮬레이션은 실제 장치를 열거나 구동하지 않습니다.

## 기존 production/bench 모드의 출입 승인과 장치 차단

기존 production/bench 프로필에서는 **관리자가 현재 보이는 1명을 30초간 임시 승인하는 방식**을 사용합니다. 현재 ventilation 프로필은 영구 얼굴 등록 후 자동 승인 방식이며 [얼굴 등록 안내](docs/VENTILATION.md)를 따릅니다. `1명 승인`은 얼굴이나 신원을 자동 확인하지 않습니다. 운영자가 직접 사람을 확인하는 시연 방식이며, 같은 인원수로 사람을 바꿔치기하는 상황을 식별하지 못합니다.

- 승인 없는 사람이 한 명이라도 검출되면 경보가 유지되고 장치 허가를 해제합니다.
- 승인 중 두 번째 사람이 나타나거나 승인 시간이 만료되면 다시 경보가 발생합니다.
- 카메라 관측이 끊기면 승인을 취소하고 장치를 차단합니다.
- 사람이 떠나도 침입 경보는 자동으로 해제되지 않습니다. 감시 구역이 비어 있는 것을 확인한 뒤 `경보 해제`을 누릅니다.
- 경보·센서 오류가 복구되어도 장치는 자동 재시작하지 않습니다. 정상 상태에서 `장치 시작`를 눌러야 합니다.
- `긴급 정지`는 PIN 없이 즉시 사용할 수 있습니다. 실물 모드의 승인·해제·시작에는 설정한 관리자 PIN이 필요합니다.

화면의 `Requested`는 송신 명령, `ACK`는 Arduino가 응답한 출력 상태입니다. 실제 릴레이 접점이나 장치의 움직임은 별도 피드백 센서가 없으므로 검증하지 않습니다.

## 실물 연결 순서

2026-10-14 구성은 Mega 2560, DHT11, 5V I2C LCD 2004A, 환기용 SG90, 장치 회전용 SG90 360, MH-FMD, HW-479 RGB LED, MQ-9입니다. HW-201(IR)은 제외합니다. D10 회전 서보, RGB 색 조합, LCD 20×4, 부저 2kHz 구동을 펌웨어에 반영했습니다. LCD 주소는 실측 `0x27`, RGB는 공통 음극·내장 저항 사용입니다. 사용자가 서보용 외부 5V 2A 전원을 확인했고, D9 작은 각도 시험은 통과했습니다. D10은 1초씩 세 차례 시험에서 1600µs 연속 회전과 1500µs 정지가 확인됐습니다. 실제 환기구 각도, MQ-9 구동·예열·임계값 보정이 남아 있습니다. MQ-9의 5V 고정 구동 원시값 시연과 CO 측정을 구분합니다. 상세 내용은 [배선 안내](docs/WIRING.md)에 있습니다.

1. [배선 안내](docs/WIRING.md)의 핀 표와 각 모듈에 인쇄된 `VCC`, `GND`, `DATA`, `AO` 등을 대조합니다.
2. MQ 모델·정격 전압·예열 시간, 서보 전원·각도, LCD 주소, 차단할 장치의 인터페이스를 확인합니다.
3. `firmware/mega_controller/hardware_config.h`에서 확인된 부품만 활성화합니다. `WIRING_CONFIRMED=1`과 실제 `GAS_WARMUP_MS`가 필요하며, 회전 서보 사용 시 `ENABLE_ROTATION_SERVO=1`과 `ROTATION_CALIBRATED=true`가 필요합니다. 현재 보유 D10 서보의 무부하 시험 결과에 따라 이 값은 true로 반영했습니다. 부저는 시험 결과에 맞춰 `BUZZER_ACTIVE=false`, `BUZZER_DRIVE_CONFIRMED=true`로 2kHz 구동을 선택했습니다. IR은 `ENABLE_IR=0`을 유지합니다.
4. Arduino 펌웨어를 컴파일하고 USB로 업로드합니다. 구체적인 명령은 아래에 있습니다.
5. `config/local.example.json`을 `config/local.json`으로 복사하고 포트·ROI·실측 임계값을 설정합니다. `hardware.confirmed`, `hardware.gas_calibrated`는 확인한 뒤 `true`로 바꿉니다.
6. `python3 monitor.py --set-pin`으로 관리자 PIN을 설정합니다.
7. `DISPLAY=:0 ./run.sh`으로 실제 카메라·Arduino 모드를 실행합니다. SSH에서 화면 없이 상태만 확인하려면 `./run.sh --headless`를 사용합니다.

기본 펌웨어는 확인되지 않은 출력을 비활성화하며, 실물 설정이 끝날 때까지 프로그램은 `FAULT`와 차단 상태를 표시합니다. USB 카메라 영상·GPU 사람 검출, Mega 업로드, DHT11 수신, LCD 글자 표시, RGB 네 색 출력과 꺼짐, 주파수 신호를 사용한 부저 소리를 확인했습니다. 두 서보의 기본 구동 및 카메라·GPU와의 짧은 동시 구동도 확인했습니다. 실제 환기구 각도·가스 보정 및 경보·차단 통합 시험은 남아 있습니다.

카메라 화면만 띄우려면 `DISPLAY=:0 python3 scripts/camera_check.py --preview --seconds 0`을 실행합니다. Q/Esc 또는 창 닫기로 종료합니다. 카메라와 GPU만 사용하며 Arduino 출력은 제어하지 않습니다. 전체 모니터와 동시에 실행하면 카메라가 충돌할 수 있으므로 한 프로그램만 실행합니다.

## Arduino 빌드와 업로드

```bash
bash scripts/compile_firmware.sh
# 연결된 보드 목록
.tools/arduino-cli --config-file .tools/arduino-cli.yaml board list
# 실제 Mega 포트로 변경하여 실행
.tools/arduino-cli --config-file .tools/arduino-cli.yaml upload \
  --fqbn arduino:avr:mega --port /dev/ttyUSB0 \
  --input-dir build/mega firmware/mega_controller
```

현재 Mega의 CH340 USB 포트는 `/dev/ttyUSB0`입니다. 사용자 계정 `moble`을 `dialout`에 추가했고, 현재 포트에는 ACL로 읽기·쓰기 권한을 적용했습니다. 기존 로그인 세션의 그룹 갱신은 로그아웃·재로그인 후 적용됩니다. USB 재연결 후 `Permission denied`가 발생하면 먼저 세션의 `id` 출력을 확인합니다.

첫 실물 점검에는 `firmware/hardware_check/hardware_check.ino`를 사용합니다. DHT11, A0 원시값, LCD 주소와 4행 표시만 점검하며 IR과 출력 제어는 사용하지 않습니다. 서보 외부 전원을 끈 상태에서 시험합니다. 진단 스케치는 본 프로그램의 통신 프로토콜과 다르므로, 전체 모니터와 함께 실행하지 않습니다. 센서·출력 보정 완료 후 본 펌웨어를 업로드해 통합 시험합니다.

Jetson에 설치한 **Arduino IDE 1.8.19 ARM64**는 앱 메뉴의 `Arduino Mega (2.5th project)` 또는 `~/.local/bin/arduino-moble`로 실행합니다. Mega 2560, AVR 코어 1.8.6, 프로젝트 라이브러리, 115200 baud를 설정했습니다. [IDE 사용과 메모리 점검](docs/ARDUINO_IDE.md)을 참고합니다. IDE의 시리얼 모니터와 Python 프로그램은 같은 포트를 동시에 열지 않습니다.

## GPU 모델과 추가 설치

카메라 화면은 2026-10-15 사용자 요청으로 **640×480** 설정을 사용합니다. 연결된 카메라에는 MJPEG 60fps를 요청하며 화면 목표는 30fps입니다. 얼굴 인식을 추가하기 전 GPU 사람 감지 통합 화면의 30초 측정은 **평균 26.21fps**로, 이 해상도에서 30fps 유지에는 도달하지 못했습니다. 화면과 GPU 추론을 분리했고, 운영 화면 아래에 실제 표시 FPS가 나옵니다. `camera_at`은 최신 **AI 판정에 사용된 영상 시각**으로 유지해, 미리보기만 움직이고 AI가 멈춘 경우에는 기존처럼 차단합니다. 자세한 결과는 [검증 기록](docs/VALIDATION.md)에 있습니다.

사람 검출은 YOLOv5n v6.0, TensorRT FP16, 320×320 입력으로 실행합니다. 신경망 추론은 CUDA GPU에서 처리하고, 화면 표시·전처리·NMS·센서 판단은 CPU에서 처리합니다. 자동 CPU 대체 실행은 하지 않으며 GPU 추론이 실패하면 차단 상태를 유지합니다.

```bash
# 재설치가 필요한 경우: 프로젝트 내부에 pyserial과 Arduino 도구 설치
python3 scripts/setup.py --arduino
# CLI 다운로드가 불안정하면 공식 배포 파일을 검증해 캐시에 준비
python3 scripts/prefetch_arduino.py
# 모델 다운로드와 이 Jetson용 엔진 생성
python3 scripts/download_model.py
bash scripts/build_engine.sh
# 얼굴 검출·특징 모델 확인 및 엔진 생성
python3 scripts/build_face_engines.py
```

TensorRT 엔진은 이 보드의 GPU·TensorRT 버전에 종속됩니다. 다른 보드에서 사용하려면 다시 빌드합니다. 모델의 출처·SHA256은 `models/yolo-sources.json`, 라이선스는 `models/YOLO_LICENSE`에 있습니다.

## 외장 SSD와 16 GiB 스왑

[SSD 이전 안내](docs/SSD_MIGRATION.md)에 삼성 840 EVO 120GB의 파티션 구성과 부팅·복구 절차를 정리했습니다. 현재 SD 부팅 파일을 사용해 SSD `/dev/sda1`에서 운영체제를 실행하고 있으며, 16 GiB SSD 스왑과 GPU 추론까지 확인했습니다. SSD 단독 부팅 설정은 실제로 적용됐으나 SD 제거 시험에서 NVIDIA 로고에 멈췄습니다. R32.7.6 펌웨어와 설치된 부팅 파일의 해시는 확인됐으며, [부트로더 로그 진단](docs/SSD_BOOT_DIAGNOSTICS.md)이 남아 있습니다. 완료된 SSD에 포맷·복사 명령을 다시 실행하지 않습니다.

## 오류 처리와 기록

USB 시리얼은 2초 간격으로 재연결하고, 센서 패킷은 5초, 명령 ACK는 3초 안에 갱신되어야 합니다. 손상된 JSON과 너무 긴 줄은 버린 뒤 다음 줄부터 복구합니다. 시리얼 장치가 여러 개면 임의로 고르지 않으며 포트를 지정해야 합니다.

카메라와 GPU 추론은 별도 프로세스에서 실행합니다. 프레임이 3초 이상 멈추면 해당 프로세스를 종료하고 재시작합니다. GPU 초기화에는 최대 30초를 허용하며 이 동안 장치는 차단됩니다. Arduino는 호스트 명령이 3초 동안 없으면 독립적으로 장치 허가를 해제합니다. 프로그램의 예기치 않은 종료는 `run.sh`가 최대 3회 재시작합니다.

센서 임계값에는 히스테리시스를 적용하고, 위험 상태에서 정상으로 복구할 때 2초의 안정 시간을 둡니다. 로그는 `logs/monitor.log`와 CSV에 기록합니다. CSV에는 실제·시뮬레이션 여부가 구분됩니다. 사진과 동영상은 기본적으로 저장하지 않습니다.

## 검증과 구성

```bash
python3 -m unittest discover -s tests -v
DISPLAY=:0 python3 scripts/gui_check.py
python3 scripts/gpu_check.py
```

- `app/`: 제어·통신·GPU 추론·출입 승인·Tk 화면
- `firmware/`: Arduino Mega 코드와 I2C 스캐너
- `config/`: 기본값과 실물 설정 예시
- `docs/`: 배선·통신·시험 절차
- `artifacts/`: 검증 로그와 화면 캡처
- `models/`: 모델·이 보드용 TensorRT 엔진

이 결과물은 교육용 시제품입니다. RGB 카메라로 온도·가스를 직접 측정하지 않으며, DHT11은 공기 온도를, MQ는 보정 전 원시 ADC 값을 제공합니다. 실제 산업용 안전 인터록은 인증된 별도 장치가 필요합니다.
