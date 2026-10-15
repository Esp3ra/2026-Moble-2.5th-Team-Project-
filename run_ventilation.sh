#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"
if [[ -e /dev/ttyUSB0 && (! -r /dev/ttyUSB0 || ! -w /dev/ttyUSB0) && ${MOBLE_DIALOUT_REFRESHED:-0} != 1 ]]; then
  printf -v quoted_command '%q ' env MOBLE_DIALOUT_REFRESHED=1 bash "$project_root/run_ventilation.sh" "$@"
  exec sg dialout -c "$quoted_command"
fi
exec bash run.sh --config "$project_root/config/ventilation.json" "$@"
