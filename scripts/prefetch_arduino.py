#!/usr/bin/env python3
"""Use verified registry archives when CLI downloads time out on the Nano."""
import gzip
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / '.tools/arduino-data'
CACHE = ROOT / '.tools/downloads/packages'


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url.replace('http://', 'https://'), timeout=180) as r:
                return r.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def archive(item):
    path = CACHE / item['archiveFileName']
    expected = item['checksum'].split(':', 1)[-1]
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return
    print('Prefetch:', item['archiveFileName'], flush=True)
    raw = fetch(item['url'])
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Checksum mismatch: ' + item['archiveFileName'])
    path.write_bytes(raw)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    raw = fetch('https://downloads.arduino.cc/packages/package_index.json')
    (DATA / 'package_index.json').write_bytes(raw)
    registry = json.loads(raw.decode())
    package = next(p for p in registry['packages'] if p['name'] == 'arduino')
    platform = next(p for p in package['platforms'] if p['architecture'] == 'avr' and p['version'] == '1.8.6')
    archive(platform)
    for dep in platform['toolsDependencies']:
        tool = next(t for t in package['tools'] if t['name'] == dep['name'] and t['version'] == dep['version'])
        system = next(s for s in tool['systems'] if 'aarch64' in s['host'])
        archive(system)
    raw = gzip.decompress(fetch('https://downloads.arduino.cc/libraries/library_index.json.gz'))
    (DATA / 'library_index.json').write_bytes(raw)
    libraries = json.loads(raw.decode())['libraries']
    cache = ROOT / '.tools/downloads/libraries'
    cache.mkdir(exist_ok=True)
    for name, version in [('ArduinoJson', '6.21.5'), ('DHT sensor library', '1.4.6'), ('Adafruit Unified Sensor', '1.1.15'), ('Servo', '1.2.2'), ('LiquidCrystal I2C', '1.1.2')]:
        lib = next(l for l in libraries if l['name'] == name and l['version'] == version)
        target = cache / lib['archiveFileName']
        print('Prefetch:', lib['archiveFileName'], flush=True)
        content = fetch(lib['url'])
        if hashlib.sha256(content).hexdigest() != lib['checksum'].split(':', 1)[-1]:
            raise ValueError('Library checksum mismatch')
        target.write_bytes(content)
    print('Registry archives verified and cached.')


if __name__ == '__main__':
    main()
