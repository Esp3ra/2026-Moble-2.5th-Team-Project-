#!/usr/bin/env python3
"""Migrate this Nano's SD rootfs to its identified SSD. Default: read-only plan.

Python 3.6 compatible. Never changes the SD boot configuration or reboots.
The apply option ERASES the identified SSD and requires root plus its serial.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SERIAL = "235678C218CA"
DEVICE_ID = "/dev/disk/by-id/usb-Samsung_SSD_840_EVO_120G_235678C218CA-0:0"
DISK_BYTES = 120034123776
SOURCE_ROOT = "/dev/mmcblk0p1"
SWAP_BYTES = 16 * 1024 ** 3
METADATA_BYTES = 1024 * 1024
PROJECT = Path(__file__).resolve().parents[1]
BOOT_CONF = Path("/boot/extlinux/extlinux.conf")
RULE_PATH = Path("/run/udev/rules.d/99-moble-ssd-migration.rules")
ENV = dict(os.environ, PATH="/usr/sbin:/usr/bin:/sbin:/bin", LC_ALL="C")


def command(args, capture=True, allowed=(0,)):
    result = subprocess.run([str(x) for x in args], env=ENV,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None,
                            universal_newlines=True)
    if result.returncode not in allowed:
        raise RuntimeError("Command failed ({}): {}\n{}".format(
            result.returncode, " ".join(str(x) for x in args),
            "\n".join(part for part in (result.stdout, result.stderr) if part)
            or "See terminal output."))
    return result.stdout.strip() if capture else result.returncode


def properties(device):
    lines = command(["udevadm", "info", "--query=property", "--name=" + device])
    return dict(line.split("=", 1) for line in lines.splitlines() if "=" in line)


def layout(total_bytes, sector_bytes=512):
    if sector_bytes != 512 or total_bytes != DISK_BYTES:
        raise RuntimeError("Unexpected disk geometry; refusing this disk.")
    alignment = 1024 * 1024 // sector_bytes
    end = ((total_bytes // sector_bytes - alignment) // alignment) * alignment
    swap_start = end - SWAP_BYTES // sector_bytes
    return {"root_start": alignment, "root_end": swap_start - 1,
            "swap_start": swap_start, "swap_end": end - 1,
            "root_bytes": (swap_start - alignment) * sector_bytes,
            "swap_bytes": SWAP_BYTES}


def extlinux_config(original, partuuid):
    if not re.match(r"^[0-9a-fA-F-]{36}$", partuuid):
        raise RuntimeError("Invalid GPT PARTUUID.")
    defaults = re.findall(r"^\s*DEFAULT\s+(\S+)\s*$", original, re.M)
    if len(defaults) != 1:
        raise RuntimeError("Cannot identify one default boot entry.")
    selected = False
    changed = 0
    output = []
    for line in original.splitlines():
        label = re.match(r"^\s*LABEL\s+(\S+)\s*$", line)
        if label:
            selected = label.group(1) == defaults[0]
        if selected and re.match(r"^\s*APPEND\s+", line):
            if len(re.findall(r"(?<!\S)root=\S+", line)) != 1:
                raise RuntimeError("Expected exactly one explicit root argument.")
            line = re.sub(r"(?<!\S)root=\S+", "root=PARTUUID=" + partuuid, line)
            changed += 1
        output.append(line)
    if changed != 1:
        raise RuntimeError("Cannot safely update the default boot entry.")
    return "\n".join(output) + "\n"


def fstab_config(original, root_uuid, swap_uuid):
    output = []
    for line in original.splitlines():
        fields = line.split()
        if fields and not line.lstrip().startswith("#") and len(fields) >= 3:
            if fields[1] == "/" or fields[2] == "swap":
                output.append("# Previous SD entry: " + line)
                continue
        output.append(line)
    output.extend(["", "# SSD root and 16 GiB SSD swap; NVIDIA zram remains enabled.",
                   "UUID={} / ext4 defaults,noatime 0 1".format(root_uuid),
                   "UUID={} none swap sw,pri=1 0 0".format(swap_uuid)])
    return "\n".join(output) + "\n"


def inventory():
    if not Path(DEVICE_ID).exists():
        raise RuntimeError("The identified Samsung SSD is not connected.")
    disk = os.path.realpath(DEVICE_ID)
    props = properties(disk)
    if props.get("ID_SERIAL_SHORT") != SERIAL or props.get("ID_BUS") != "usb":
        raise RuntimeError("SSD identity mismatch.")
    name = Path(disk).name
    if (Path("/sys/class/block") / name / "partition").exists():
        raise RuntimeError("Target must be a whole disk.")
    sysdisk = Path("/sys/class/block") / name
    size = int((sysdisk / "size").read_text()) * 512
    sector = int((sysdisk / "queue/logical_block_size").read_text())
    plan = layout(size, sector)
    root = os.path.realpath(command(["findmnt", "-n", "-o", "SOURCE", "/"]))
    plan.update({"disk": disk, "serial": SERIAL, "disk_bytes": size,
                 "source_root": root, "model": props.get("ID_MODEL"),
                 "root_GiB": round(plan["root_bytes"] / 1024 ** 3, 3),
                 "swap_GiB": 16, "apply_requires_root": True})
    return plan


def members(disk):
    return command(["lsblk", "-n", "-r", "-o", "NAME", disk]).splitlines()


def mount_targets(device):
    return command(["findmnt", "-r", "-n", "-S", device, "-o", "TARGET"],
                   allowed=(0, 1)).splitlines()


def validate_source(plan):
    if plan["source_root"] != SOURCE_ROOT:
        raise RuntimeError("Apply requires the original SD rootfs. Already on SSD?")
    if "t210" not in Path("/etc/nv_tegra_release").read_text():
        raise RuntimeError("This script is for the inspected Jetson Nano only.")
    source_mounts = json.loads(command(["findmnt", "-J", "-o", "TARGET,SOURCE"]))

    def check_mounts(entries):
        for entry in entries:
            target = entry["target"]
            if target != "/" and any(target == p or target.startswith(p + "/")
                                     for p in ("/boot", "/home", "/usr", "/var", "/opt")):
                raise RuntimeError("Separate source mount needs a custom migration: " + target)
            check_mounts(entry.get("children", []))
    check_mounts(source_mounts["filesystems"])
    for required in ("/boot/Image", "/boot/initrd", str(BOOT_CONF)):
        if not Path(required).is_file():
            raise RuntimeError("Missing boot file: " + required)
    if Path(str(BOOT_CONF) + ".sig").exists():
        raise RuntimeError("Signed boot configuration needs a custom migration.")
    extlinux_config(BOOT_CONF.read_text(), "00000000-0000-0000-0000-000000000001")
    occupied = shutil.disk_usage("/").used
    if plan["root_bytes"] < occupied + 5 * 1024 ** 3:
        raise RuntimeError("Insufficient destination root capacity.")
    disk_members = members(plan["disk"])
    active_swap = [os.path.realpath(line.split()[0]) for line in
                   Path("/proc/swaps").read_text().splitlines()[1:]]
    for name in disk_members:
        if "/dev/" + name in active_swap:
            raise RuntimeError("Target is active swap; refusing to erase it.")
        if list((Path("/sys/class/block") / name / "holders").iterdir()):
            raise RuntimeError("Target has a block-device holder: " + name)
        for target in mount_targets("/dev/" + name):
            if not target.startswith(("/media/", "/run/media/")):
                raise RuntimeError("Target is mounted outside removable media: " + target)
    return disk_members


def unmount_members(names):
    for name in reversed(names):
        for target in reversed(mount_targets("/dev/" + name)):
            command(["umount", target])  # Never force or lazy-unmount.
    for name in names:
        if mount_targets("/dev/" + name):
            raise RuntimeError("Target remains mounted: " + name)


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def atomic_write(path, content):
    path = Path(path)
    temporary = path.with_name(path.name + ".ssd-new")
    with temporary.open("w") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o644)
    os.replace(str(temporary), str(path))


def disk_edges(stream):
    """Check the opened device itself, not just its cached udev size."""
    size = stream.seek(0, os.SEEK_END)
    if size != DISK_BYTES:
        raise RuntimeError("Opened target has an unexpected size; refusing disk I/O.")
    return (0, size - METADATA_BYTES)


def backup_metadata(disk, backup):
    """Save raw metadata even when GPT is corrupt or has already been wiped."""
    with open(str(disk), "rb", buffering=0) as stream:
        for offset, name in zip(disk_edges(stream), ("ssd-head-1MiB.bin", "ssd-tail-1MiB.bin")):
            stream.seek(offset)
            data = stream.read(METADATA_BYTES)
            if len(data) != METADATA_BYTES:
                raise RuntimeError("Short read while backing up SSD metadata.")
            with (Path(backup) / name).open("wb") as destination:
                destination.write(data)
                destination.flush()
                os.fsync(destination.fileno())


def initialize_partition_table(disk, plan):
    """Called only after apply's identity, consent, mount and swap checks.

    wipefs removes signatures, not all GPT structures. Older sgdisk versions
    can refuse even --zap-all/--clear on malformed GPT. Clear the reserved
    first/last MiB without parsing the old table, then create a new GPT.
    The first partition starts after this region; both regions were backed up.
    """
    zeros = bytes(METADATA_BYTES)
    with open(str(disk), "r+b", buffering=0) as stream:
        offsets = disk_edges(stream)
        for offset in offsets:
            stream.seek(offset)
            if stream.write(zeros) != len(zeros):
                raise RuntimeError("Short write while initializing SSD metadata.")
        os.fsync(stream.fileno())
        for offset in offsets:
            stream.seek(offset)
            if stream.read(METADATA_BYTES) != zeros:
                raise RuntimeError("SSD metadata readback failed; check SSD and USB connection.")
    command(["sgdisk", "--clear", "--set-alignment=2048",
             "--new=1:{}:{}".format(plan["root_start"], plan["root_end"]),
             "--typecode=1:8300", "--change-name=1:APP",
             "--new=2:{}:{}".format(plan["swap_start"], plan["swap_end"]),
             "--typecode=2:8200", "--change-name=2:SWAP16", disk])
    # JSON readback verifies both partition sizes and their types before formatting.
    table = json.loads(command(["sfdisk", "--json", disk]))["partitiontable"]
    partitions = table.get("partitions", [])
    expected = [(plan["root_start"], plan["root_bytes"], "APP",
                 "0FC63DAF-8483-4772-8E79-3D69D8477DE4"),
                (plan["swap_start"], SWAP_BYTES, "SWAP16",
                 "0657FD6D-A4AB-43C4-84E5-0933C84B4F4F")]
    if table.get("label") != "gpt" or len(partitions) != 2:
        raise RuntimeError("New GPT readback failed.")
    for actual, (start, size, name, guid) in zip(partitions, expected):
        if (actual.get("start") != start or actual.get("size", 0) * 512 != size or
                actual.get("name") != name or actual.get("type", "").upper() != guid):
            raise RuntimeError("New GPT partition does not match the requested layout.")


def apply(plan, erase_serial):
    if erase_serial != SERIAL:
        raise RuntimeError("SSD erasure requires --erase-serial " + SERIAL)
    if os.geteuid() != 0:
        raise RuntimeError("Run this command with sudo in your Jetson terminal.")
    for tool in ("rsync", "sgdisk", "sfdisk", "wipefs", "partprobe", "mkfs.ext4", "mkswap",
                 "mount", "umount", "blkid", "udevadm", "sync"):
        if not shutil.which(tool, path=ENV["PATH"]):
            raise RuntimeError("Required utility missing: " + tool)
    lock = open("/run/lock/moble-ssd-migration.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    names = validate_source(plan)
    original_boot = BOOT_CONF.read_text()
    original_fstab = Path("/etc/fstab").read_text()
    if RULE_PATH.exists():
        raise RuntimeError("Previous automount guard exists: " + str(RULE_PATH))
    backup = Path(tempfile.mkdtemp(prefix="moble-ssd-backup-", dir="/var/tmp"))
    (backup / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    (backup / "sd-extlinux.conf").write_text(original_boot)
    (backup / "sd-fstab").write_text(original_fstab)
    backup_metadata(plan["disk"], backup)
    (backup / "ssd-signatures.txt").write_text(command(["wipefs", "-n", plan["disk"]]))
    print("SSD DATA WILL BE ERASED. Partition metadata backup (not data):", backup, flush=True)
    mountpoint = Path(tempfile.mkdtemp(prefix="moble-ssd-", dir="/mnt"))
    mounted = False
    guard = False
    try:
        RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # udisks respects this property for this serial only; unrelated disks are unaffected.
        RULE_PATH.write_text('SUBSYSTEM=="block", ENV{ID_SERIAL_SHORT}=="' + SERIAL +
                             '", ENV{UDISKS_IGNORE}="1"\n')
        guard = True
        command(["udevadm", "control", "--reload-rules"])
        command(["udevadm", "trigger", "--action=change", "--subsystem-match=block"])
        command(["udevadm", "settle", "--timeout=30"])
        unmount_members(names)
        # Check identity and source again immediately before the first destructive operation.
        if inventory() != plan:
            raise RuntimeError("Disk state changed during preparation.")
        validate_source(plan)
        initialize_partition_table(plan["disk"], plan)
        command(["partprobe", plan["disk"]])
        command(["udevadm", "settle", "--timeout=30"])
        root_part, swap_part = plan["disk"] + "1", plan["disk"] + "2"
        for partition, expected in ((root_part, plan["root_bytes"]), (swap_part, SWAP_BYTES)):
            actual = int((Path("/sys/class/block") / Path(partition).name / "size").read_text()) * 512
            if actual != expected or mount_targets(partition):
                raise RuntimeError("Unexpected new partition size or mount: " + partition)
            command(["wipefs", "--all", partition])
        command(["mkfs.ext4", "-L", "APP", "-m", "1", root_part], capture=False)
        command(["mkswap", "-L", "SWAP16", swap_part], capture=False)
        command(["mount", root_part, mountpoint])
        mounted = True
        if os.path.realpath(command(["findmnt", "-n", "-o", "SOURCE", str(mountpoint)])) != root_part:
            raise RuntimeError("Unexpected destination mount.")
        exclusions = ["/dev/*", "/proc/*", "/sys/*", "/run/*", "/tmp/*", "/var/tmp/*",
                      "/mnt/*", "/media/*", "/lost+found"]
        base = ["rsync", "-aHAXx", "--numeric-ids", "--info=progress2", "--stats",
                "--log-file=" + str(backup / "rsync.log")]
        base.extend("--exclude=" + value for value in exclusions)
        for iteration in (1, 2):
            print("Copy pass {} of 2. Keep applications and package updates closed.".format(iteration), flush=True)
            result = command(base + ["/", str(mountpoint) + "/"], capture=False, allowed=(0, 24))
            if result == 24:
                print("Files vanished during live copy; see rsync.log. Retrying live files on next pass.", flush=True)
                if iteration == 2:
                    command(base + ["/", str(mountpoint) + "/"], capture=False)
        partuuid = command(["blkid", "-s", "PARTUUID", "-o", "value", root_part])
        root_uuid = command(["blkid", "-s", "UUID", "-o", "value", root_part])
        swap_uuid = command(["blkid", "-s", "UUID", "-o", "value", swap_part])
        target_boot = mountpoint / "boot/extlinux/extlinux.conf"
        shutil.copy2(str(target_boot), str(target_boot) + ".before-ssd")
        atomic_write(target_boot, extlinux_config(original_boot, partuuid))
        atomic_write(mountpoint / "etc/fstab", fstab_config(original_fstab, root_uuid, swap_uuid))
        # Hash all delivered application files and the two critical boot binaries.
        checked = 0
        paths = [Path("/boot/Image"), Path("/boot/initrd")]
        for folder in ("app", "config", "firmware", "scripts", "models", ".vendor"):
            paths.extend(p for p in (PROJECT / folder).rglob("*")
                         if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
        paths.extend(PROJECT / name for name in ("monitor.py", "run.sh", "README.md"))
        for source in paths:
            target = mountpoint / source.relative_to("/")
            if digest(source) != digest(target):
                raise RuntimeError("Copied file checksum mismatch: " + str(source))
            checked += 1
        if BOOT_CONF.read_text() != original_boot or Path("/etc/fstab").read_text() != original_fstab:
            raise RuntimeError("Source boot configuration changed during migration.")
        report = dict(plan, status="copied_not_boot_verified", root_partuuid=partuuid,
                      root_uuid=root_uuid, swap_uuid=swap_uuid, checked_files=checked,
                      backup_directory=str(backup))
        (backup / "copy-result.json").write_text(json.dumps(report, indent=2) + "\n")
        atomic_write(mountpoint / "etc/moble-ssd-migration.json", json.dumps(report, indent=2) + "\n")
        command(["sync"])
        command(["umount", mountpoint])
        mounted = False
        print("COPY COMPLETE; BOOT NOT YET VERIFIED. SD boot configuration is unchanged.")
        print("Power off, remove SD while power is off, leave SSD attached, then power on.")
        print("After boot: python3 '{}' --verify".format(PROJECT / "scripts/migrate_ssd.py"))
        print("Copy report:", backup / "copy-result.json")
    finally:
        if mounted:
            try:
                command(["umount", mountpoint])
                mounted = False
            except RuntimeError as error:
                print("Unmount failed; do not unplug SSD:", error, file=sys.stderr)
        if not mounted:
            mountpoint.rmdir()
        if guard:
            RULE_PATH.unlink()
            command(["udevadm", "control", "--reload-rules"])
            command(["udevadm", "trigger", "--action=change", "--subsystem-match=block"])


def verify():
    report_path = Path("/etc/moble-ssd-migration.json")
    if not report_path.is_file():
        raise RuntimeError("No completed SSD copy marker in this root filesystem.")
    report = json.loads(report_path.read_text())
    root = os.path.realpath(command(["findmnt", "-n", "-o", "SOURCE", "/"]))
    expected_root = os.path.realpath("/dev/disk/by-uuid/" + report["root_uuid"])
    if root != expected_root:
        raise RuntimeError("Currently running root filesystem is not the migrated SSD.")
    swap_device = os.path.realpath("/dev/disk/by-uuid/" + report["swap_uuid"])
    swap_size = int((Path("/sys/class/block") / Path(swap_device).name / "size").read_text()) * 512
    if swap_size != SWAP_BYTES:
        raise RuntimeError("Swap partition is not 16 GiB.")
    swaps = [os.path.realpath(line.split()[0]) for line in Path("/proc/swaps").read_text().splitlines()[1:]]
    if swap_device not in swaps:
        raise RuntimeError("SSD swap is not active.")
    print("PASS: SSD root filesystem and 16 GiB SSD swap are active.")
    print(command(["findmnt", "/"]))
    print(command(["swapon", "--show"]))
    print(command(["free", "-h"]))
    print("NVIDIA zram is retained; total swap may be about 18 GiB.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="ERASE SSD and copy SD rootfs; requires sudo")
    mode.add_argument("--verify", action="store_true", help="Read-only check after booting SSD")
    parser.add_argument("--erase-serial", help="Explicit erasure acknowledgement; must match target serial")
    args = parser.parse_args()
    if args.verify:
        verify()
        return
    plan = inventory()
    validate_source(plan)
    print(json.dumps(plan, indent=2), flush=True)
    if args.apply:
        apply(plan, args.erase_serial)
    else:
        print("READ-ONLY PLAN. No partitions, filesystems, swap or boot settings changed.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyboardInterrupt) as error:
        print("STOPPED:", error, file=sys.stderr)
        sys.exit(1)
