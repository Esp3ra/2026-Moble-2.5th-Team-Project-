# Jetson의 Arduino IDE와 메모리 점검

2026-10-14 Jetson Nano ARM64, Ubuntu 18.04.6에 **Arduino IDE 1.8.19 ARM64**를 사용자 계정으로 설치했습니다. 공식 배포 파일의 MD5를 공식 체크섬 목록과 대조했습니다. IDE 실행, 본 펌웨어 컴파일, 센서 진단 스케치의 실제 Mega 업로드를 확인했습니다.

## 실행과 보드 설정

바탕화면 또는 앱 메뉴에서 **Arduino Mega (2.5th project)**를 엽니다. 본 펌웨어 `firmware/mega_controller/mega_controller.ino`가 열립니다. 터미널에서는 다음 명령을 사용합니다.

```bash
~/.local/bin/arduino-moble
# SSH에서 Jetson에 연결된 모니터로 표시할 때
DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority \
  ~/.local/bin/arduino-moble '/home/moble/2.5th project/firmware/mega_controller/mega_controller.ino'
```

- 보드: **Arduino Mega or Mega 2560**
- 프로세서: **ATmega2560 (Mega 2560)**
- 포트: 현재 **/dev/ttyUSB0** (CH340; USB 재연결 시 번호 확인)
- 시리얼 모니터: **115200 baud**
- AVR 코어: **1.8.6**
- 라이브러리: ArduinoJson, DHT sensor library, Adafruit Unified Sensor, LiquidCrystal_I2C, Servo

`~/.arduino15/packages/arduino`는 프로젝트의 `.tools/arduino-data/packages/arduino`를, 스케치북은 `.tools/arduino-user`를 사용합니다. 따라서 프로젝트의 `.tools`를 옮기거나 삭제하면 IDE 설정도 다시 연결해야 합니다. AVR 보드와 라이브러리 설정은 기존 CLI 작업 환경과 공유합니다.

IDE에서 확인 버튼(✓)은 컴파일만 수행하고, 업로드 버튼(→)은 Mega의 프로그램을 교체합니다. 현재 보드에는 `hardware_check`가 올라가 있으며, DHT11·A0·LCD를 점검합니다. IR은 사용하지 않고 부저·서보·RGB 출력은 비활성입니다. 전체 모니터용 `mega_controller`는 출력 보정과 설정을 마친 다음 올립니다. 본 펌웨어의 기본 설정은 확인되지 않은 실물 출력을 차단합니다.

IDE의 시리얼 모니터와 Python 모니터는 같은 포트를 동시에 열지 않습니다. CLI 업로드를 할 때도 IDE의 시리얼 모니터를 먼저 닫습니다.

## 개별 부품 시험 스케치

각 폴더의 이름과 같은 `.ino` 파일을 IDE에서 열고 Mega로 업로드합니다. 한 번에 하나의 스케치만 Mega에서 실행됩니다. 출력 시험은 확인된 전원·배선에서만 수행합니다.

| 파일 | 동작 |
|---|---|
| `firmware/hardware_check/hardware_check.ino` | 온습도·A0·LCD만 확인. 서보·RGB·부저 구동 없음 |
| `firmware/rgb_check/rgb_check.ino` | 리셋 후 5초 대기, 빨강·초록·파랑·노랑을 한 번씩 표시한 뒤 끔. 공통 음극·내장 저항 모듈 기준 |
| `firmware/buzzer_check/buzzer_check.ino` | 리셋 후 5초 대기, 1kHz와 2kHz 소리를 각각 2.5초 시험한 뒤 핀을 입력 상태로 복구 |
| `firmware/servo_check/servo_check.ino` | 부팅 시 구동하지 않음. 아래 명령을 받아 제한된 시험만 수행 |
| `firmware/power_check/power_check.ino` | LCD 백라이트 ON, RGB 흰색·2kHz 부저·서보 두 개 동시 시험. 아래 전용 실행 도구 사용 |

서보는 별도 정전압 5V 전원과 공통 GND가 필요합니다. 현재 사용자는 외부 5V 2A 공급을 확인했습니다. 축에 기구 부하가 걸리지 않은 상태에서 시리얼 모니터를 **115200 baud, 새 줄(Newline)**로 설정하고 다음 명령을 하나씩 보냅니다.

- `VENT`: D9 서보를 90 → 75 → 105 → 90도로 움직인 뒤 신호를 해제합니다.
- `NEUTRAL`: D10에 1500µs를 약 3초 공급합니다. 실제 축이 멈춰 있는지 관찰합니다.
- `RUN`: **1500µs에서 실제 정지가 확인된 경우에만 사용합니다.** D10에 1600µs를 0.6초 공급한 뒤 1500µs로 돌려놓고 신호를 해제합니다.
- `ONESEC`: 1500µs로 1초 대기한 다음, 1600µs 1초 → 1500µs 1초를 세 번 반복합니다. LCD에 RUN/STOP과 반복 번호를 표시합니다. RUN 동안 계속 회전하고 STOP에서 그 위치에 멈추는지, 두 각도 사이를 오가는지 관찰해 제어 유형을 구분합니다. 표시의 STOP은 1500µs 신호를 뜻하며 실물 정지를 보증하지 않습니다.
- `STOP`: 현재 시험을 중단하고 신호를 해제합니다. 회전형에는 해제 전에 1500µs를 보냅니다. 전원 차단 기능은 아닙니다.

중립에서 계속 돌거나 기구가 걸리면 서보 전원을 끄고 보정합니다. 이 시험의 작은 각도 이동은 실제 환기구 닫힘·열림 각도 보정을 대신하지 않습니다. 시험이 끝나면 `hardware_check`로 복구합니다.

## LCD 밝기와 동시 구동 점검

현재 LiquidCrystal_I2C 라이브러리의 `backlight()`는 백라이트를 계속 켜며, `setBacklight()`도 0=OFF, 그 밖의 값=ON으로 처리합니다. 밝기 PWM은 제공하지 않으므로 ON이 현재 소프트웨어에서 가능한 최대 설정입니다.

`scripts/power_check.py`는 컴파일된 `build/power-check`를 업로드하고 카메라·GPU 영상과 센서 수신을 확인한 다음, RGB 세 채널과 2kHz 부저를 켠 채 D9의 75/90/105도 이동과 D10의 1600/1500µs 구동·정지를 동시에 실행합니다. 각 단계는 1초이며 기본은 세 쌍 약 6초, `--seconds 10`은 다섯 쌍 약 10초, `--seconds 30`은 열다섯 쌍 약 30초입니다. 끝나면 센서 진단 펌웨어를 복구합니다. IR은 사용하지 않으며 MQ-9은 기존 전원 상태의 ADC 원시값만 읽습니다.

전원과 배선이 현재 검증한 상태이고 서보에 기구 부하가 없을 때 실행합니다. 이 스크립트는 실제 장치를 움직입니다. IDE 시리얼 모니터와 다른 카메라 프로그램을 닫습니다.

```bash
cd '/home/moble/2.5th project'
.tools/arduino-cli --config-file .tools/arduino-cli.yaml compile --jobs 1 --fqbn arduino:avr:mega --output-dir build/power-check firmware/power_check
.tools/arduino-cli --config-file .tools/arduino-cli.yaml compile --jobs 1 --fqbn arduino:avr:mega --output-dir build/hardware-check firmware/hardware_check
python3 scripts/power_check.py
# 30초 동시 구동 + Jetson 화면에 영상 표시 (Q/Esc로 중단)
DISPLAY=:0 python3 scripts/power_check.py --seconds 30 --preview
```

호스트의 한 바이트 하트비트(`!`)가 1.5초 이상 끊기거나 센서·I2C 오류가 발생하면 구동을 중단하며, 독립적인 시간 제한과 AVR 워치독도 사용합니다. 업로드·포트 열기 때문에 발생하는 시작 재설정과 시험 중의 예상치 않은 재설정을 구분합니다. 시험 기록은 `artifacts/power-check-result.json`과 `power-check-sequence.json`에 저장합니다. 외부 서보 전원 전압·전류는 측정하지 않으므로, 기록상 오류가 없다는 결과만으로 순간 전압 강하나 실제 기구 부하에서의 전원 여유를 보증하지 않습니다.

## 메모리 사용을 줄인 설정

- 실행 스크립트 `~/.local/bin/arduino-moble`: JVM 초기 힙 32MiB, 최대 힙 256MiB, Serial GC. **256MiB는 자바 힙 한도이며 프로세스 전체 RAM 한도가 아닙니다.**
- IDE의 `arduino-builder` 실행 파일은 원본을 `arduino-builder-original`로 보존하고, `-jobs=1`을 전달하는 래퍼를 두었습니다. 따라서 동시에 실행하는 컴파일러는 1개입니다.
- 기존 CLI 빌드도 `scripts/compile_firmware.sh`에서 `--jobs 1`을 사용합니다.
- IDE 버전 업데이트 자동 확인을 껐습니다. 설치 위치는 `~/.local/opt/arduino-1.8.19`입니다.

IDE 창을 연 직후 자바 프로세스의 RSS는 약 **144MiB**였습니다. 편집 파일과 컴파일에 따라 변합니다.

## 로우메모리 경고 조사

처음 점검 시 물리 RAM 3.9GiB 중 약 3.4GiB를 사용했고, 사용 가능 RAM은 약 300MiB였습니다. VS Code 원격 확장 호스트가 RAM 약 1.7GiB와 스왑 약 1.9GiB를 사용했습니다. 확인 가능한 커널 로그에는 OOM 강제 종료 기록이 없었습니다. 사용자 경고 문구 자체는 아직 확보하지 않았으므로 특정 프로그램의 오류 원인까지 확정한 것은 아닙니다.

SSD의 `/dev/sda2` 16GiB 스왑은 활성 상태이며, 약 1.9GiB zram과 함께 작동합니다. 스왑 부족이나 SSD 용량 부족은 관찰되지 않았습니다. 스왑은 물리 RAM과 같지 않으며, RAM이 부족하면 스왑 입출력으로 응답이 느려질 수 있습니다. 메모리 압박 중에 `swapoff`를 실행하지 않습니다.

현재 연결과 작업도 VS Code 확장 호스트를 사용하므로 프로세스를 강제 종료하지 않았습니다. 작업을 저장한 뒤 VS Code에서 **Ctrl+Shift+P → Developer: Reload Window**를 실행하고 아래 명령으로 사용량이 줄었는지 확인합니다. 원격 작업 연결이 잠시 끊길 수 있습니다. 반복해서 메모리가 늘면 VS Code의 실행 중인 확장 진단과 경고 원문 확인이 필요합니다.

```bash
free -h
swapon --show
ps -eo pid,ppid,rss,comm --sort=-rss | head -n 12
```

실물 모니터 운전 중에는 업로드를 끝낸 IDE와 불필요한 편집 창을 닫아 여유 RAM을 확보합니다. 측정 자료는 `artifacts/memory-check.json`, IDE 업로드 결과는 `artifacts/ide-hardware-check-upload.log`에 있습니다.

## 공식 자료

- [Arduino 다운로드](https://www.arduino.cc/en/software/): 최신 IDE와 Legacy IDE 안내
- [Arduino 공식 ARM64 다운로드 링크가 있는 페이지](https://academy.arduino.cc/pages/download-software): Legacy 1.8.19의 Linux ARM 64 bits
- [1.8.19 공식 체크섬](https://downloads.arduino.cc/arduino-1.8.19.md5sum.txt)
- [IDE 1.8.19 명령행 안내](https://github.com/arduino/Arduino/blob/1.8.19/build/shared/manpage.adoc)
