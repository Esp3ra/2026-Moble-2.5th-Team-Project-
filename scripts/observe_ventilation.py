#!/usr/bin/env python3
"""Read-only observation of the running ventilation app's status file."""
import datetime
import argparse
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--report', default='artifacts/ventilation-live-result.json')
    args = parser.parse_args()
    if args.seconds < 10:
        parser.error('Observe at least 10 seconds')
    path = ROOT / 'logs/status.json'
    began, wall_started = time.monotonic(), time.time()
    observed, first, seen = [], None, None
    while time.monotonic() - began < args.seconds + 50:
        try:
            snap = json.loads(path.read_text())
            modified = path.stat().st_mtime
        except (OSError, ValueError):
            time.sleep(0.5)
            continue
        if snap.get('profile') != 'ventilation' or modified < wall_started or time.time() - modified > 4:
            time.sleep(0.5)
            continue
        if first is None and snap['healthy'] and snap['decision']['state'] != 'FAULT':
            first = time.monotonic()
        if first is not None and snap['timestamp'] != seen:
            observed.append(snap)
            seen = snap['timestamp']
        if first is not None and time.monotonic() - first >= args.seconds:
            break
        time.sleep(0.5)
    invalid = [s for s in observed if not s['healthy'] or s['camera_age_seconds'] is None
               or s['camera_age_seconds'] > 3 or s['decision']['state'] == 'FAULT']
    report = {'timestamp': datetime.datetime.now().isoformat(),
              'duration_seconds': round(time.monotonic() - first, 1) if first is not None else 0,
              'samples': len(observed), 'unhealthy_samples': len(invalid),
              'new_rejected_packets': observed[-1]['bad_packets'] - observed[0]['bad_packets'] if observed else None,
              'new_reconnects': observed[-1]['reconnects'] - observed[0]['reconnects'] if observed else None,
              'states': sorted(set(s['decision']['state'] for s in observed)),
              'vision_states': sorted(set(s['vision']['state'] for s in observed)),
              'fan_commands': sorted(set(s['decision']['fan'] for s in observed)),
              'ack_fan_states': sorted(set((s['ack'] or {}).get('fan', 'NONE') for s in observed)),
              'camera_inference_ms_mean': round(sum(s['vision']['inference_ms'] for s in observed) / len(observed), 2) if observed else None,
              'last_sample': observed[-1] if observed else None, 'bad_sample_examples': invalid[:3]}
    # At most ~1 sample/sec; missing status updates also fail this check.
    report['passed'] = (report['duration_seconds'] >= args.seconds and len(observed) >= args.seconds * 0.75 and not invalid
                        and report['new_rejected_packets'] == 0 and report['new_reconnects'] == 0)
    (ROOT / args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('last_sample', 'bad_sample_examples')}, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
