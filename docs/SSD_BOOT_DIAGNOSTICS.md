# SSD 단독 부팅 실패 진단

2026년 10월 14일 SSD 단독 부팅 설정을 적용했지만 SD를 제거하면 NVIDIA 로고에서 멈췄습니다. 설치된 설정과 initrd의 SHA256은 준비된 파일과 일치합니다. 현재는 SD 부팅 파일을 이용해 SSD 운영체제로 복구한 상태입니다.

## 확인된 상태

| 항목 | 확인 결과 |
|---|---|
| 현재 운영체제 `/` | SSD `/dev/sda1` |
| SSD 스왑 | `/dev/sda2`, 16 GiB 활성화 |
| 실제 부트 펌웨어 조회 | R32.7.6, NV3, Nano BOARDID 3448 |
| SSD 단독 부팅 파일 | 적용됨, 설정과 initrd 해시 일치 |
| 현재 커널 명령줄 | 단독 부팅 메뉴 표시 없음, SD의 SSD 루트 메뉴 사용 |
| 이전 실패 부팅의 로그 | 현재 journal에는 이번 성공 부팅만 있고 pstore는 비어 있음 |
| 실패 원인 | 미확정. 로고만으로 펌웨어·USB 인식·파일 읽기·커널 진입 중 어디인지 구분할 수 없음 |

SD카드를 부팅용으로 유지해도 현재 운영체제·프로젝트·SSD 스왑은 SSD에서 실행됩니다. 운영 중에는 SD와 SSD를 연결한 상태로 유지합니다. SSD 재포맷이나 운영체제 재복사는 다음 진단에 필요하지 않습니다.

## 필요한 로그

3.3V USB–TTL 시리얼 어댑터를 노트북에 연결해 Nano의 부트 콘솔 로그를 전원을 넣는 순간부터 저장합니다. 어댑터 모델과 보드 핀 방향을 확인한 뒤 배선합니다. 5V TTL이나 RS-232를 직접 연결하지 않습니다. Jetson 전원은 원래 전원을 사용합니다.

NVIDIA는 U-Boot 배너가 나온 뒤 키를 눌러 자동 부팅을 중단하고 콘솔에서 조사하는 절차를 안내합니다. 일반 SSH는 Linux가 실행된 뒤에 접속하므로 이 초기 단계의 실패 로그를 직접 읽을 수 없습니다. [NVIDIA U-Boot 디버깅 문서](https://docs.nvidia.com/jetson/l4t/Tegra%20Linux%20Driver%20Package%20Development%20Guide/uboot_guide.html)

아래는 **Linux/SSH 터미널이 아닌 U-Boot 콘솔**에서 확인할 항목입니다. 먼저 배너까지 도달하는지 기록합니다.

```text
version
printenv boot_targets
help usb
usb start
usb storage
```

USB 저장장치가 검출되면 `usb storage`에 나온 실제 장치 번호로 파티션과 `/boot` 디렉터리를 조회합니다. SSD가 장치 0이고 첫 파티션에 rootfs가 있는 경우의 예시는 다음과 같습니다.

```text
part list usb 0
ls usb 0:1 /boot
ls usb 0:1 /boot/extlinux
```

여기까지는 펌웨어나 부팅 순서를 저장하지 않는 진단입니다. `saveenv`, 플래시 기록, 파티션 초기화는 로그 판독 전에 실행하지 않습니다.

## 결과에 따라 확인할 부분

- U-Boot 배너에 도달하지 못하면 그 앞 단계의 직렬 로그로 QSPI 부트 흐름을 확인합니다.
- U-Boot에서 SSD가 보이지 않으면 USB 초기화 오류·전원·연결·어댑터 인식을 확인합니다.
- SSD는 보이지만 `/boot`를 읽지 못하면 장치 번호·파티션·파일시스템 지원과 오류를 확인합니다.
- `/boot`까지 읽히면 실제 `boot_targets`와 extlinux 선택, 커널·DTB·initrd 로딩 결과를 확인합니다.
- 커널이 시작된 뒤 멈추면 그 커널 로그에서 USB 루트 마운트나 장치 초기화 오류를 확인합니다.

USB 주변기기와 부팅 순서가 관련된 Nano 사례가 있지만, 이번 보드의 원인으로 확정한 것은 아닙니다. [NVIDIA 지원 답변](https://forums.developer.nvidia.com/t/nano-4gb-kit-boot-issues-from-ssd/174149)
