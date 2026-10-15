# GitHub 소스 구성과 재설치

저장소: [Esp3ra/2026-Moble-2.5th-Team-Project-](https://github.com/Esp3ra/2026-Moble-2.5th-Team-Project-)

현재 기본 브랜치는 `main`이며 정책 버전 6까지의 프로젝트 소스를 포함한다. 기존 저장소의 비공개 설정을 유지한다.

| 경로 | 포함 내용 |
|---|---|
| `app/`, `monitor.py`, `run*.sh` | 한글 관리자 화면, GPU 인식, 얼굴 등록·승인, 센서·장치 제어, USB 통신 |
| `firmware/` | Mega 운영 펌웨어와 D9·서보·RGB·부저·센서·전원·I2C 진단 스케치 |
| `scripts/` | 설치, 모델 다운로드·엔진 빌드, 화면·실물 점검, 배포, SSD 이전·부팅 점검 |
| `tests/` | 제어·통신·인식·설정·펌웨어·SSD 자동 테스트 |
| `config/` | 기본 설정, ventilation/bench 설정, 로컬 설정 예시 |
| `docs/` | 현재 운영 방법, 배선도·예시 이미지, 통신, 설치와 변경·점검 기록 |
| `models/` | 모델 출처 URL·고정 SHA256·라이선스 |
| `artifacts/temperature-stop-*` | 검토된 최신 테스트·빌드·업로드 기록, 합성 화면, 출력 응답·연결 점검 결과 |

## 기기별로 보관하는 파일

관리자 PIN 해시를 담은 `config/local.json`, 등록자 이름·얼굴 특징을 담은 `data/`, 운영 로그·실제 카메라 사진·진단 원본, `.backups/`는 업로드하지 않는다. 해당 파일은 기존 Jetson에 그대로 남긴다. GitHub 소스를 새로 받으면 PIN 설정과 얼굴 등록을 별도로 해야 한다.

`.tools/`, `.vendor/`, `build/`, `dist/`, ONNX 모델과 TensorRT 엔진은 설치·다운로드·빌드로 다시 생성한다. 저장소의 출처·SHA256 파일로 모델 무결성을 검사한다. 엔진은 Jetson GPU와 TensorRT 버전에 종속되므로 대상 기기에서 생성한다. 문서에 나오는 과거 `artifacts/` 경로는 당시 로컬 점검 기록이며, GitHub에는 위의 최신 검토 기록만 포함한다.

## Jetson에서 처음 받기

실제 사용 환경은 Jetson Nano, Ubuntu 18.04, Python 3.6, CUDA 10.2, TensorRT 8.2다. 일반 PC에서는 센서·GPU 연결 없이 가능한 코드 테스트와 문서 검토를 진행할 수 있다. 시스템 OpenCV/CUDA/TensorRT를 pip로 교체하지 않는다.

```bash
git clone https://github.com/Esp3ra/2026-Moble-2.5th-Team-Project-.git
cd 2026-Moble-2.5th-Team-Project-
python3 scripts/setup.py --arduino
python3 scripts/download_model.py
python3 scripts/build_face_engines.py
bash scripts/build_engine.sh
python3 -m unittest discover -s tests -v
```

비공개 저장소 접근에는 GitHub 인증이 필요하다. 자격 증명은 저장소 파일이나 채팅에 기록하지 않는다.

실제 카메라 경로는 `config/ventilation.json`에서 대상 기기에 맞게 설정한다. 운영 펌웨어 컴파일은 `bash scripts/compile_ventilation.sh`이며, 업로드·배선 확인은 [운영 안내](VENTILATION.md)와 [배선 안내](WIRING.md)를 따른다. 펌웨어 업로드는 실제 장치 동작에 영향을 주므로 시리얼 포트를 사용하는 운영 프로그램을 먼저 종료한다.

새 기기의 첫 실행은 정지 상태로 시작한다.

```bash
DISPLAY=:0 bash run_ventilation.sh --start-stopped
```

관리자 화면에서 PIN 최초 설정·얼굴 등록을 진행하고, 회로와 센서 상태를 확인한 뒤 자동 제어로 전환한다. 정상 기준은 [현재 정책](VENTILATION.md)을 따른다. 온도 센서 급변의 물리적 원인은 아직 확정하지 않았으며, 소프트웨어의 자동 정지·복귀 검증과 구분한다.

## 이후 변경 업로드

```bash
git status --short
git diff
git add app firmware scripts tests config docs README.md .gitignore .gitattributes
git diff --cached --stat
git commit -m "Describe the change"
git push origin main
```

실제 측정·개인정보 파일을 올리려고 `git add -f`로 제외 규칙을 우회하지 않는다. 제3자 코드와 모델의 이용 조건은 [THIRD_PARTY.md](../THIRD_PARTY.md)에 기록돼 있다.
