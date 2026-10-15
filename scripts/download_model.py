#!/usr/bin/env python3
"""Download pinned YOLOv5n v6.0 ONNX and record source hashes."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    'yolov5n.onnx': 'https://github.com/ultralytics/yolov5/releases/download/v6.0/yolov5n.onnx',
    'YOLO_LICENSE': 'https://raw.githubusercontent.com/ultralytics/yolov5/v6.0/LICENSE'
}


def main():
    dest = ROOT / 'models'
    dest.mkdir(exist_ok=True)
    manifest_path = dest / 'yolo-sources.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {'release': 'v6.0', 'files': {}}
    for name, url in SOURCES.items():
        target = dest / name
        info = manifest['files'].get(name)
        if target.exists() and info and hashlib.sha256(target.read_bytes()).hexdigest() == info['sha256']:
            continue
        print('Downloading', name, flush=True)
        with urllib.request.urlopen(url, timeout=180) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if info and digest != info['sha256']:
            raise ValueError('Checksum mismatch: ' + name)
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
        manifest['files'][name] = {'url': url, 'sha256': digest}
        manifest_path.write_text(json.dumps(manifest, indent=2))
    print('YOLOv5n v6.0 ready')


if __name__ == '__main__':
    main()
