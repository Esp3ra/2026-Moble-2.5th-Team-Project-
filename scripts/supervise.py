#!/usr/bin/env python3
"""Restart unexpected crashes up to three times. Never restart after user exit."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
child = None
stopping = False


def stop(*_):
    global stopping
    stopping = True
    if child and child.poll() is None:
        child.terminate()


def main():
    global child
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for attempt in range(4):
        env = dict(os.environ)
        if attempt:
            env['MOBLE_RECOVERED_AFTER_CRASH'] = '1'
        child = subprocess.Popen([sys.executable, str(ROOT / 'monitor.py')] + sys.argv[1:], cwd=str(ROOT), env=env)
        result = child.wait()
        if stopping or result in (0, 2, 3):
            return result
        if attempt < 3:
            print('Monitor crashed; restarting in {}s with device blocked.'.format(2 ** attempt), file=sys.stderr)
            time.sleep(2 ** attempt)
    return result


if __name__ == '__main__':
    sys.exit(main())
