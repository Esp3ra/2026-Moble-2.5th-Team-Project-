# 외부 코드와 모델

- YOLOv5n v6.0 ONNX: Ultralytics YOLOv5 공식 배포. 배포 모델과 GPL 3.0 라이선스는 `models/YOLO_LICENSE`, 원본 URL과 SHA256은 `models/yolo-sources.json`에 포함합니다. 예제 검증 사진도 같은 저장소의 `data/images/bus.jpg`에서 받습니다.
- pySerial 3.5: 프로젝트 내부 `.vendor`에 설치하며 패키지의 BSD 라이선스와 배포 메타데이터를 함께 보존합니다.
- ArduinoJson 6.21.5, Adafruit DHT 1.4.6, Adafruit Unified Sensor 1.1.15, Servo 1.2.2, LiquidCrystal I2C 1.1.2: Arduino 공식 라이브러리 인덱스의 배포를 사용합니다. 로컬 설치 위치는 `.tools/arduino-user/libraries`이며 각 패키지의 라이선스 파일이 포함되어 있습니다. 소스 배포 ZIP에는 이 도구 캐시 대신 버전 고정 설치 스크립트를 제공합니다.
- OpenCV, NumPy, Tkinter, CUDA, TensorRT: Jetson 시스템의 기존 설치를 사용합니다.
- OpenCV Zoo YuNet 2023mar 얼굴 검출 모델: MIT, `models/YUNET_LICENSE`.
- OpenCV Zoo SFace 2021dec 얼굴 특징 모델: Apache 2.0, `models/SFACE_LICENSE`. 두 모델의 공식 배포 URL과 고정 SHA256은 `models/face-sources.json`에 기록합니다. 전처리와 5점 정렬은 OpenCV의 `modules/objdetect/src/face_detect.cpp`, `face_recognize.cpp` 규약을 따릅니다. 이 Jetson용 FP16 엔진은 `scripts/build_face_engines.py`로 생성합니다.

제3자 모델 및 라이브러리의 재배포에는 해당 라이선스가 적용됩니다.
