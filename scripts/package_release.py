#!/usr/bin/env python3
"""Create a portable source/model bundle without local PINs or runtime logs."""
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    dest = ROOT / 'dist'
    dest.mkdir(exist_ok=True)
    output = dest / 'Moble_Jetson_Safety_Monitor.zip'
    files = []
    for directory in ['app', 'config', 'docs', 'firmware', 'scripts', 'tests', 'models', '.vendor']:
        for file in (ROOT / directory).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts and file.name != 'local.json' and file.suffix != '.pyc':
                files.append(file)
    for name in ['README.md', 'requirements.txt', 'monitor.py', 'run.sh', 'run_integration.sh', 'run_ventilation.sh', '.gitignore', 'THIRD_PARTY.md']:
        files.append(ROOT / name)
    for name in ['dashboard.png', 'wiring.png', 'gpu-check.json', 'gpu-detections.jpg',
                 'python-tests.log', 'gui-check.log', 'firmware-build.log', 'firmware-enabled-build.log', 'readiness.json',
                 'hardware-first-read.json', 'hardware-ir-disabled-read.json',
                 'ide-hardware-check-upload.log', 'memory-check.json', 'camera-live-validation.json',
                 'hardware-commissioning-status.json', 'rgb-check-sequence.json', 'rgb-check-build.log',
                 'buzzer-check-sequence.json', 'buzzer-check-build.log', 'hardware-after-rgb-read.json',
                 'buzzer-tone-sequence.json', 'buzzer-tone-build.log',
                 'servo-first-check-sequence.json', 'servo-run-check-sequence.json',
                 'servo-one-second-sequence.json', 'hardware-after-servo-read.json', 'servo-check-build.log',
                 'power-check-result.json', 'power-check-sequence.json', 'power-check-memory.json',
                 'power-check-kernel.log', 'power-check-build.log', 'power-check-run.log',
                 'power-check-30s-servo-disconnected-result.json', 'power-check-10s-command-error-result.json',
                 'firmware-integration-build.log', 'firmware-integration-upload.log',
                 'integration-tests.log', 'integration-serial-result.json', 'integration-live-result.json',
                 'integration-live-before-final-check.json', 'integration-start-observation.json',
                 'ventilation-tests.log', 'ventilation-gui-check.log', 'ventilation-dashboard.png',
                 'firmware-ventilation-build.log', 'firmware-ventilation-upload.log',
                 'ventilation-serial-result.json', 'ventilation-live-result.json',
                 'ventilation-serial-first-result.json', 'ventilation-live-before-clearance-fix.json',
                 'camera-render-benchmark.json', 'camera-mode-comparison.json',
                 'camera-gpu-640-30.json', 'camera-gpu-320-30.json',
                 'camera-preview-performance.json', 'camera-preview-gui-check.log',
                 'camera-preview-tests.log', 'camera-dashboard-live-check.json',
                 'camera-dashboard-320-final.json', 'camera-dashboard-640-check.log',
                 'korean-dashboard.png', 'korean-ui-tests.log', 'korean-ui-check.log',
                 'korean-ventilation-gui-check.log', 'korean-general-gui-check.log',
                 'admin-tests.log', 'admin-ui-check.log', 'admin-ventilation-gui-check.log',
                 'admin-general-gui-check.log', 'admin-face-camera-check.json',
                 'admin-firmware-build.log', 'admin-firmware-upload.log',
                 'admin-serial-result.json', 'admin-live-result.json', 'admin-live-followup.json',
                 'admin-user-acceptance.json',
                 'quiet-buzzer-build.log', 'quiet-buzzer-upload.log', 'quiet-buzzer-tests.log',
                 'quiet-buzzer-serial.json', 'quiet-buzzer-live.json',
                 'quiet-buzzer-serial-17pct.json', 'quiet-buzzer-live-before-camera-fix.json',
                 'nearest-person-tests.log', 'nearest-person-gui-check.log',
                 'nearest-person-dashboard.png', 'nearest-person-live.json',
                 'nearest-person-user-acceptance.json', 'nearest-person-live-before-startup-fix.json',
                 'temp27-silent-intrusion-tests.log', 'temp27-silent-intrusion-build.log',
                 'temp27-silent-intrusion-upload.log', 'temp27-silent-intrusion-live.json',
                 'temp-bands-tests.log', 'temp-bands-build.log', 'temp-bands-upload.log',
                 'temp-bands-gui-check.log', 'temp-bands-dashboard.png', 'temp-bands-live.json',
                 'temperature-stop-tests.log', 'temperature-stop-build.log', 'temperature-stop-upload.log',
                 'temperature-stop-gui-check.log', 'temperature-stop-dashboard.png',
                 'temperature-stop-serial-result.json', 'temperature-stop-live.json',
                 'dht-jump-observation.json', 'dht-load-check.json', 'dht-recovery-status.json',
                 'd9-only-90-result.json', 'd9-only-zero-result.json',
                 'camera-decoupled-check.json', 'camera-capture-60.json',
                 'camera-dashboard-before-optimization.json', 'camera-supported-modes.log']:
        file = ROOT / 'artifacts' / name
        if file.exists():
            files.append(file)
    manifest = []
    with zipfile.ZipFile(str(output), 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(files):
            name = str(file.relative_to(ROOT))
            archive.write(str(file), 'Moble_Jetson_Safety_Monitor/' + name)
            manifest.append(hashlib.sha256(file.read_bytes()).hexdigest() + '  ' + name)
        archive.writestr('Moble_Jetson_Safety_Monitor/SHA256SUMS.txt', '\n'.join(manifest) + '\n')
    print(output)
    print('Files:', len(files), 'Bytes:', output.stat().st_size)


if __name__ == '__main__':
    main()
