#!/usr/bin/env python3
"""Start the Nano monitor, diagnostics, simulation, or PIN setup."""
import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.vendor'))


def main():
    from app.access import make_pin_hash
    from app.config import load, save_pin_hash
    parser = argparse.ArgumentParser(description='Jetson equipment safety and access monitor')
    parser.add_argument('--simulate', action='store_true', help='Synthetic sensors/camera, no devices opened')
    parser.add_argument('--camera-only', action='store_true', help='카메라·얼굴 등록만 실행; 아두이노 출력 연결 없음')
    parser.add_argument('--start-stopped', action='store_true', help='긴급 정지 상태로 시작; 관리자 자동 제어로 복귀')
    parser.add_argument('--headless', action='store_true', help='Run in SSH without a desktop')
    parser.add_argument('--config', help='JSON settings overlay')
    parser.add_argument('--seconds', type=float, default=0, help='Stop after N seconds; 0 means run continuously')
    parser.add_argument('--scenario', default='normal')
    parser.add_argument('--set-pin', action='store_true')
    parser.add_argument('--diagnose', action='store_true')
    args = parser.parse_args()
    if args.set_pin:
        pin = getpass.getpass('New administrator PIN (6+ digits): ')
        if pin != getpass.getpass('Repeat PIN: '):
            raise ValueError('PIN mismatch')
        save_pin_hash(make_pin_hash(pin))
        print('PIN saved; no default PIN is supplied.')
        return 0
    cfg = load(args.config)
    if args.seconds < 0:
        raise ValueError('--seconds must be nonnegative')
    if args.diagnose:
        from scripts.diagnose import diagnose
        return diagnose(cfg)
    from app.runtime import Runtime, SCENARIOS, setup_logging
    if args.scenario not in SCENARIOS:
        raise ValueError('Unknown scenario: ' + args.scenario)
    lock = (ROOT / ('.simulation.lock' if args.simulate else '.live.lock')).open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('Another monitor instance is already running.', file=sys.stderr)
        return 3
    directory = setup_logging(cfg)
    runtime = Runtime(cfg, args.simulate, args.scenario, directory, camera_only=args.camera_only)
    try:
        if args.start_stopped:
            runtime.action('stop')
        if args.headless:
            stopping = [False]
            signal.signal(signal.SIGTERM, lambda *_: stopping.__setitem__(0, True))
            started, last_report = time.monotonic(), 0
            while not stopping[0] and (not args.seconds or time.monotonic() - started < args.seconds):
                snap = runtime.tick()
                if time.monotonic() - last_report >= 1:
                    print(json.dumps({k: snap[k] for k in ['simulation', 'decision', 'vision', 'port']}, default=list), flush=True)
                    last_report = time.monotonic()
                time.sleep(0.1)
        else:
            from app.ui import Dashboard
            dashboard = Dashboard(runtime)
            signal.signal(signal.SIGTERM, lambda *_: dashboard.close())
            dashboard.run(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        lock.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, FileNotFoundError, ImportError) as exc:
        print('Setup/configuration error: ' + str(exc), file=sys.stderr)
        sys.exit(2)
