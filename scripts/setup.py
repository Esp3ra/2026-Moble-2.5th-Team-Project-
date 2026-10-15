#!/usr/bin/env python3
"""Install project-local dependencies without changing JetPack/system packages."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def fetch(url):
    print('Download:', url, flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def install_python():
    metadata = json.loads(fetch('https://pypi.org/pypi/pyserial/3.5/json').decode())
    wheel = next(f for f in metadata['urls'] if f['filename'].endswith('.whl'))
    data = fetch(wheel['url'])
    if hashlib.sha256(data).hexdigest() != wheel['digests']['sha256']:
        raise ValueError('pyserial checksum mismatch')
    dest = ROOT / '.vendor'
    dest.mkdir(exist_ok=True)
    zipfile.ZipFile(io.BytesIO(data)).extractall(str(dest))
    (dest / 'pyserial-source.json').write_text(json.dumps({'url': wheel['url'], 'sha256': wheel['digests']['sha256'], 'version': '3.5'}, indent=2))
    for module in ['cv2', 'numpy', 'tkinter']:
        __import__(module)
    print('Python dependencies ready; existing system OpenCV/NumPy retained.')


def install_arduino():
    version = '1.2.2'
    arch = {'aarch64': 'ARM64', 'x86_64': '64bit'}.get(platform.machine())
    if not arch:
        raise ValueError('Unsupported host: ' + platform.machine())
    root = ROOT / '.tools'
    root.mkdir(exist_ok=True)
    cli = root / 'arduino-cli'
    if not cli.exists():
        name = 'arduino-cli_{}_Linux_{}.tar.gz'.format(version, arch)
        prefix = 'https://github.com/arduino/arduino-cli/releases/download/v{}/'.format(version)
        checksums = fetch(prefix + '{}-checksums.txt'.format(version)).decode()
        expected = next(line.split()[0] for line in checksums.splitlines() if line.endswith(name))
        data = fetch(prefix + name)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Arduino CLI checksum mismatch')
        archive = tarfile.open(fileobj=io.BytesIO(data), mode='r:gz')
        member = next(m for m in archive.getmembers() if m.name == 'arduino-cli')
        cli.write_bytes(archive.extractfile(member).read())
        cli.chmod(0o755)
    configuration = root / 'arduino-cli.yaml'
    configuration.write_text(json.dumps({'directories': {'data': str(root / 'arduino-data'), 'downloads': str(root / 'downloads'), 'user': str(root / 'arduino-user')}, 'network': {'connection_timeout': '600s'}}))
    base = [str(cli), '--config-file', str(configuration)]
    commands = [['core', 'update-index'], ['core', 'install', 'arduino:avr@1.8.6'],
                ['lib', 'install', 'ArduinoJson@6.21.5', 'DHT sensor library@1.4.6',
                 'Adafruit Unified Sensor@1.1.15', 'Servo@1.2.2', 'LiquidCrystal I2C@1.1.2']]
    for cmd in commands:
        try:
            subprocess.check_call(base + cmd)
        except subprocess.CalledProcessError:
            # The old board's CLI downloads can fail on an unstable connection.
            # Refill its cache from the official indexes, checking every SHA256.
            subprocess.check_call([os.sys.executable, str(ROOT / 'scripts/prefetch_arduino.py')])
            if cmd != ['core', 'update-index']:
                subprocess.check_call(base + cmd)
    print('Arduino build environment ready.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arduino', action='store_true')
    args = parser.parse_args()
    install_python()
    if args.arduino:
        install_arduino()
