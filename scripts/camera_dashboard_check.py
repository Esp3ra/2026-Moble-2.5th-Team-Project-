#!/usr/bin/env python3
"""Measure the real Tk preview with live camera/GPU, never opening Arduino."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / '.vendor'))


class NoSerial:
    def __init__(self, *_): pass
    def start(self): pass
    def submit(self, *_): pass
    def close(self): pass
    def snapshot(self, now):
        return dict(telemetry=None, received_at=0, healthy=False, connected=False,
                    error='Camera-only check', port='NOT OPENED', ack=None,
                    bad_packets=0, reconnects=0, safety_override=False)


def main():
    from app.config import load
    from app.runtime import Runtime
    from app.ui import Dashboard
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--width', type=int)
    parser.add_argument('--height', type=int)
    args = parser.parse_args()
    if args.seconds < 10:
        parser.error('Observe at least 10 seconds')
    cfg = load(ROOT / 'config/ventilation.json')
    for key in ('width', 'height'):
        value = getattr(args, key)
        if value is not None:
            cfg['camera'][key] = value
    with patch('app.runtime.SerialLink', NoSerial):
        runtime = Runtime(cfg)
    dashboard = Dashboard(runtime)
    dashboard.root.title('Moble 실제 카메라 화면 FPS 점검 — Arduino 연결 안 함')
    dashboard.badge.configure(text='CAMERA CHECK / NO OUTPUTS')
    render = dashboard.render
    frames, detections, inference_ms, ages = [], [], [], []
    last_frame = last_detection = None
    first = None
    first_called = time.monotonic()
    errors = []

    def observed_render(snap):
        nonlocal first, last_frame, last_detection
        render(snap)
        now = time.monotonic()
        if first is None and snap['camera_at'] is not None and not snap['camera_error']:
            first = now
        if first is not None:
            if snap['frame_at'] is not None and snap['frame_at'] != last_frame:
                frames.append(now)
                last_frame = snap['frame_at']
            if snap['camera_at'] is not None and snap['camera_at'] != last_detection:
                detections.append(now)
                inference_ms.append(snap['vision']['inference_ms'])
                ages.append(now - snap['camera_at'])
                last_detection = snap['camera_at']
            if snap['camera_error']:
                errors.append(snap['camera_error'])

    dashboard.render = observed_render

    def finish_when_ready():
        elapsed = time.monotonic() - (first if first is not None else first_called)
        if (first is not None and elapsed >= args.seconds) or (first is None and elapsed > 40):
            dashboard.close()
        elif not dashboard.closed:
            dashboard.root.after(100, finish_when_ready)

    dashboard.root.after(100, finish_when_ready)
    try:
        dashboard.run()
    finally:
        dashboard.close()
    rate = lambda stamps: (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0
    span = frames[-1] - frames[0] if len(frames) > 1 else 0
    bins = [sum(frames[0] + i * 5 <= t < frames[0] + (i + 1) * 5 for t in frames) / 5
            for i in range(int(span // 5))]
    gaps = sorted((b - a) * 1000 for a, b in zip(frames, frames[1:]))
    report = dict(scope='Actual displayed Tk images, live camera and TensorRT; Arduino never opened',
                  displayed_frames=len(frames), observation_seconds=round(span, 2),
                  display_fps=round(rate(frames), 2), five_second_window_fps=bins,
                  gap_p95_ms=round(gaps[int((len(gaps)-1) * 0.95)], 2) if gaps else None,
                  inference_fps=round(rate(detections), 2),
                  median_inference_ms=round(statistics.median(inference_ms), 2) if inference_ms else None,
                  max_detection_age_seconds=round(max(ages), 3) if ages else None,
                  worker_generations=runtime.camera.generation, errors=errors,
                  serial_opened=False, requested_camera=cfg['camera'])
    report['passed'] = (span >= args.seconds - 1 and report['display_fps'] >= 28.5
                        and bool(bins) and min(bins) >= 28 and not errors
                        and runtime.camera.generation == 1)
    (ROOT / 'artifacts/camera-dashboard-live-check.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
