#!/usr/bin/env python3
"""Run the real CUDA/TensorRT engine on an official YOLO sample image."""
import json
from pathlib import Path
import statistics
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
from app.config import load
from app.inference import PersonDetector


def main():
    path = ROOT / 'artifacts/test_bus.jpg'
    url = 'https://raw.githubusercontent.com/ultralytics/yolov5/v6.0/data/images/bus.jpg'
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            path.write_bytes(response.read())
    frame = cv2.imread(str(path))
    if frame is None:
        raise ValueError('Unable to decode test image')
    detector = PersonDetector(load()['vision'])
    try:
        detector.inspect(frame)  # Warm up before the measured calls.
        results = [detector.inspect(frame) for _ in range(5)]
        result = results[-1]
        if result['count'] < 1:
            raise AssertionError('No person detected in the official test image')
        blank = detector.inspect(np.zeros((360, 640, 3), dtype=np.uint8))
        if blank['count'] != 0:
            raise AssertionError('Unexpected person on blank test frame')
        for box in result['boxes']:
            a, b, c, d = box['box']
            cv2.rectangle(frame, (a, b), (c, d), (30, 210, 90), 3)
        cv2.imwrite(str(ROOT / 'artifacts/gpu-detections.jpg'), frame)
        report = {'passed': True, 'backend': result['backend'], 'input_size': 320,
                  'test_image_source': url, 'persons_detected': result['count'],
                  'blank_persons_detected': blank['count'], 'samples': 5,
                  'median_pipeline_ms': statistics.median(r['inference_ms'] for r in results),
                  'scope': 'Static image GPU inference including CPU pre/postprocessing; not live-camera FPS'}
        (ROOT / 'artifacts/gpu-check.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        detector.close()


if __name__ == '__main__':
    main()
