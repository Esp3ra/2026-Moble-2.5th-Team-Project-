#!/usr/bin/env python3
"""Prepare SSD-local boot files. --apply installs them; --verify requires no SD.

Runs from the migrated SSD. Never formats media, flashes firmware or reboots.
"""
import argparse
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import migrate_ssd as migration

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts/ssd-standalone'
INITRD = Path('/boot/initrd.moble-standalone')
CONFIG = Path('/boot/extlinux/extlinux.conf')
BACKUP = Path('/boot/extlinux/extlinux.conf.before-standalone')
DTB = Path('/boot/dtb/kernel_tegra210-p3448-0000-p3449-0000-b00.dtb')
LABEL = 'moble_standalone'
MARKER = 'moble_boot=ssd_standalone'
UUID_RE = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')


def inspect():
    plan = migration.inventory()
    report = json.loads(Path('/etc/moble-ssd-migration.json').read_text())
    if plan['source_root'] != plan['disk'] + '1' or report.get('serial') != migration.SERIAL:
        raise RuntimeError('Run this setup from the migrated Samsung SSD operating system.')
    for key, kind, suffix in (('root_uuid', 'by-uuid', '1'),
                              ('root_partuuid', 'by-partuuid', '1'),
                              ('swap_uuid', 'by-uuid', '2')):
        value = report.get(key, '')
        if not UUID_RE.match(value) or os.path.realpath('/dev/disk/' + kind + '/' + value) != plan['disk'] + suffix:
            raise RuntimeError('SSD identity mismatch: ' + key)
    if Path(str(CONFIG) + '.sig').exists():
        raise RuntimeError('Signed configuration requires a separate secure-boot procedure.')
    dts = Path('/proc/device-tree/nvidia,dtsfilename').read_bytes().rstrip(b'\0').decode()
    if not dts.endswith('/tegra210-p3448-0000-p3449-0000-b00.dts'):
        raise RuntimeError('This setup targets the inspected Nano B01 device tree only.')
    for path in (Path('/boot/Image'), Path('/boot/initrd'), DTB, CONFIG):
        if not path.is_file() or os.stat(str(path)).st_dev != os.stat('/').st_dev:
            raise RuntimeError('Boot file must reside on the SSD: ' + str(path))
    fstab = Path('/etc/fstab').read_text()
    if not re.search(r'^UUID=' + report['root_uuid'] + r'\s+/\s+ext4\s', fstab, re.M):
        raise RuntimeError('SSD fstab root entry is incorrect.')
    return report


def boot_config(original, partuuid):
    if re.search(r'^\s*LABEL\s+' + LABEL + r'\s*$', original, re.M):
        raise RuntimeError('Standalone entry already exists; use --verify or inspect it.')
    default = re.search(r'^\s*DEFAULT\s+(\S+)\s*$', original, re.M)
    if not default:
        raise RuntimeError('Cannot identify existing default boot entry.')
    replaced = migration.extlinux_config(original, partuuid)
    selected = False
    block = []
    kernel_count = initrd_count = fdt_count = append_count = 0
    for line in replaced.splitlines():
        label = re.match(r'^\s*LABEL\s+(\S+)\s*$', line)
        if label:
            selected = label.group(1) == default.group(1)
            if selected:
                block.append('LABEL ' + LABEL)
            continue
        if not selected or not line.strip() or line.lstrip().startswith('#'):
            continue
        directive = line.split()[0]
        if directive == 'LINUX':
            if line.split()[1:] != ['/boot/Image']:
                raise RuntimeError('Unexpected kernel path.')
            kernel_count += 1
        elif directive == 'INITRD':
            line = '      INITRD ' + str(INITRD)
            initrd_count += 1
        elif directive == 'FDT':
            line = '      FDT ' + str(DTB)
            fdt_count += 1
        elif directive == 'APPEND':
            line = re.sub(r'(?<!\S)quiet(?=\s|$)', '', line)
            line += ' ' + MARKER
            append_count += 1
        elif line.strip().startswith('MENU LABEL '):
            line = '      MENU LABEL SSD standalone boot'
        block.append(line)
    if (kernel_count, initrd_count, append_count) != (1, 1, 1) or fdt_count > 1:
        raise RuntimeError('Unexpected boot entry structure.')
    if fdt_count == 0:
        block.insert(2, '      FDT ' + str(DTB))
    result = re.sub(r'^\s*DEFAULT\s+\S+\s*$', 'DEFAULT ' + LABEL, original, count=1, flags=re.M)
    return result.rstrip() + '\n\n# All boot files and rootfs below are on the SSD.\n' + '\n'.join(block) + '\n'


def standalone_branch():
    return '''elif [[ "${rootdev}" == PARTUUID* ]]; then
	count=0;
	while [ ${count} -lt 150 ]; do
		sleep 0.2;
		count="$(expr ${count} + 1)";
		if mount "${rootdev}" /mnt/; then
			break;
		fi;
	done;
	if ! mountpoint -q /mnt/; then
		echo "ERROR: SSD standalone root mount failed after 30 seconds." > /dev/kmsg;
		exec /bin/bash;
	fi;
'''


def patch_init(original):
    start = original.find('elif [[ "${rootdev}" == PARTUUID* ]]; then\n')
    end = original.find('elif [[ "${rootdev}" == mmcblk* || "${rootdev}" == nvme* ]]; then\n', start)
    if start < 0 or end < 0 or 'mount "${rootdev}" /mnt/;' not in original[start:end]:
        raise RuntimeError('Unexpected NVIDIA initrd root-mount implementation.')
    return original[:start] + standalone_branch() + original[end:]


def prepare():
    report = inspect()
    original = CONFIG.read_text()
    prepared_config = boot_config(original, report['root_partuuid'])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nano-standalone-') as directory:
        directory = Path(directory)
        tree = directory / 'tree'
        migration.command(['unmkinitramfs', '/boot/initrd', tree])
        init = tree / 'init'
        init.write_text(patch_init(init.read_text()))
        migration.command(['bash', '-n', init])
        (OUTPUT / 'init.preview').write_text(init.read_text())
        names = ['.'] + sorted(str(path.relative_to(tree)) for path in tree.rglob('*'))
        cpio = directory / 'initrd.cpio'
        with cpio.open('wb') as stream:
            result = subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--owner=0:0'],
                                    input=('\0'.join(names) + '\0').encode(), cwd=str(tree),
                                    stdout=stream, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError(result.stderr.decode())
        prepared_initrd = OUTPUT / INITRD.name
        with cpio.open('rb') as source, prepared_initrd.open('wb') as destination:
            with gzip.GzipFile(fileobj=destination, mode='wb', mtime=0) as archive:
                shutil.copyfileobj(source, archive)
        unpacked = directory / 'check'
        migration.command(['unmkinitramfs', prepared_initrd, unpacked])
        if (unpacked / 'init').read_bytes() != init.read_bytes():
            raise RuntimeError('Generated initrd script differs after extraction.')
        for relative in ('bin/bash', 'bin/mount', 'bin/mountpoint', 'sbin/blkid',
                         'lib/firmware/tegra21x_xusb_firmware'):
            path = unpacked / relative
            if not path.exists() and not path.is_symlink():
                raise RuntimeError('Required initrd file missing: ' + relative)
    (OUTPUT / 'extlinux.conf').write_text(prepared_config)
    source_files = [CONFIG, Path('/boot/Image'), Path('/boot/initrd'), DTB]
    manifest = {'ssd_partuuid': report['root_partuuid'],
                'source_hashes': {str(path): migration.digest(path) for path in source_files},
                'output_hashes': {name: migration.digest(OUTPUT / name)
                                  for name in ('extlinux.conf', INITRD.name)}}
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('PREPARED:', OUTPUT)
    print('SSD boot files prepared; /boot and QSPI firmware have not been modified.')


def apply():
    if os.geteuid() != 0:
        raise RuntimeError('sudo is required to install SSD boot files.')
    report = inspect()
    manifest = json.loads((OUTPUT / 'manifest.json').read_text())
    if report['root_partuuid'] != manifest['ssd_partuuid']:
        raise RuntimeError('SSD changed after preparation.')
    for path, expected in manifest['source_hashes'].items():
        if migration.digest(path) != expected:
            raise RuntimeError('Source changed after preparation: ' + path)
    for name, expected in manifest['output_hashes'].items():
        if migration.digest(OUTPUT / name) != expected:
            raise RuntimeError('Prepared file changed: ' + name)
    if BACKUP.exists() or INITRD.exists():
        raise RuntimeError('Standalone setup already exists; use --verify or inspect it.')
    # NVIDIA's -v branch reads the bootloader version; it never installs a BUP.
    firmware = subprocess.run(['/usr/sbin/l4t_payload_updater_t210', '-v'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True)
    (OUTPUT / 'firmware-version.txt').write_text(firmware.stdout)
    print(firmware.stdout, flush=True)
    if firmware.returncode:
        raise RuntimeError('Cannot read bootloader version; see firmware-version.txt.')
    staged = INITRD.with_name(INITRD.name + '.new')
    shutil.copyfile(str(OUTPUT / INITRD.name), str(staged))
    staged.chmod(0o644)
    with staged.open('rb') as stream:
        os.fsync(stream.fileno())
    os.replace(str(staged), str(INITRD))
    shutil.copy2(str(CONFIG), str(BACKUP))
    migration.command(['sync'])
    migration.atomic_write(CONFIG, (OUTPUT / 'extlinux.conf').read_text())
    migration.command(['sync'])
    print('INSTALLED: SSD-local kernel, device tree and initrd configuration.')
    print('QSPI firmware and the SD boot configuration are unchanged. No reboot performed.')
    print('SSD-only boot is not verified yet; bootloader USB support must also work.')


def verify():
    migration.verify()
    if Path('/sys/class/block/mmcblk0').exists():
        raise RuntimeError('SD is still present; SSD-only boot is not yet proven.')
    if MARKER not in Path('/proc/cmdline').read_text().split():
        raise RuntimeError('Standalone SSD boot entry was not used.')
    print('PASS: standalone SSD boot with no SD card; 16 GiB SSD swap active.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.apply:
        apply()
    elif args.verify:
        verify()
    else:
        prepare()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print('STOPPED:', error, file=sys.stderr)
        sys.exit(1)
