#!/usr/bin/env python3
"""Run a bounded, no-load hardware/GPU bench check and restore hardware_check.

Requires separately powered servos (5V/common GND), known 1500us neutral,
clear servo travel, compiled power-check/hardware-check binaries, and an idle
serial port. This operates hardware and is not a supply voltage certification.
"""
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.vendor'))
import serial
import cv2
from app.config import load
from app.devices import Camera

OUT = ROOT / 'artifacts'


def upload(folder):
    cli = [str(ROOT / '.tools/arduino-cli'), '--config-file', str(ROOT / '.tools/arduino-cli.yaml')]
    with (OUT / ('power-test-upload-' + folder + '.log')).open('w') as log:
        subprocess.run(cli + ['upload', '--fqbn', 'arduino:avr:mega', '--port', '/dev/ttyUSB0',
                             '--input-dir', str(ROOT / 'build' / folder)], stdout=log,
                       stderr=subprocess.STDOUT, timeout=60, check=True)
    print('Uploaded ' + folder, flush=True)


def kernel_lines():
    result = subprocess.run(['dmesg'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, timeout=5)
    return result.stdout.splitlines() if result.returncode == 0 else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, choices=(6, 10, 30), default=6)
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    if args.preview and not os.environ.get('DISPLAY'):
        parser.error('--preview requires DISPLAY, e.g. DISPLAY=:0')
    for name in ('power-check/power_check.ino.hex', 'hardware-check/hardware_check.ino.hex'):
        if not (ROOT / 'build' / name).is_file():
            raise RuntimeError('Compile the required sketch first: ' + name)
    OUT.mkdir(exist_ok=True)
    cfg = load()
    camera = Camera(cfg['camera'], cfg['vision'])
    port = None
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Brief simultaneous no-load actuator and live camera/GPU check',
              'external_servo_voltage_measured': False, 'passed_observed_checks': False,
              'visual_confirmation': 'pending', 'restored_sensor_firmware': False,
              'backlight': 'continuously_ON_no_PWM_control', 'error': ''}
    report['requested_load_seconds'] = args.seconds
    report['preview_enabled'] = args.preview
    window = 'Moble Power Check + GPU Camera - Q / Esc to stop'
    packets, frames, inferences, memory = [], [], [], []
    kernel_before = kernel_lines()
    have_ready = False
    last_uptime = None
    load_at = done_at = None
    last_telemetry = last_ping = last_memory = 0
    buffer = b''
    try:
        if args.preview:
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window, 900, 650)
        upload('power-check')
        port = serial.Serial('/dev/ttyUSB0', 115200, timeout=0, write_timeout=0.5, exclusive=True)
        began = time.monotonic()
        deadline = began + cfg['camera']['startup_seconds'] + args.seconds + 30
        sensor = None
        while time.monotonic() < deadline:
            now = time.monotonic()
            # Let the Mega bootloader exit before sending any serial traffic.
            if have_ready and now - last_ping >= 0.2:
                port.write(b'!')
                last_ping = now
            data = port.read(min(port.in_waiting, 4096))
            buffer += data
            if len(buffer) > 8192:
                raise RuntimeError('Serial framing overflow')
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    packet = json.loads(line.decode('utf-8'))
                except (ValueError, UnicodeError):
                    raise RuntimeError('Malformed serial packet')
                packet['host_elapsed_s'] = round(now - began, 3)
                packets.append(packet)
                uptime = packet.get('uptime_ms')
                if uptime is not None:
                    if last_uptime is not None and uptime < last_uptime:
                        raise RuntimeError('Unexpected Mega reset')
                    last_uptime = uptime
                phase = packet.get('phase', '')
                if packet.get('type') == 'power_phase':
                    print(phase, flush=True)
                    if phase == 'READY / NO DRIVE':
                        if have_ready:
                            raise RuntimeError('Unexpected Mega startup')
                        have_ready = True
                    elif phase == 'LOAD DONE':
                        done_at = now
                    elif phase.startswith(('TIMEOUT', 'DHT ERROR', 'I2C ERROR', 'SENSOR NOT', 'OVERFLOW', 'BAD COMMAND')):
                        raise RuntimeError(phase)
                elif packet.get('type') == 'power_check':
                    sensor = packet
                    last_telemetry = now
                    if packet['i2c_timeout'] or not packet['lcd_ready']:
                        raise RuntimeError('LCD/I2C fault')
                    if load_at is not None and not packet['dht_ok']:
                        raise RuntimeError('DHT read fault during/after load')
            frame, _, fresh = camera.poll(now)
            if camera.generation > 1:
                raise RuntimeError('Camera/GPU worker restarted')
            if not have_ready and now - began > 12:
                raise RuntimeError('Mega startup was not received; LOAD was never sent')
            if fresh:
                frames.append(now)
                inferences.append(camera.result['inference_ms'])
                if len(frames) == 1:
                    print('Camera/GPU frames received', flush=True)
                if args.preview:
                    preview = frame.copy()
                    for detection in camera.result['boxes']:
                        x1, y1, x2, y2 = detection['box']
                        cv2.rectangle(preview, (x1, y1), (x2, y2), (30, 220, 90), 2)
                    text = 'GPU People: {} | {}'.format(camera.result['count'], sensor['phase'] if sensor else 'Starting')
                    cv2.putText(preview, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (40, 255, 100), 1, cv2.LINE_AA)
                    cv2.imshow(window, preview)
            if args.preview:
                if cv2.getWindowProperty(window, cv2.WND_PROP_AUTOSIZE) < 0:
                    raise RuntimeError('Preview closed by operator')
                if cv2.waitKey(1) & 0xff in (27, ord('q')):
                    raise RuntimeError('Stopped by operator from preview')
            if now - last_memory >= 1:
                info = dict((s.split(':')[0], int(s.split()[1])) for s in Path('/proc/meminfo').read_text().splitlines())
                memory.append({'elapsed_s': round(now - began, 3), 'available_kib': info['MemAvailable'],
                               'swap_free_kib': info['SwapFree']})
                last_memory = now
            if load_at is None and have_ready and sensor and sensor['dht_ok'] and len(frames) >= 20:
                if now - last_telemetry > 1:
                    raise RuntimeError('Telemetry stale before load')
                print('Starting simultaneous load: {} seconds'.format(args.seconds), flush=True)
                port.write(('LOAD{}\n'.format(args.seconds) if args.seconds != 6 else 'LOAD\n').encode('ascii'))
                load_at = now
            if load_at is not None:
                if now - last_telemetry > 2:
                    raise RuntimeError('Telemetry interrupted under load')
                if frames and now - frames[-1] > 2:
                    raise RuntimeError('Camera frames interrupted under load')
                if done_at is None and now - load_at > args.seconds + 5:
                    raise RuntimeError('Load sequence failed to finish')
            if done_at and now - done_at >= 5:
                break
            time.sleep(0.01)
        if not done_at:
            raise RuntimeError('Timed out before load completion')
        active_frames = [t for t in frames if load_at <= t <= done_at]
        report.update({'load_duration_s': done_at - load_at, 'frames_during_load': len(active_frames),
                       'frames': len(frames), 'worker_generations': camera.generation,
                       'median_inference_ms': statistics.median(inferences),
                       'processed_fps': (len(frames) - 1) / (frames[-1] - frames[0]),
                       'serial_packets': len(packets), 'unexpected_resets': 0,
                       'dht_errors_during_load': 0, 'i2c_timeout': False})
        if len(active_frames) < 5:
            raise RuntimeError('Insufficient camera overlap with actuator load')
        report['passed_observed_checks'] = True
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc) or 'Interrupted by operator'
        print('STOP: ' + str(exc), flush=True)
    finally:
        if port is not None:
            try:
                port.write(b'STOP\n'); port.flush()
            except (OSError, serial.SerialException):
                pass
            port.close()
        camera.close()
        if args.preview:
            cv2.destroyAllWindows()
        try:
            upload('hardware-check')
            report['restored_sensor_firmware'] = True
        except Exception as exc:
            report['restore_error'] = str(exc)
            report['passed_observed_checks'] = False
        before = set(kernel_before)
        new_kernel = [line for line in kernel_lines() if line not in before]
        report['kernel_log_readable'] = bool(kernel_before)
        report['kernel_power_usb_memory_warnings'] = [line for line in new_kernel if re.search(
            r'OC ALARM|under.?volt|over.?current|out of memory|oom-kill|killed process|usb.*(?:disconnect|reset|error)|ch341.*(?:disconnect|error)',
            line, re.I)]
        if report['kernel_power_usb_memory_warnings']:
            report['passed_observed_checks'] = False
        report['min_mem_available_mib'] = min((r['available_kib'] / 1024 for r in memory), default=None)
        (OUT / 'power-check-sequence.json').write_text(json.dumps(packets, indent=2) + '\n')
        (OUT / 'power-check-memory.json').write_text(json.dumps(memory, indent=2) + '\n')
        (OUT / 'power-check-kernel.log').write_text('\n'.join(new_kernel) + '\n')
        (OUT / 'power-check-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed_observed_checks'] else 1


if __name__ == '__main__':
    sys.exit(main())
