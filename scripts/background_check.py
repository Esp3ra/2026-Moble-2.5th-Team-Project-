#!/usr/bin/env python3
"""Record completion of a long local build even when the chat is interrupted."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
label = sys.argv[1]
with (ROOT / 'artifacts' / (label + '.log')).open('w') as log:
    result = subprocess.call(sys.argv[2:], cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
(ROOT / 'artifacts' / (label + '.exit')).write_text(str(result))
