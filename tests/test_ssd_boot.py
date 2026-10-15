"""SD-assisted SSD boot config and simulated initrd mount behavior."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import enable_ssd_root as boot

SD_UUID = '11111111-2222-3333-4444-555555555555'
SSD_UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
ORIGINAL = '''TIMEOUT 30
DEFAULT primary
MENU TITLE L4T boot options
LABEL primary
  MENU LABEL primary kernel
  LINUX /boot/Image
  INITRD /boot/initrd
  FDT /boot/dtb/example.dtb
  APPEND ${cbootargs} quiet root=/dev/mmcblk0p1 rw rootwait console=tty0
'''


class SSDBootTests(unittest.TestCase):
    def test_preserves_sd_boot_and_adds_ssd_entry(self):
        result = boot.boot_config(ORIGINAL, SSD_UUID)
        self.assertIn('DEFAULT moble_ssd', result)
        self.assertIn(ORIGINAL[ORIGINAL.index('LABEL primary'):].strip(), result)
        ssd = result.split('LABEL moble_ssd')[1]
        self.assertIn('INITRD /boot/initrd.moble-ssd', ssd)
        self.assertIn('root=PARTUUID=' + SSD_UUID, ssd)
        self.assertIn('FDT /boot/dtb/example.dtb', ssd)
        self.assertNotIn(' quiet ', ssd)

    def test_duplicate_entry_is_refused(self):
        with self.assertRaises(RuntimeError):
            boot.boot_config(boot.boot_config(ORIGINAL, SSD_UUID), SSD_UUID)

    def test_unexpected_initrd_is_refused(self):
        with self.assertRaises(RuntimeError):
            boot.boot_config(ORIGINAL.replace('/boot/initrd', '/boot/custom.img'), SSD_UUID)

    def test_unrecognized_initrd_script_is_refused(self):
        with self.assertRaises(RuntimeError):
            boot.patch_init('#!/bin/sh\necho hello\n', SD_UUID)

    def test_invalid_sd_uuid_is_refused(self):
        with self.assertRaises(RuntimeError):
            boot.fallback_branch('invalid; reboot')

    def test_apply_without_sudo_does_not_read_or_write_boot(self):
        with mock.patch.object(boot.os, 'geteuid', return_value=1000):
            with mock.patch.object(boot, 'inspect') as inspect:
                with self.assertRaises(RuntimeError):
                    boot.apply()
                inspect.assert_not_called()

    def simulate(self, ssd_after, sd_works):
        with tempfile.TemporaryDirectory() as directory:
            branch = boot.fallback_branch(SD_UUID).replace('/dev/kmsg', str(Path(directory) / 'kmsg'))
            script = '''#!/bin/bash
rootdev="PARTUUID=SSD_UUID"
attempts=0
mounted=no
mount() {
  if [[ "$1" == "PARTUUID=SSD_UUID" ]]; then
    attempts=$((attempts + 1))
    if [[ SSD_AFTER -gt 0 && $attempts -ge SSD_AFTER ]]; then mounted=yes; return 0; fi
    return 1
  fi
  if [[ "$1" == "PARTUUID=SD_UUID" && SD_WORKS == yes ]]; then mounted=yes; return 0; fi
  return 1
}
mountpoint() { [[ "$mounted" == yes ]]; }
sleep() { :; }
exec() { exit 91; }
if false; then :;
BRANCH
fi
printf '%s %s %s\\n' "$rootdev" "$mounted" "$attempts"
'''.replace('SSD_UUID', SSD_UUID).replace('SD_UUID', SD_UUID)
            script = script.replace('SSD_AFTER', str(ssd_after)).replace('SD_WORKS', 'yes' if sd_works else 'no')
            script = script.replace('BRANCH', branch)
            path = Path(directory) / 'simulate.sh'
            path.write_text(script)
            return subprocess.run(['bash', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True, timeout=15)

    def test_ssd_mount_success_uses_ssd(self):
        result = self.simulate(1, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'PARTUUID=' + SSD_UUID + ' yes 1')

    def test_usb_delay_retries_ssd_mount(self):
        result = self.simulate(4, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'PARTUUID=' + SSD_UUID + ' yes 4')

    def test_missing_ssd_falls_back_to_sd(self):
        result = self.simulate(0, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'PARTUUID=' + SD_UUID + ' yes 150')

    def test_both_missing_do_not_start_unmounted_root(self):
        result = self.simulate(0, False)
        self.assertEqual(result.returncode, 91, result.stderr)


if __name__ == '__main__':
    unittest.main()
