#!/usr/bin/env python3
"""Play a bounded 3-second reduced-duty warning with D10 OFF and D9 CLOSED."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / '.vendor'))
import serial
from app.protocol import Framer, ack_matches, command, encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--play', action='store_true', required=True)
    parser.parse_args()
    framer, pending, records = Framer(), {}, []
    session, sequence = int.from_bytes(os.urandom(4), 'big') or 1, 0
    last, checks, completed = None, {}, False
    with serial.Serial('/dev/ttyUSB0', 115200, timeout=.1, write_timeout=.5, exclusive=True) as port:
        def receive():
            return framer.feed(port.read(min(port.in_waiting or 1, 4096)))

        def send(stopped):
            nonlocal sequence
            sequence += 1
            msg = command(sequence, 'WARNING', 'CLOSED', not stopped, False, session,
                          fan='OFF', settings_locked=False, access_alert=False,
                          vent_mode='CLOSED', emergency_stop=stopped)
            pending[sequence] = msg
            port.write(encode(msg))
            return sequence

        try:
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                for packet in receive():
                    if packet.get('type') == 'telemetry':
                        last = packet
                        if last.get('sensor_ok') and last.get('hardware_ready'):
                            break
                if last and last.get('sensor_ok') and last.get('hardware_ready'):
                    break
            assert last and last.get('policy_rev') == 6 and last.get('buzzer_duty_percent') == 5, 'Updated quiet firmware required'
            assert last.get('sensor_ok') and last.get('hardware_ready'), 'Hardware not ready'
            assert not last.get('environment_alert'), 'Resolve environmental alert first'
            for label, duration, stopped in [('ARM_STOP', 2, True), ('QUIET_WARNING', 3, False), ('STOP', 2, True)]:
                print('STAGE ' + label, flush=True)
                checks[label] = 0
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    for packet in receive():
                        records.append(packet)
                        if packet.get('type') == 'telemetry':
                            last = packet
                            assert packet.get('sensor_ok') and packet.get('hardware_ready')
                            assert not packet.get('environment_alert')
                            send(stopped)
                        elif packet.get('type') == 'ack':
                            expected = pending.pop(packet.get('seq'), None)
                            assert expected and ack_matches(packet, expected), 'ACK mismatch'
                            assert packet['fan'] == 'OFF' and packet['vent'] == 'CLOSED'
                            if packet['emergency_stop'] == stopped:
                                checks[label] += 1
                assert checks[label] >= 2, 'Missing ACK in ' + label
            assert framer.errors == 0
            completed = True
        finally:
            deadline = time.monotonic() + 1.5
            stop_seq = None
            while time.monotonic() < deadline:
                packets = receive()
                if stop_seq is None and any(p.get('type') == 'telemetry' for p in packets):
                    stop_seq = send(True)
                if stop_seq and any(p.get('type') == 'ack' and p.get('seq') == stop_seq and p.get('emergency_stop') is True for p in packets):
                    break
            report = dict(passed=completed, stage_ack_counts=checks, framing_errors=framer.errors,
                          duty_percent=(last or {}).get('buzzer_duty_percent'),
                          test_kind='3-second physical warning; D10 OFF and D9 CLOSED throughout',
                          perceived_volume_user_verified=False, last_telemetry=last)
            (ROOT / 'artifacts/quiet-buzzer-serial.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'last_telemetry'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
