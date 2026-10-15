#!/usr/bin/env python3
"""Bounded LED/buzzer load comparison. D9 CLOSED and D10 OFF throughout."""
import argparse
import datetime
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
    parser.add_argument('--run-indicators', required=True, action='store_true')
    args = parser.parse_args()
    framer, pending, records = Framer(), {}, []
    seq, session = 0, int.from_bytes(os.urandom(4), 'big') or 1
    completed = False
    stages = [('STOP_BASELINE', True, True), ('LED_ONLY', False, True),
              ('LED_AND_BUZZER', False, False), ('STOP_RECOVERY', True, True)]
    with serial.Serial('/dev/ttyUSB0', 115200, timeout=.1, write_timeout=.5, exclusive=True) as port:
        def send(stopped, muted):
            nonlocal seq
            seq += 1
            msg = command(seq, 'WARNING', 'CLOSED', not muted and not stopped, False, session,
                          fan='OFF', settings_locked=False, access_alert=False, vent_mode='CLOSED',
                          emergency_stop=stopped, alarm_acknowledged=muted)
            pending[seq] = msg
            port.write(encode(msg))

        def receive():
            return framer.feed(port.read(min(port.in_waiting or 1,4096)))

        try:
            ready = False
            deadline = time.monotonic()+12
            while time.monotonic()<deadline and not ready:
                for packet in receive():
                    if packet.get('type')=='telemetry':
                        send(True, True)
                        ready = packet.get('sensor_ok') and packet.get('hardware_ready')
                        assert packet.get('policy_rev')==6, 'Expected current temperature-band firmware'
                    elif packet.get('type')=='ack':
                        expected=pending.pop(packet.get('seq'),None)
                        assert expected and ack_matches(packet,expected)
            assert ready, 'Sensors not ready'
            for label, stopped, muted in stages:
                print('STAGE',label,flush=True)
                start=time.monotonic()
                while time.monotonic()-start<18:
                    for packet in receive():
                        if packet.get('type')=='telemetry':
                            assert packet.get('sensor_ok') and packet.get('hardware_ready'), 'Sensor fault'
                            assert packet['fan']=='OFF' and not packet['device_enable'], 'Unexpected motor run'
                            records.append(dict(stage=label,seconds=round(time.monotonic()-start,3),telemetry=packet))
                            send(stopped,muted)
                        elif packet.get('type')=='ack':
                            expected=pending.pop(packet.get('seq'),None)
                            assert expected and ack_matches(packet,expected), 'ACK mismatch'
                            assert packet['fan']=='OFF' and packet['vent']=='CLOSED' and not packet['device_enable']
                samples=[r['telemetry']['temperature'] for r in records if r['stage']==label and r['seconds']>=6]
                assert len(samples)>=10, 'Too few stable-phase samples'
                print('RANGE',label,min(samples),max(samples),flush=True)
            assert framer.errors==0, 'Framing error'
            completed=True
        finally:
            end=time.monotonic()+2
            while time.monotonic()<end:
                for packet in receive():
                    if packet.get('type')=='telemetry': send(True,True)
            summary={}
            for label, _, _ in stages:
                values=[r['telemetry']['temperature'] for r in records if r['stage']==label and r['seconds']>=6]
                if values: summary[label]={'min_c':min(values),'max_c':max(values),'samples':len(values)}
            report=dict(timestamp=datetime.datetime.now().isoformat(),completed=completed,
                        stage_summary=summary,framing_errors=framer.errors,records=records,
                        constraints='D9 CLOSED, D10 OFF; existing LED PWM and 5% buzzer; camera/GPU app paused',
                        root_cause_confirmed=False)
            (ROOT/'artifacts/dht-load-check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    return 0 if completed else 1


if __name__=='__main__':
    raise SystemExit(main())
