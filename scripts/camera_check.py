#!/usr/bin/env python3
"""Check the production camera/GPU worker without opening Arduino outputs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.vendor'))

import cv2
from app.config import load
from app.devices import Camera


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Show on DISPLAY; Q/Esc closes')
    parser.add_argument('--seconds', type=float, default=20, help='Observation time after first frame; 0 runs until closed')
    parser.add_argument('--save-frame', action='store_true', help='Save the final preview image locally')
    parser.add_argument('--width', type=int, help='Request capture width for comparison')
    parser.add_argument('--height', type=int, help='Request capture height for comparison')
    parser.add_argument('--fps', type=int, help='Request capture FPS for comparison')
    parser.add_argument('--capture-fps', type=int, help='Camera transport request, independent of display FPS')
    parser.add_argument('--fourcc', choices=('MJPG', 'YUYV'))
    parser.add_argument('--report', default='artifacts/camera-live-check.json', help='JSON report path')
    parser.add_argument('--config', help='Settings profile, including optional face recognition')
    args = parser.parse_args()
    if not 0 <= args.seconds <= 3600:
        parser.error('--seconds must be between 0 and 3600')
    if args.preview and not os.environ.get('DISPLAY'):
        parser.error('--preview requires DISPLAY, e.g. DISPLAY=:0')
    cfg = load(args.config)
    from app.config import validate
    for key in ('width', 'height', 'fps'):
        value = getattr(args, key)
        if value is not None:
            cfg['camera'][key] = value
    if args.fps is not None:
        cfg['camera']['capture_fps'] = args.fps
    if args.capture_fps is not None:
        cfg['camera']['capture_fps'] = args.capture_fps
    if args.fourcc is not None:
        cfg['camera']['fourcc'] = args.fourcc
    validate(cfg)
    camera = Camera(cfg['camera'], cfg['vision'])
    stamps, times, counts = [], [], []
    face_counts, enrollable = [], 0
    preview_stamps = []
    previous_preview = None
    observed_frame = None
    started = time.monotonic()
    shape = None
    preview = None
    last_frame_stddev = None
    last_brightness = None
    failure = ''
    window = 'Moble Camera + TensorRT GPU Check - Q / Esc to close'
    try:
        if args.preview:
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window, 800, 600)
        while True:
            now = time.monotonic()
            frame, received, fresh = camera.poll(now)
            if fresh:
                result = camera.result
                stamps.append(now)
                times.append(result['inference_ms'])
                counts.append(result['count'])
                face_counts.append(len(result.get('faces', [])))
                enrollable += result.get('_enrollment') is not None
                shape = list(frame.shape)
                observed_frame = frame
                if len(stamps) == 1 or len(stamps) % 50 == 0:
                    print(json.dumps({'detections': len(stamps), 'preview_frames': len(preview_stamps),
                                      'shape': shape, 'people': result['count'], 'faces': len(result.get('faces', [])),
                                      'enrollable': result.get('_enrollment') is not None, 'backend': result['backend']}), flush=True)
            if frame is not None and camera.frame_at != previous_preview:
                previous_preview = camera.frame_at
                if stamps:
                    preview_stamps.append(now)
                if args.preview or args.save_frame:
                    preview = frame.copy()
                result = camera.result or {'count': None, 'boxes': [], 'inference_ms': 0}
                for detection in result['boxes'] if preview is not None else []:
                    x1, y1, x2, y2 = detection['box']
                    cv2.rectangle(preview, (x1, y1), (x2, y2), (30, 220, 90), 2)
                window_stamps = preview_stamps[-30:]
                live_fps = (len(window_stamps) - 1) / (window_stamps[-1] - window_stamps[0]) if len(window_stamps) > 1 else 0
                label = 'People: {} | {:.1f} FPS | GPU {:.0f} ms'.format(
                    result['count'], live_fps, result['inference_ms'])
                if preview is not None:
                    cv2.putText(preview, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                                0.5, (40, 255, 100), 1, cv2.LINE_AA)
            if args.preview:
                # GTK2 does not implement WND_PROP_VISIBLE; AUTOSIZE is supported.
                if cv2.getWindowProperty(window, cv2.WND_PROP_AUTOSIZE) < 0:
                    break
                if preview is not None:
                    cv2.imshow(window, preview)
                key = cv2.waitKey(1) & 0xff
                if key in (27, ord('q')):
                    break
            if args.seconds and stamps and now - stamps[0] >= args.seconds:
                break
            if not stamps and now - started > cfg['camera']['startup_seconds'] + 5:
                failure = camera.error or 'No GPU processed camera frames'
                break
            if stamps and now - stamps[-1] > cfg['camera']['stale_seconds'] + 5:
                failure = camera.error or 'Camera frames stopped'
                break
            time.sleep(0.01)
    finally:
        camera.close()
        if args.preview:
            cv2.destroyAllWindows()
    if observed_frame is not None:
        last_frame_stddev = float(observed_frame.std())
        last_brightness = float(observed_frame.mean())
    report = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'passed': len(stamps) >= 10 and not failure and camera.generation == 1,
        'scope': 'Live camera capture plus TensorRT GPU processing; scene/detection accuracy requires visual review',
        'error': failure, 'frames': len(stamps), 'worker_generations': camera.generation,
        'actual_frame_shape': shape, 'backend': 'TensorRT GPU FP16' if times else None,
        'requested_capture': {key: cfg['camera'][key] for key in ('width', 'height', 'fps', 'capture_fps', 'fourcc')},
        'preview_frames': len(preview_stamps),
        'preview_fps': (len(preview_stamps) - 1) / (preview_stamps[-1] - preview_stamps[0]) if len(preview_stamps) > 1 else 0,
        'processed_fps': (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0,
        'median_inference_ms': statistics.median(times) if times else None,
        'max_people': max(counts) if counts else None,
        'last_people': counts[-1] if counts else None,
        'last_frame_brightness': last_brightness, 'last_frame_stddev': last_frame_stddev,
        'serial_opened': False,
        'face_engines_enabled': cfg['vision']['faces']['enabled'],
        'max_faces': max(face_counts) if face_counts else 0,
        'enrollable_frames': enrollable,
    }
    out = ROOT / 'artifacts'
    out.mkdir(exist_ok=True)
    if args.save_frame and preview is not None:
        if not cv2.imwrite(str(out / 'camera-live-check.jpg'), preview):
            raise RuntimeError('Could not save preview image')
        report['snapshot'] = 'artifacts/camera-live-check.jpg'
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
