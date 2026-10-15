#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
mkdir -p models artifacts
/usr/src/tensorrt/bin/trtexec --onnx=models/yolov5n.onnx --minShapes=images:1x3x320x320 --optShapes=images:1x3x320x320 --maxShapes=images:1x3x320x320 --fp16 --workspace=128 --saveEngine=models/person_fp16.engine --buildOnly
