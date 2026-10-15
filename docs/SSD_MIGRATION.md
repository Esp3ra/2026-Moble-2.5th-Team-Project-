# Jetson Nano 외장 SSD 이전과 16 GiB 스왑

현재 SD카드의 Ubuntu 18.04.6, L4T 32.7.1, CUDA 10.2, TensorRT와 프로젝트를 삼성 외장 SSD로 이전했습니다. 운영체제 버전은 유지했습니다. **SSD 파티션 생성·복사·72개 파일 검증이 완료됐고, 현재 SD 부팅 파일을 통해 SSD `/dev/sda1`에서 운영체제를 실행하며 16 GiB SSD 스왑도 활성화됐습니다. SSD 자체 부팅 파일을 사용하는 추가 설정도 적용됐지만, SD 제거 시험에서 다시 NVIDIA 로고에 멈췄습니다. 이후 SD를 사용하는 기존 구성으로 복구했습니다. SD 없는 단독 부팅은 아직 성공하지 않았습니다.**

## SD 없이 SSD 단독 부팅하기

**현재 상태:** 아래 설정은 이미 적용했습니다. `/boot/extlinux/extlinux.conf`와 `/boot/initrd.moble-standalone`의 해시가 준비된 파일과 일치합니다. 같은 적용 명령을 반복하거나 SSD를 다시 포맷하지 않습니다. 다음 단계는 [UART 부트 로그 진단](SSD_BOOT_DIAGNOSTICS.md)입니다. 아래 실행 절차는 적용한 설정의 기록입니다.

사용자 터미널에서 `sudo /usr/sbin/l4t_payload_updater_t210 -v`로 조회한 실제 QSPI 펌웨어는 **R32.7.6, NV3, BOARDID 3448 / BOARDSKU 0000 / FAB 300**입니다. SSD 운영체제와 설치된 NVIDIA 패키지는 R32.7.1입니다. 현재 SSD 운영체제와 GPU 추론은 정상 실행됐습니다. USB 부팅을 지원하는 세대의 펌웨어이므로, 이번 설정에서는 QSPI를 다시 기록하지 않습니다. 단독 부팅이 실패한 정확한 원인은 아직 확인되지 않았습니다.

`scripts/enable_ssd_standalone.py`는 **현재 SSD 운영체제에서 실행하는 별도 설정 도구**입니다. 이전·포맷 스크립트를 다시 실행하지 않습니다. 준비된 파일은 `artifacts/ssd-standalone/`에 있으며 다음을 구성합니다.

- 커널 `/boot/Image`, 현재 Nano B01용 DTB, 새 `initrd.moble-standalone`을 모두 SSD에서 읽습니다.
- 루트 파일시스템은 SSD의 GPT PARTUUID로 지정합니다.
- 초기 부팅에서 SSD 마운트를 최대 약 30초간 재시도합니다. 이 메뉴에는 SD로 돌아가는 마운트 경로가 없습니다.
- 부팅 메시지를 표시하고, 실제로 이 메뉴를 사용했는지 확인할 수 있는 표시를 커널 명령줄에 넣습니다.
- 기존 SSD 부팅 메뉴와 `/boot/extlinux/extlinux.conf.before-standalone` 백업을 유지합니다. SD카드의 부팅 설정과 내부 QSPI 펌웨어는 변경하지 않습니다.

준비된 설정 적용에는 관리자 인증이 필요합니다.

```bash
cd '/home/moble/2.5th project'
sudo python3 scripts/enable_ssd_standalone.py --apply
```

이 명령은 먼저 NVIDIA의 `l4t_payload_updater_t210 -v`로 **실제 부트 펌웨어 버전만 조회**하고 `artifacts/ssd-standalone/firmware-version.txt`에 기록합니다. 설치된 `nvidia-l4t-bootloader` 패키지 버전만으로 실제 플래시 상태를 단정하지 않습니다. 버전 조회에 실패하거나 준비 이후 파일이 달라졌으면 적용을 중단합니다. 펌웨어를 업데이트하거나 자동 재부팅하지 않습니다.

`INSTALLED: SSD-local kernel, device tree and initrd configuration.`이 출력되면 SSD의 부팅 파일 설치가 끝난 것입니다. **설치 성공은 SD 없는 부팅 성공과 다릅니다.** Nano의 QSPI/U-Boot가 USB 저장장치에서 부팅 파일을 읽는 과정도 성공해야 합니다. NVIDIA 로고에서 멈춘 원인은 아직 직렬 부트 로그로 확정하지 않았습니다.

시험할 때는 저장할 작업을 마무리하고 `sudo poweroff`로 전원을 끕니다. 완전히 꺼진 뒤 SD카드를 빼고 SSD를 연결한 채 켭니다. 첫 시험에서는 SSD 외의 불필요한 USB 장치를 분리해 USB 부팅 인식 문제를 좁힐 수 있습니다. 부팅이 끝나면 다음을 실행합니다.

```bash
cd '/home/moble/2.5th project'
python3 scripts/enable_ssd_standalone.py --verify
```

`PASS: standalone SSD boot with no SD card; 16 GiB SSD swap active.`가 나와야 단독 부팅 완료입니다. 이 검사는 SSD 루트와 스왑뿐 아니라 **SD 장치가 없는지**, 새 SSD 부팅 메뉴를 사용했는지도 확인합니다. SD가 꽂혀 있으면 단독 부팅 성공으로 표시하지 않습니다.

다시 로고에서 멈추면 전원을 끈 뒤 SD를 다시 넣고 기존 SD 부팅 설정으로 복구합니다. 이때 `/`는 다시 SSD로 연결될 수 있으며 정상입니다. 실패 단계는 UART 부트 로그로 확인해야 합니다. U-Boot가 USB 디스크를 찾지 못하는 경우와 QSPI 펌웨어 문제는 처리 방법이 다르므로, 확인 없이 펌웨어를 다시 기록하지 않습니다.

새 설정 파일의 구조와 마운트 동작 검사 11개를 통과했습니다. 실제 생성된 initrd를 다시 풀어 스크립트·USB 펌웨어·필수 실행 파일 포함 여부도 확인했습니다. 검증 로그는 `artifacts/ssd-standalone-tests.log`입니다.

## 대상과 파티션

2026년 10월 14일 확인한 대상은 Samsung SSD 840 EVO 120G, USB 일련번호 `235678C218CA`입니다. `/dev/sda`라는 순서 대신 `/dev/disk/by-id/usb-Samsung_SSD_840_EVO_120G_235678C218CA-0:0`으로 식별하고 용량도 재확인합니다.

| 항목 | 구성 |
|---|---|
| 기존 운영체제 | SD `/dev/mmcblk0p1`, 약 30 GiB |
| SSD 전체 | 120,034,123,776바이트, 약 111.8 GiB |
| SSD 파티션 1 | GPT 이름 `APP`, ext4, 약 95.788 GiB, 운영체제·프로젝트 |
| SSD 파티션 2 | GPT 이름 `SWAP16`, Linux swap, 정확히 16 GiB |
| 기존 zram | 약 1.9 GiB 유지, SSD 스왑보다 높은 우선순위 |

스왑 파티션은 17,179,869,184바이트입니다. 스왑 헤더 때문에 사용 가능 수치는 한 페이지 정도 작습니다. `free -h`의 전체 스왑은 zram을 더해 약 18 GiB로 표시됩니다. 스왑을 추가해도 물리 RAM 4GB가 늘어나는 것은 아닙니다.

기존 SSD의 `/media/moble/840EVO`에는 읽을 수 있는 사용자 파일이 보이지 않았고 `lost+found`가 있었습니다. 디스크 전체의 오래된 swap 서명도 감지됐습니다. **실행 시 이 SSD의 기존 파티션과 내용은 모두 지워집니다. 보관할 파일이 있다면 먼저 다른 디스크에 복사하세요.** SD카드의 부팅 설정은 유지합니다.

## 사전 검사와 실행

읽기 전용 검사:

```bash
cd '/home/moble/2.5th project'
python3 scripts/migrate_ssd.py
```

SSD 초기화와 이전을 실행하려면 브라우저, 편집 중인 파일, 프로젝트 프로그램, 패키지 업데이트를 종료하고 Jetson의 별도 터미널에서 다음을 실행합니다. 시스템 전체를 실행 중에 두 차례 복사하므로 실행 중인 데이터베이스 등의 일관된 스냅샷을 보장하지 않습니다. Jetson 전원과 SSD 연결을 유지하고 완료 문구까지 기다립니다.

```bash
cd '/home/moble/2.5th project'
sudo python3 scripts/migrate_ssd.py --apply --erase-serial 235678C218CA
```

비밀번호는 Jetson의 `sudo` 입력창에서만 입력합니다. `--erase-serial`은 위 SSD의 데이터 삭제를 명시적으로 선택하는 옵션입니다. 옵션 없는 실행은 읽기 전용이며, 다른 일련번호나 용량, 이미 SSD에서 부팅한 상태, 마운트 해제 실패 등에서는 중단합니다. 자동 재부팅은 하지 않습니다.

스크립트는 SSD 앞·뒤 각 1 MiB의 원시 메타데이터와 설정을 SD의 `/var/tmp/moble-ssd-backup-*`에 저장합니다. 손상된 GPT도 백업할 수 있도록 기존 파티션 정보를 해석하는 과정에 의존하지 않습니다. 이 두 영역을 초기화한 뒤 새 GPT를 만들고 파티션 크기·종류·이름을 다시 읽어 검증합니다. **메타데이터 백업은 데이터 백업이 아니므로 포맷된 파일을 복구해 주지 않습니다.** 사용자·권한·하드링크·ACL·확장 속성을 보존해 복사하고, 부팅 바이너리와 프로젝트 코드·모델의 SHA256을 대조합니다. SSD에 새 PARTUUID를 사용하는 부팅 설정과 UUID를 사용하는 `/etc/fstab`을 기록합니다. 기존 스왑 파일 등록이 있으면 SSD 복사본에서 비활성화하고 SSD 스왑을 등록합니다.

복사가 실패하면 원인을 해결하기 전 재부팅하지 마세요. SD에서 현재 시스템을 계속 사용할 수 있습니다. 스크립트를 다시 `--apply`로 실행하면 SSD를 다시 초기화하고 처음부터 복사합니다.

### GPT 오류 후 재실행

첫 실행에서 `sgdisk --zap-all /dev/sda`가 `Invalid partition data`와 종료 코드 2를 반환했습니다. 이 보드의 `sgdisk 1.0.3`에서 GPT와 디스크 전체 swap 정보가 충돌하는 임시 이미지로 동일한 종료 코드를 재현했습니다. 수정본은 기존 GPT를 읽어 지우는 순서 대신, 대상 확인과 원시 메타데이터 백업 후 앞·뒤 예약 영역을 초기화하고 새 GPT를 생성합니다. 첫 실행의 백업 폴더는 삭제하지 않습니다.

수정본에서 위의 동일한 `sudo python3 ... --apply --erase-serial ...` 명령을 다시 실행합니다. SSD 전체 초기화라는 작업 범위는 동일하며 SD 부팅 설정은 유지합니다. 실제 복사 완료 문구가 나오기 전에는 SSD로 부팅을 시도하지 않습니다.

## SSD 부팅과 확인

이 보드에서는 SD를 제거한 SSD 단독 부팅이 실패했습니다. 단독 부팅 실패의 정확한 단계는 직렬 부트 로그 없이 확정하지 않았습니다. SD와 SSD의 `Image`와 `initrd` SHA256은 일치하며, SSD의 UUID·fstab·커널 모듈·복사 완료 기록도 확인했습니다. **포맷과 운영체제 복사는 다시 실행하지 않습니다.**

### SD 부팅 파일을 사용해 SSD 운영체제 실행

SD에는 부팅 파일을 두고 `/` 운영체제와 사용자 파일은 SSD에서 실행합니다. **이 구성에서는 SD와 SSD를 둘 다 계속 연결합니다.** SD의 커널이 USB 장치를 초기화하므로, 부트로더가 SSD에서 커널을 직접 읽는 단계에 의존하지 않습니다.

`scripts/enable_ssd_root.py`는 기본 실행 시 `/boot`를 바꾸지 않고 `artifacts/ssd-boot/`에 검토 가능한 설정과 `initrd`를 준비합니다. 준비 작업은 이미 완료했습니다. SSD `APP` 볼륨이 파일 관리자에서 열려 있는 상태에서 다음을 실행합니다.

```bash
cd '/home/moble/2.5th project'
sudo python3 scripts/enable_ssd_root.py --apply
```

`INSTALLED`가 표시되면 SD와 SSD를 모두 연결한 채 `sudo reboot`로 재부팅합니다. 이 명령은 파티션·파일시스템·펌웨어를 변경하거나 운영체제를 다시 복사하지 않습니다.

원래 SD 부팅 설정은 `/boot/extlinux/extlinux.conf.before-ssd-root`에 보존합니다. 원래 커널과 `/boot/initrd`, `primary` 부팅 메뉴도 유지합니다. 새 `moble_ssd` 메뉴는 `/boot/initrd.moble-ssd`를 사용하고, SSD를 약 30초 동안 찾지 못하거나 마운트하지 못하면 원래 SD 파티션으로 되돌아가도록 구성했습니다. 이 복귀 경로는 명령 모의 실행으로 검증했으며, 실제 부팅 하드웨어 검증은 별도입니다. SSD 마운트 이후 운영체제 자체에서 발생한 문제까지 자동 복구하는 기능은 아닙니다.

재부팅 후 다음을 실행합니다.

```bash
cd '/home/moble/2.5th project'
python3 scripts/migrate_ssd.py --verify
python3 monitor.py --diagnose
python3 scripts/gpu_check.py
```

첫 명령은 `/`가 SSD의 UUID와 일치하고 16 GiB SSD 스왑 파티션이 활성화됐는지 확인합니다. 2026년 10월 14일 실제 재부팅 후 `PASS: SSD root filesystem and 16 GiB SSD swap are active.`를 확인했습니다. 결과는 `artifacts/ssd-active-verification.log`에 있습니다. 이 검사는 SD 없는 단독 부팅을 증명하지 않습니다. `findmnt /`가 `/dev/mmcblk0p1`이면 SD로 복귀했거나 SD 메뉴에서 부팅한 상태입니다.

### 원래 SD 부팅으로 복구

새 설정에서 SSD 마운트가 안 되면 SD로 복귀하도록 구성돼 있습니다. 필요하면 전원을 끄고 SSD만 분리한 채 SD로 부팅해 다음을 실행합니다.

```bash
cd '/home/moble/2.5th project'
sudo python3 scripts/enable_ssd_root.py --restore
```

운영 중인 SSD를 분리하지 않습니다. SD의 커널을 읽고 SSD의 커널 모듈을 사용하므로, 추후 커널 업데이트 시 SD `/boot`와 SSD의 커널·모듈 버전을 함께 맞춰야 합니다. 현재 두 복사본의 버전과 부팅 파일은 일치합니다.

## 근거

- [NVIDIA L4T 외장 USB 부팅 안내](https://docs.nvidia.com/jetson/l4t/Tegra%20Linux%20Driver%20Package%20Development%20Guide/flashing.html): Nano의 USB 부팅 지원과 GPT/ext4 APP 파티션 구성.
- [JetsonHacks bootFromUSB 원본 저장소](https://github.com/jetsonhacks/bootFromUSB): Nano에서 기존 rootfs 복사, SSD의 extlinux 설정과 PARTUUID 사용, 전원 종료 후 SD 제거 절차.
- [NVIDIA Nano 부트 펌웨어 버전 조회](https://docs.nvidia.com/jetson/l4t/Tegra%20Linux%20Driver%20Package%20Development%20Guide/bootloader_update_nano_tx1.html): `l4t_payload_updater_t210 -v` 조회 명령.
- [NVIDIA 포럼의 Nano USB 부팅 진단](https://forums.developer.nvidia.com/t/nano-4gb-kit-boot-issues-from-ssd/174149): USB 주변기기와 부팅 순서 문제를 UART/U-Boot 콘솔로 확인하는 사례. 이 보드의 실패 원인으로 확정한 것은 아닙니다.

이 스크립트는 확인한 Nano와 SSD에 맞춰 작성했습니다. 파티션 계산·설정 변환·실행 전 보호 조건·손상 GPT 복구 검사 16개를 통과했고, 실제 `sgdisk`와 `sfdisk`를 사용한 임시 일반 파일의 GPT 구성도 확인했습니다. 결과는 `artifacts/ssd-migration-tests.log`에 있습니다. 실제 SSD 복사 완료 기록에는 72개 파일의 SHA256 대조가 기록돼 있습니다.

SD를 사용하는 SSD 부팅 설정은 별도 검사 10개를 통과했습니다. 원래 메뉴 유지, USB 지연 후 SSD 선택, SSD 마운트 실패 시 SD 복귀, 두 장치 모두 마운트 실패 시 부팅 중단을 명령 모의 실행으로 검사했습니다. 생성한 실제 initrd 압축 파일을 다시 풀어 실행 스크립트와 USB 펌웨어 포함 여부도 확인했습니다. 결과는 `artifacts/ssd-boot-tests.log`에 있습니다. 현재 SD를 사용하는 SSD 운영체제 부팅은 실제로 확인됐으며, SD 없는 단독 부팅은 추가 시험이 필요합니다.
