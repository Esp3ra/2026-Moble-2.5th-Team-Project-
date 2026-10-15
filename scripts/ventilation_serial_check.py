#!/usr/bin/env python3
"""Bounded REAL actuator command test. Does not inject gas or change thresholds."""
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
    parser.add_argument('--run-actuators', action='store_true', required=True,
                        help='Enable the explicitly requested bounded physical output test')
    parser.add_argument('--focus-combined', action='store_true', help='Longer LOW/HIGH and combined LED observation')
    parser.add_argument('--focus-temperature-stop', action='store_true', help='Bounded normal/automatic-stop/resume output comparison')
    parser.add_argument('--report', default='artifacts/ventilation-serial-result.json')
    args = parser.parse_args()
    stages = [('ARM', 4, 'NORMAL', False, False),
              ('NORMAL_LOW', 4, 'NORMAL', True, False),
              ('INTRUSION_LOW', 4, 'DANGER', True, True),
              ('ENV_HIGH', 4, 'WARNING', True, False),
              ('COMBINED_HIGH', 8, 'WARNING', True, True),
              ('MUTE_COMBINED', 3, 'WARNING', True, True),
              ('STOP_COMBINED', 3, 'WARNING', False, True),
              ('MANUAL_OPEN', 3, 'NORMAL', True, False),
              ('MANUAL_CLOSED', 3, 'WARNING', True, False),
              ('AUTO_RESTORE', 3, 'NORMAL', True, False),
              ('FAULT_OFF', 3, 'FAULT', False, True)]
    if args.focus_combined:
        stages = [('ARM', 4, 'NORMAL', False, False),
                  ('NORMAL_LOW', 10, 'NORMAL', True, False),
                  ('ENV_HIGH', 10, 'WARNING', True, False),
                  ('COMBINED_HIGH', 20, 'WARNING', True, True),
                  ('STOP_COMBINED', 3, 'WARNING', False, True),
                  ('FAULT_OFF', 3, 'FAULT', False, True)]
    if args.focus_temperature_stop:
        stages = [('ARM',3,'NORMAL',False,False), ('NORMAL_LOW',3,'NORMAL',True,False),
                  ('TEMP_STOP',5,'WARNING',False,False), ('TEMP_STOP_LOCKED',3,'WARNING',False,True),
                  ('AUTO_RESTORE',3,'NORMAL',True,False), ('STOP_COMBINED',3,'WARNING',False,True)]
    seq, session = 0, int.from_bytes(os.urandom(4), 'big') or 1
    records, checks, pending = [], {}, {}
    framer = Framer()
    last_telemetry = None
    with serial.Serial('/dev/ttyUSB0', 115200, timeout=0.1, write_timeout=0.5, exclusive=True) as port:
        def receive():
            return framer.feed(port.read(min(port.in_waiting or 1, 4096)))
        try:
            # Opening the port resets Mega. Wait for actual valid sensor data.
            until = time.monotonic() + 12
            while time.monotonic() < until:
                for packet in receive():
                    records.append(packet)
                    if packet.get('type') == 'telemetry': last_telemetry = packet
                if last_telemetry and last_telemetry.get('sensor_ok') and last_telemetry.get('hardware_ready'):
                    break
            assert last_telemetry and last_telemetry['profile'] == 'ventilation', 'Ventilation firmware required'
            assert last_telemetry.get('policy_rev') == 6, 'Revision 6 firmware required'
            assert last_telemetry['sensor_ok'] and last_telemetry['hardware_ready'], 'Hardware not ready'
            assert not last_telemetry['environment_alert'], 'Resolve real environmental alert before staged output test'
            for label, seconds, state, run, access in stages:
                print('STAGE ' + label, flush=True)
                checks[label] = 0
                until = time.monotonic() + seconds
                while time.monotonic() < until:
                    for packet in receive():
                        records.append(packet)
                        if packet.get('type') == 'telemetry':
                            last_telemetry = packet
                            assert packet['sensor_ok'] and packet['hardware_ready'], 'Sensor/hardware failure'
                            assert not packet['environment_alert'], 'Unexpected actual environment alert'
                            seq += 1
                            mode = 'OPEN' if label in ('MANUAL_OPEN','TEMP_STOP') else 'CLOSED' if label == 'MANUAL_CLOSED' else 'AUTO'
                            stopped = label == 'STOP_COMBINED'
                            thermal_stop = label in ('TEMP_STOP','TEMP_STOP_LOCKED')
                            vent = 'CLOSED' if stopped or thermal_stop else mode if mode != 'AUTO' else 'OPEN' if state == 'WARNING' else 'SAFE' if state == 'FAULT' else 'CLOSED'
                            msg = command(seq, state, vent,
                                          state in ('WARNING', 'FAULT'), run, session,
                                          fan='OFF' if not run else 'HIGH' if state == 'WARNING' else 'LOW',
                                          settings_locked=access, access_alert=access, vent_mode=mode,
                                          emergency_stop=stopped, alarm_acknowledged=label == 'MUTE_COMBINED',
                                          temperature_stop=thermal_stop)
                            pending[seq] = (label, msg)
                            port.write(encode(msg))
                        elif packet.get('type') == 'ack':
                            previous = pending.pop(packet['seq'], None)
                            assert previous and ack_matches(packet, previous[1]), 'Rejected/mismatched ACK'
                            assert all(packet.get(k) == previous[1][k] for k in ('state', 'vent', 'fan', 'device_enable', 'access_alert', 'settings_locked', 'vent_mode', 'emergency_stop', 'alarm_acknowledged','temperature_stop')), 'Wrong output'
                            checks[previous[0]] += 1
                assert checks[label] >= 3, 'Too few acknowledgements in ' + label
            # Stop transmitting. Mega must independently remain OFF on timeout.
            until = time.monotonic() + 4.5
            while time.monotonic() < until:
                for packet in receive():
                    records.append(packet)
                    if packet.get('type') == 'telemetry': last_telemetry = packet
            assert last_telemetry['fault'] == 'COMM_ERROR'
            assert last_telemetry['fan'] == 'OFF' and not last_telemetry['device_enable']
            assert framer.errors == 0, 'Malformed serial line'
        finally:
            # Prefer a telemetry reply slot; hardware timeout also stops D10.
            until = time.monotonic() + 1
            stopped = False
            while not stopped and time.monotonic() < until:
                for packet in receive():
                    if packet.get('type') == 'telemetry':
                        port.write(encode(command(seq + 1, 'FAULT', 'CLOSED', False, False, session,
                                                  fan='OFF', settings_locked=True, emergency_stop=True)))
                        port.flush()
                        stopped = True
                        break
            report_path = ROOT / args.report
            report_path.with_name(report_path.stem + '-packets.json').write_text(json.dumps(records, indent=2) + '\n')
    report = dict(passed=True, stage_ack_counts=checks, framing_errors=framer.errors,
                  last_telemetry=last_telemetry,
                  test_kind='Physical outputs driven by staged commands; no real heat/gas exposure',
                  physical_color_speed_observation='Pending user observation')
    (ROOT / args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
