#!/usr/bin/env python3
"""Keep SD boot files, run the copied SSD rootfs, fall back to SD if SSD cannot mount.

Default execution prepares reviewable files in artifacts/ssd-boot without changing
/boot. --apply installs them with sudo. No partitioning, formatting or rebooting.
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
OUTPUT = ROOT / 'artifacts/ssd-boot'
BACKUP = Path('/boot/extlinux/extlinux.conf.before-ssd-root')
NEW_INITRD = Path('/boot/initrd.moble-ssd')
LABEL = 'moble_ssd'
UUID_RE = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')


def boot_config(original, partuuid):
    # Reuse the validated default-entry root substitution, then extract its active lines.
    replaced = migration.extlinux_config(original, partuuid)
    default = re.search(r'^\s*DEFAULT\s+(\S+)\s*$', original, re.M).group(1)
    if re.search(r'^\s*LABEL\s+' + LABEL + r'\s*$', original, re.M):
        raise RuntimeError('SSD boot entry already exists; do not append another one.')
    selected = False
    block = []
    initrd_count = 0
    for line in replaced.splitlines():
        label = re.match(r'^\s*LABEL\s+(\S+)\s*$', line)
        if label:
            selected = label.group(1) == default
            if selected:
                block.append('LABEL ' + LABEL)
            continue
        if not selected or not line.strip() or line.lstrip().startswith('#'):
            continue
        if re.match(r'^\s*MENU LABEL\s+', line):
            line = '      MENU LABEL SSD operating system (SD fallback)'
        elif re.match(r'^\s*INITRD\s+', line):
            if line.split()[1:] != ['/boot/initrd']:
                raise RuntimeError('Unexpected original initrd directive.')
            line = '      INITRD /boot/initrd.moble-ssd'
            initrd_count += 1
        elif re.match(r'^\s*APPEND\s+', line):
            line = re.sub(r'(?<!\S)quiet(?=\s|$)', '', line)
        block.append(line)
    if initrd_count != 1:
        raise RuntimeError('Expected one initrd in the original default boot entry.')
    updated = re.sub(r'^\s*DEFAULT\s+\S+\s*$', 'DEFAULT ' + LABEL, original, count=1, flags=re.M)
    updated = re.sub(r'^TIMEOUT\s+\d+', 'TIMEOUT 50', updated, count=1, flags=re.M)
    return updated.rstrip() + '\n\n# SSD rootfs; original SD entry remains available.\n' + '\n'.join(block) + '\n'


def fallback_branch(sd_partuuid):
    if not UUID_RE.match(sd_partuuid):
        raise RuntimeError('Invalid SD partition UUID.')
    return '''elif [[ "${rootdev}" == PARTUUID* ]]; then
	count=0;
	while [ ${count} -lt 150 ]; do
		sleep 0.2;
		count="$(expr ${count} + 1)"
		mount "${rootdev}" /mnt/;
		if [ $? -eq 0 ]; then
			break;
		fi
	done
	if ! mountpoint -q /mnt/; then
		echo "SSD could not mount; falling back to original SD rootfs." > /dev/kmsg;
		rootdev="PARTUUID=SD_UUID";
		if ! mount "${rootdev}" /mnt/; then
			echo "ERROR: both SSD and SD root mounts failed." > /dev/kmsg;
			exec /bin/bash;
		fi;
	fi;
'''.replace('SD_UUID', sd_partuuid)


def patch_init(original, sd_partuuid):
    start = original.find('elif [[ "${rootdev}" == PARTUUID* ]]; then\n')
    end = original.find('elif [[ "${rootdev}" == mmcblk* || "${rootdev}" == nvme* ]]; then\n', start)
    if start < 0 or end < 0 or 'mount "${rootdev}" /mnt/;' not in original[start:end]:
        raise RuntimeError('Unexpected NVIDIA initrd root-mount implementation.')
    return original[:start] + fallback_branch(sd_partuuid) + original[end:]


def inspect():
    plan = migration.inventory()
    if plan['source_root'] != migration.SOURCE_ROOT:
        raise RuntimeError('Run setup from the original SD system. To verify SSD, use migrate_ssd.py --verify.')
    if Path(str(migration.BOOT_CONF) + '.sig').exists():
        raise RuntimeError('Signed boot configuration needs a custom setup.')
    mounts = migration.mount_targets(plan['disk'] + '1')
    if len(mounts) != 1:
        raise RuntimeError('Open the SSD APP volume in the file manager, then retry; SSD needs one mount.')
    ssd = Path(mounts[0])
    report = json.loads((ssd / 'etc/moble-ssd-migration.json').read_text())
    if report.get('serial') != migration.SERIAL or report.get('status') != 'copied_not_boot_verified':
        raise RuntimeError('Missing or unexpected completed-copy marker.')
    for key, directory, partition in [('root_uuid', 'by-uuid', '1'),
                                      ('root_partuuid', 'by-partuuid', '1'),
                                      ('swap_uuid', 'by-uuid', '2')]:
        value = report.get(key, '')
        if not UUID_RE.match(value) or os.path.realpath('/dev/disk/' + directory + '/' + value) != plan['disk'] + partition:
            raise RuntimeError('SSD identity does not match its copy marker: ' + key)
    for name in ('Image', 'initrd'):
        if migration.digest('/boot/' + name) != migration.digest(ssd / 'boot' / name):
            raise RuntimeError('SD and SSD boot files differ: ' + name)
    for relative in ('lib/systemd/systemd', 'lib/modules/' + os.uname().release):
        if not (ssd / relative).exists():
            raise RuntimeError('Missing SSD root file: ' + relative)
    fstab = (ssd / 'etc/fstab').read_text()
    if not re.search(r'^UUID=' + report['root_uuid'] + r'\s+/\s+ext4\s', fstab, re.M):
        raise RuntimeError('SSD fstab root entry is incorrect.')
    if not re.search(r'^UUID=' + report['swap_uuid'] + r'\s+none\s+swap\s', fstab, re.M):
        raise RuntimeError('SSD fstab swap entry is incorrect.')
    sd_partuuid = migration.command(['lsblk', '-n', '-o', 'PARTUUID', migration.SOURCE_ROOT])
    if not UUID_RE.match(sd_partuuid):
        raise RuntimeError('Cannot identify SD root partition UUID.')
    return report, sd_partuuid


def prepare():
    report, sd_partuuid = inspect()
    original = migration.BOOT_CONF.read_text()
    output_config = boot_config(original, report['root_partuuid'])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nano-ssd-initrd-') as directory:
        directory = Path(directory)
        tree = directory / 'tree'
        migration.command(['unmkinitramfs', '/boot/initrd', tree])
        init = tree / 'init'
        if not init.is_file():
            raise RuntimeError('Unexpected multi-part initrd archive; setup stopped.')
        init.write_text(patch_init(init.read_text(), sd_partuuid))
        migration.command(['bash', '-n', init])
        # Store the exact patched script for review and behavioral tests.
        (OUTPUT / 'init.preview').write_text(init.read_text())
        names = ['.'] + sorted(str(path.relative_to(tree)) for path in tree.rglob('*'))
        cpio_path = directory / 'initrd.cpio'
        with cpio_path.open('wb') as destination:
            result = subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--owner=0:0'],
                                    input=('\0'.join(names) + '\0').encode(), cwd=str(tree),
                                    stdout=destination, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError(result.stderr.decode())
        compressed = OUTPUT / 'initrd.moble-ssd'
        with cpio_path.open('rb') as source, compressed.open('wb') as target:
            with gzip.GzipFile(fileobj=target, mode='wb', mtime=0) as archive:
                shutil.copyfileobj(source, archive)
        # Unpack the actual generated archive, not just the staging directory.
        check = directory / 'check'
        migration.command(['unmkinitramfs', compressed, check])
        if (check / 'init').read_bytes() != init.read_bytes():
            raise RuntimeError('Generated initrd did not preserve the patched init script.')
        for required in ('bin/bash', 'bin/mount', 'bin/mountpoint', 'sbin/blkid',
                         'lib/firmware/tegra21x_xusb_firmware'):
            path = check / required
            if not path.exists() and not path.is_symlink():
                raise RuntimeError('Required boot file missing from generated initrd: ' + required)
    (OUTPUT / 'extlinux.conf').write_text(output_config)
    manifest = {'original_config_sha256': migration.digest(migration.BOOT_CONF),
                'original_initrd_sha256': migration.digest('/boot/initrd'),
                'kernel_sha256': migration.digest('/boot/Image'),
                'prepared_initrd_sha256': migration.digest(compressed),
                'prepared_config_sha256': migration.digest(OUTPUT / 'extlinux.conf'),
                'ssd_partuuid': report['root_partuuid'], 'sd_partuuid': sd_partuuid}
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('PREPARED:', OUTPUT)
    print('SD boot files -> SSD operating system; fallback to SD if SSD cannot mount.')
    print('No partition, filesystem, firmware or /boot setting has been changed.')


def apply():
    if os.geteuid() != 0:
        raise RuntimeError('sudo is required to install the prepared boot configuration.')
    report, sd_partuuid = inspect()
    manifest = json.loads((OUTPUT / 'manifest.json').read_text())
    for key, path in [('original_config_sha256', migration.BOOT_CONF),
                      ('original_initrd_sha256', Path('/boot/initrd')),
                      ('kernel_sha256', Path('/boot/Image')),
                      ('prepared_initrd_sha256', OUTPUT / 'initrd.moble-ssd'),
                      ('prepared_config_sha256', OUTPUT / 'extlinux.conf')]:
        if migration.digest(path) != manifest[key]:
            raise RuntimeError('File changed after preparation: ' + str(path))
    if report['root_partuuid'] != manifest['ssd_partuuid'] or sd_partuuid != manifest['sd_partuuid']:
        raise RuntimeError('A partition changed after preparation.')
    if BACKUP.exists() or NEW_INITRD.exists():
        raise RuntimeError('Previous SD boot setup exists; inspect or restore it before applying again.')
    # Only after all checks: install new initrd, preserve original config, then switch default.
    staging = NEW_INITRD.with_name(NEW_INITRD.name + '.new')
    shutil.copyfile(str(OUTPUT / 'initrd.moble-ssd'), str(staging))
    staging.chmod(0o644)
    with staging.open('rb') as stream:
        os.fsync(stream.fileno())
    os.replace(str(staging), str(NEW_INITRD))
    shutil.copy2(str(migration.BOOT_CONF), str(BACKUP))
    migration.command(['sync'])
    migration.atomic_write(migration.BOOT_CONF, (OUTPUT / 'extlinux.conf').read_text())
    migration.command(['sync'])
    print('INSTALLED. Leave both SD and SSD connected, then reboot.')
    print('No repartitioning or copying is required. The original SD entry and initrd remain.')
    print('After reboot: python3 scripts/migrate_ssd.py --verify')


def restore():
    if os.geteuid() != 0:
        raise RuntimeError('sudo is required to restore the SD boot configuration.')
    if os.path.realpath(migration.command(['findmnt', '-n', '-o', 'SOURCE', '/'])) != migration.SOURCE_ROOT:
        raise RuntimeError('Restore from the SD fallback system: power off, unplug SSD, boot with SD.')
    if not BACKUP.is_file():
        raise RuntimeError('Original SD configuration backup is missing.')
    migration.atomic_write(migration.BOOT_CONF, BACKUP.read_text())
    migration.command(['sync'])
    print('Original SD boot configuration restored. Backups have been retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if args.apply:
        apply()
    elif args.restore:
        restore()
    else:
        prepare()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print('STOPPED:', error, file=sys.stderr)
        sys.exit(1)
