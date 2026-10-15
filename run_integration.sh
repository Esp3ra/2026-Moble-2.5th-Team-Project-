#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"
# The user already joined dialout; older desktop/SSH sessions may not yet have
# that supplementary group. Refresh only for this process, without sudo.
if [[ -e /dev/ttyUSB0 && (! -r /dev/ttyUSB0 || ! -w /dev/ttyUSB0) && ${MOBLE_DIALOUT_REFRESHED:-0} != 1 ]]; then
  printf -v quoted_command '%q ' env MOBLE_DIALOUT_REFRESHED=1 bash "$project_root/run_integration.sh" "$@"
  exec sg dialout -c "$quoted_command"
fi
exec bash run.sh --config "$project_root/config/integration.json" "$@"
