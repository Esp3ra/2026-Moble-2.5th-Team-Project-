#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
.tools/arduino-cli --config-file .tools/arduino-cli.yaml compile --jobs 1 --fqbn arduino:avr:mega --output-dir build/mega firmware/mega_controller
