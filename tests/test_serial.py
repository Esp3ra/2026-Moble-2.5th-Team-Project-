"""Exercise the actual pySerial reader against a pseudo-terminal MCU."""
import json
import os
from pathlib import Path
import pty
import select
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.vendor'))
from app.devices import SerialLink
from app.protocol import command, encode
from test_core import sample


class FakeMega:
    def __init__(self):
        self.master, self.slave = pty.openpty()
        self.port = os.ttyname(self.slave)
        self.stopped = threading.Event()
        self.silent = False
        self.ack_enabled = True
        self.seq = 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        buf = bytearray()
        next_sample = 0
        while not self.stopped.is_set():
            now = time.monotonic()
            if not self.silent and now >= next_sample:
                self.seq += 1
                try:
                    os.write(self.master, encode(sample(self.seq)))
                except OSError:
                    pass
                next_sample = now + 0.05
            if select.select([self.master], [], [], 0.02)[0]:
                try:
                    buf.extend(os.read(self.master, 4096))
                except OSError:
                    continue
                while b'\n' in buf:
                    line, _, remainder = buf.partition(b'\n')
                    buf = bytearray(remainder)
                    try:
                        msg = json.loads(line.decode())
                    except ValueError:
                        continue
                    if msg.get('type') == 'command' and self.ack_enabled and not self.silent:
                        ack = dict(msg, type='ack', accepted=True)
                        os.write(self.master, encode(ack))

    def close(self):
        self.stopped.set()
        self.thread.join(1)
        os.close(self.master)
        os.close(self.slave)


class SerialRecoveryTests(unittest.TestCase):
    def test_real_serial_timeout_and_reconnect(self):
        mega = FakeMega()
        link = SerialLink({'port': mega.port, 'baud': 115200, 'stale_seconds': 0.35, 'ack_seconds': 0.3, 'retry_seconds': 0.1})
        link.start()
        seq = 0

        def wait_for(predicate, timeout=3):
            nonlocal seq
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                seq += 1
                link.submit(command(seq, 'NORMAL', 'CLOSED', False, False, 42))
                snap = link.snapshot(time.monotonic())
                if predicate(snap):
                    return snap
                time.sleep(0.03)
            self.fail('Serial condition not reached: ' + str(link.snapshot(time.monotonic())))

        try:
            healthy = wait_for(lambda s: s['healthy'] and s['telemetry'] is not None)
            reconnects = healthy['reconnects']
            mega.silent = True
            wait_for(lambda s: not s['connected'])
            mega.silent = False
            recovered = wait_for(lambda s: s['healthy'] and s['reconnects'] > reconnects)
            self.assertGreater(recovered['telemetry']['seq'], healthy['telemetry']['seq'])
            mega.ack_enabled = False
            reconnects = recovered['reconnects']
            wait_for(lambda s: not s['connected'])
            mega.ack_enabled = True
            wait_for(lambda s: s['healthy'] and s['reconnects'] > reconnects)
        finally:
            link.close()
            mega.close()


if __name__ == '__main__':
    unittest.main()
