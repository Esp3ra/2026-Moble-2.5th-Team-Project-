#!/usr/bin/env python3
"""Check the integration firmware protocol with the rotation output OFF."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / '.vendor'))
import serial
from app.protocol import command, encode


def main():
    records = []
    started = time.monotonic()
    sequence = 0
    with serial.Serial('/dev/ttyUSB0', 115200, timeout=0.3, write_timeout=0.5, exclusive=True) as port:
        while time.monotonic() - started < 15:
            data = port.readline().strip()
            if not data: continue
            packet = json.loads(data.decode('ascii'))
            records.append(packet)
            if packet.get('type') == 'telemetry':
                sequence += 1
                port.write(encode(command(sequence, 'NORMAL', 'CLOSED', False, False, 640014)))
    telemetry = [p for p in records if p.get('type') == 'telemetry']
    ready = [p for p in telemetry if p.get('sensor_ok') and p.get('hardware_ready')]
    acks = [p for p in records if p.get('type') == 'ack']
    errors = [p.get('fault') for p in ready if p.get('fault') not in ('', 'STARTUP', 'COMM_ERROR')]
    passed = (len(ready) >= 15 and len(acks) >= 15 and not errors
              and all(p.get('device_enable') is False for p in records)
              and all(p.get('profile') == 'bench' and p.get('gas_guard') is False
                      and p.get('bench_run_ms') == 10000 for p in telemetry)
              and all(p.get('accepted') is True for p in acks))
    report = {'passed': passed, 'ready_samples': len(ready), 'ack_count': len(acks),
              'device_ever_enabled': any(p.get('device_enable') for p in records),
              'faults_after_ready': errors, 'last_telemetry': telemetry[-1] if telemetry else None}
    (ROOT / 'artifacts/integration-serial-packets.json').write_text(json.dumps(records, indent=2) + '\n')
    (ROOT / 'artifacts/integration-serial-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
