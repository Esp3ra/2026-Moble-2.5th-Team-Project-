#!/usr/bin/env python3
"""Verify/download pinned OpenCV Zoo models and build local TensorRT FP16 engines."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-only', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'models'
    manifest = json.loads((directory / 'face-sources.json').read_text())
    for name, info in manifest['files'].items():
        path = directory / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == info['sha256']:
            continue
        print('Downloading', name, flush=True)
        with urllib.request.urlopen(info['url'], timeout=180) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != info['sha256']:
            raise ValueError('Model checksum mismatch: ' + name)
        temporary = path.with_suffix('.download')
        temporary.write_bytes(data)
        temporary.replace(path)
    if args.download_only:
        return
    import tensorrt as trt
    for stem, size in [('face_detection_yunet', 640), ('face_recognition_sface', 112)]:
        logger = trt.Logger(trt.Logger.WARNING)
        builder = trt.Builder(logger)
        network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
        parser = trt.OnnxParser(network, logger)
        if not parser.parse((directory / (stem + '.onnx')).read_bytes()):
            raise RuntimeError('\n'.join(str(parser.get_error(i)) for i in range(parser.num_errors)))
        network.get_input(0).shape = (1, 3, size, size)
        config = builder.create_builder_config()
        config.max_workspace_size = 128 * 1024 * 1024
        config.set_flag(trt.BuilderFlag.FP16)
        print('Building', stem, flush=True)
        engine = builder.build_engine(network, config)
        if engine is None:
            raise RuntimeError('TensorRT build failed: ' + stem)
        target = directory / (stem + '_fp16.engine')
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(bytes(engine.serialize()))
        temporary.replace(target)
        print('Built', target.name, target.stat().st_size, flush=True)
        del engine, parser, config, network, builder


if __name__ == '__main__':
    main()
