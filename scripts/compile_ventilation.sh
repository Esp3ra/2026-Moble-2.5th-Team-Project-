#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
flags='-DMOBLE_VENTILATION_PROFILE=1 -DWIRING_CONFIRMED=1 -DENABLE_DHT=1 -DENABLE_GAS=1 -DENABLE_LCD=1 -DENABLE_SERVO=1 -DENABLE_ROTATION_SERVO=1 -DENABLE_BUZZER=1 -DENABLE_STATUS_LEDS=1'
.tools/arduino-cli --config-file .tools/arduino-cli.yaml compile --jobs 1 \
  --fqbn arduino:avr:mega --build-property "compiler.cpp.extra_flags=$flags" \
  --output-dir build/mega-ventilation firmware/mega_controller
