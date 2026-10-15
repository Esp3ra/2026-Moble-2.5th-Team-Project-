"""Disk migration checks: all disk-writing tests use a sparse regular file."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'migrate_ssd', str(Path(__file__).resolve().parents[1] / 'scripts/migrate_ssd.py'))
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)

BOOT = '''TIMEOUT 30
DEFAULT primary
MENU TITLE L4T boot options
LABEL primary
  LINUX /boot/Image
  INITRD /boot/initrd
  FDT /boot/dtb/example.dtb
  APPEND ${cbootargs} quiet root=/dev/mmcblk0p1 rw rootwait console=tty0
LABEL backup
  LINUX /boot/Image.backup
  APPEND ${cbootargs} root=/dev/mmcblk0p1 rw
# APPEND root=/dev/untouched
'''
UUID = 'aabbccdd-0000-1111-2222-334455667788'


class SSDMigrationTests(unittest.TestCase):
    def test_default_entry_changes_and_backup_is_preserved(self):
        result = migration.extlinux_config(BOOT, UUID)
        self.assertIn('root=PARTUUID=' + UUID, result)
        self.assertIn('FDT /boot/dtb/example.dtb', result)
        self.assertIn('APPEND ${cbootargs} root=/dev/mmcblk0p1 rw', result)
        self.assertIn('# APPEND root=/dev/untouched', result)
        self.assertIn('console=tty0', result)

    def test_unknown_default_refused(self):
        with self.assertRaises(RuntimeError):
            migration.extlinux_config(BOOT.replace('DEFAULT primary', 'DEFAULT missing'), UUID)

    def test_ambiguous_default_refused(self):
        with self.assertRaises(RuntimeError):
            migration.extlinux_config('DEFAULT backup\n' + BOOT, UUID)

    def test_multiple_explicit_roots_refused(self):
        with self.assertRaises(RuntimeError):
            migration.extlinux_config(BOOT.replace('quiet root=', 'root=/bad quiet root='), UUID)

    def test_missing_explicit_root_refused(self):
        with self.assertRaises(RuntimeError):
            migration.extlinux_config(BOOT.replace('root=/dev/mmcblk0p1', ''), UUID)

    def test_invalid_partuuid_refused(self):
        with self.assertRaises(RuntimeError):
            migration.extlinux_config(BOOT, 'bad\nAPPEND root=/wrong')

    def test_old_swap_disabled_and_other_mount_preserved(self):
        original = '# keep comment\n/dev/root / ext4 defaults 0 1\n'
        original += '/swapfile none swap sw 0 0\nUUID=data /data ext4 defaults 0 2\n'
        result = migration.fstab_config(original, 'new-root', 'new-swap')
        active = [line.split() for line in result.splitlines() if line and not line.startswith('#')]
        self.assertEqual(sum(fields[1] == '/' for fields in active), 1)
        self.assertEqual(sum(fields[2] == 'swap' for fields in active), 1)
        self.assertIn('UUID=new-swap none swap sw,pri=1 0 0', result)
        self.assertIn('UUID=data /data ext4 defaults 0 2', result)

    def test_other_disk_size_refused(self):
        with self.assertRaises(RuntimeError):
            migration.layout(128 * 1024 ** 3)

    def test_other_sector_size_refused(self):
        with self.assertRaises(RuntimeError):
            migration.layout(migration.DISK_BYTES, 4096)

    def test_erasure_ack_required_before_any_mutation(self):
        with mock.patch.object(migration, 'command') as command:
            with self.assertRaises(RuntimeError):
                migration.apply({}, 'wrong-serial')
            command.assert_not_called()

    def test_root_required_before_any_mutation(self):
        with mock.patch.object(migration.os, 'geteuid', return_value=1000):
            with mock.patch.object(migration, 'command') as command:
                with self.assertRaises(RuntimeError):
                    migration.apply({}, migration.SERIAL)
                command.assert_not_called()

    def test_already_ssd_source_refused(self):
        with self.assertRaises(RuntimeError):
            migration.validate_source({'source_root': '/dev/sda1'})

    def test_wrong_opened_file_size_cannot_be_erased(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'wrong-size.img'
            original = b'preserve this content'
            image.write_bytes(original)
            with self.assertRaises(RuntimeError):
                migration.initialize_partition_table(image, migration.layout(migration.DISK_BYTES))
            self.assertEqual(image.read_bytes(), original)

    @unittest.skipUnless(all(shutil.which(tool) for tool in ('sgdisk', 'sfdisk', 'mkswap', 'wipefs')),
                         'Partition utilities unavailable')
    def test_recovers_from_gpt_swap_collision_that_stopped_old_script(self):
        plan = migration.layout(migration.DISK_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'corrupt.img'
            with image.open('wb') as stream:
                stream.truncate(migration.DISK_BYTES)
            image.chmod(0o600)
            subprocess.check_output(['sgdisk', '--clear', '--new=1:2048:0', str(image)],
                                    stderr=subprocess.STDOUT)
            subprocess.check_output(['mkswap', '--force', str(image)], stderr=subprocess.STDOUT)
            # Metadata backup must work without parsing the damaged GPT.
            migration.backup_metadata(image, directory)
            head = (Path(directory) / 'ssd-head-1MiB.bin').read_bytes()
            tail = (Path(directory) / 'ssd-tail-1MiB.bin').read_bytes()
            self.assertEqual(len(head), 1024 * 1024)
            self.assertEqual(len(tail), 1024 * 1024)
            self.assertEqual(head[4086:4096], b'SWAPSPACE2')
            subprocess.check_output(['wipefs', '--all', str(image)], stderr=subprocess.STDOUT)
            old = subprocess.run(['sgdisk', '--zap-all', str(image)], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, universal_newlines=True)
            if '1.0.3' in subprocess.check_output(['sgdisk', '--version']).decode():
                self.assertEqual(old.returncode, 2)
                self.assertIn('Invalid partition data', old.stdout)
            # Test the correction against the damaged original, not just zap's leftovers.
            with image.open('r+b') as stream:
                stream.write(head)
                stream.seek(migration.DISK_BYTES - len(tail))
                stream.write(tail)
            migration.initialize_partition_table(image, plan)
            report = json.loads(subprocess.check_output(['sfdisk', '--json', str(image)]).decode())
            self.assertEqual(report['partitiontable']['partitions'][1]['size'] * 512,
                             16 * 1024 ** 3)
            # Running the same recovery against a previously created layout is supported.
            migration.initialize_partition_table(image, plan)

    @unittest.skipUnless(shutil.which('sgdisk') and shutil.which('sfdisk'), 'GPT utilities unavailable')
    def test_recovers_when_both_gpt_headers_are_damaged(self):
        plan = migration.layout(migration.DISK_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'damaged-headers.img'
            with image.open('wb') as stream:
                stream.truncate(migration.DISK_BYTES)
            subprocess.check_output(['sgdisk', '--clear', '--new=1:2048:0', str(image)],
                                    stderr=subprocess.STDOUT)
            with image.open('r+b') as stream:
                stream.seek(512)
                stream.write(b'bad GPT!')
                stream.seek(migration.DISK_BYTES - 512)
                stream.write(b'bad GPT!')
            migration.initialize_partition_table(image, plan)

    @unittest.skipUnless(shutil.which('sgdisk') and shutil.which('sfdisk'), 'GPT utilities unavailable')
    def test_real_gpt_layout_on_sparse_regular_file(self):
        plan = migration.layout(migration.DISK_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'test-disk.img'
            with image.open('wb') as stream:
                stream.truncate(migration.DISK_BYTES)
            self.assertTrue(image.is_file())
            migration.initialize_partition_table(image, plan)
            data = json.loads(subprocess.check_output(['sfdisk', '--json', str(image)]).decode())
            root, swap = data['partitiontable']['partitions']
            self.assertEqual(root['name'], 'APP')
            self.assertEqual(swap['name'], 'SWAP16')
            self.assertEqual(swap['size'] * 512, 16 * 1024 ** 3)
            self.assertEqual(swap['start'] % 2048, 0)
            self.assertEqual(root['start'] + root['size'], swap['start'])
            self.assertEqual(swap['type'].upper(), '0657FD6D-A4AB-43C4-84E5-0933C84B4F4F')
            self.assertLess(swap['start'] + swap['size'], migration.DISK_BYTES // 512 - 33)


if __name__ == '__main__':
    unittest.main()
