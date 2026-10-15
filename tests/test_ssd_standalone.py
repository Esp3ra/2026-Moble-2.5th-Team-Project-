"""Standalone boot configuration and simulated initrd; no real mounts or reboot."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import enable_ssd_standalone as boot

UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
ORIGINAL = '''TIMEOUT 30
DEFAULT primary
MENU TITLE L4T boot options
LABEL primary
  MENU LABEL primary kernel
  LINUX /boot/Image
  INITRD /boot/initrd
  APPEND ${cbootargs} quiet root=PARTUUID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee rw rootwait console=tty0
'''


class StandaloneBootTests(unittest.TestCase):
    def test_ssd_entry_names_every_boot_file_and_preserves_original(self):
        result = boot.boot_config(ORIGINAL, UUID)
        self.assertIn('DEFAULT moble_standalone', result)
        self.assertIn(ORIGINAL[ORIGINAL.index('LABEL primary'):], result)
        entry = result.split('LABEL moble_standalone')[1]
        self.assertIn('LINUX /boot/Image', entry)
        self.assertIn('INITRD /boot/initrd.moble-standalone', entry)
        self.assertIn('FDT ' + str(boot.DTB), entry)
        self.assertIn(boot.MARKER, entry)
        self.assertIn('root=PARTUUID=' + UUID, entry)
        self.assertNotIn(' quiet ', entry)
        self.assertNotIn('mmcblk', entry)

    def test_existing_dtb_directive_is_replaced_once(self):
        result = boot.boot_config(ORIGINAL.replace('  INITRD', '  FDT /boot/old.dtb\n  INITRD'), UUID)
        entry = result.split('LABEL moble_standalone')[1]
        self.assertEqual(entry.count('FDT '), 1)
        self.assertNotIn('/boot/old.dtb', entry)

    def test_duplicate_setup_refused(self):
        with self.assertRaises(RuntimeError):
            boot.boot_config(boot.boot_config(ORIGINAL, UUID), UUID)

    def test_unknown_kernel_refused(self):
        with self.assertRaises(RuntimeError):
            boot.boot_config(ORIGINAL.replace('/boot/Image', '/boot/custom'), UUID)

    def test_missing_initrd_refused(self):
        with self.assertRaises(RuntimeError):
            boot.boot_config(ORIGINAL.replace('  INITRD /boot/initrd\n', ''), UUID)

    def test_unrecognized_init_script_refused(self):
        with self.assertRaises(RuntimeError):
            boot.patch_init('#!/bin/bash\necho custom boot')

    def test_apply_needs_root_before_any_setup(self):
        with mock.patch.object(boot.os, 'geteuid', return_value=1000):
            with mock.patch.object(boot, 'inspect') as inspect:
                with self.assertRaises(RuntimeError):
                    boot.apply()
                inspect.assert_not_called()

    def test_sd_present_is_not_reported_as_standalone_success(self):
        with mock.patch.object(boot.migration, 'verify'):
            with mock.patch.object(Path, 'exists', return_value=True):
                with self.assertRaisesRegex(RuntimeError, 'SD is still present'):
                    boot.verify()

    def simulate(self, succeeds_after):
        with tempfile.TemporaryDirectory() as directory:
            branch = boot.standalone_branch().replace('/dev/kmsg', str(Path(directory) / 'kmsg'))
            script = '''#!/bin/bash
rootdev="PARTUUID=SSD_UUID"
attempts=0
mounted=no
mount() {
  [[ "$1" == "PARTUUID=SSD_UUID" ]] || exit 92
  attempts=$((attempts + 1))
  if [[ AFTER -gt 0 && $attempts -ge AFTER ]]; then mounted=yes; return 0; fi
  return 1
}
mountpoint() { [[ "$mounted" == yes ]]; }
sleep() { :; }
exec() { exit 91; }
if false; then :;
BRANCH
fi
printf '%s %s\\n' "$mounted" "$attempts"
'''.replace('SSD_UUID', UUID).replace('AFTER', str(succeeds_after)).replace('BRANCH', branch)
            path = Path(directory) / 'simulate.sh'
            path.write_text(script)
            return subprocess.run(['bash', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True, timeout=15)

    def test_success_mounts_only_requested_ssd(self):
        result = self.simulate(1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'yes 1')

    def test_usb_delay_beyond_original_limit_is_supported(self):
        result = self.simulate(70)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'yes 70')

    def test_failed_mount_stops_without_attempting_sd_or_booting_empty_root(self):
        result = self.simulate(0)
        self.assertEqual(result.returncode, 91, result.stderr)


if __name__ == '__main__':
    unittest.main()
