#!/usr/bin/env python3
"""Stage the existing telemetry script in STS2 immediately before a clean OBS launch.

Default mode only reports the proposed action. --apply is intended for the
ubuntu user's sts2-obs.service ExecStartPre; it never starts or stops OBS.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import stat
import tempfile

COLLECTION = Path('/home/ubuntu/.config/obs-studio/basic/scenes/STS2.json')
TELEMETRY = Path('/home/ubuntu/jev-obs/obs-performance-status.lua')
DESTINATION = '/home/ubuntu/jev-obs/performance-status.json'
BACKUPS = Path('/home/ubuntu/jev-obs/telemetry-next-start-backup')
# Root QGA verified this machine-id against libvirt/DMI UUID
# fd83a53b-7bd7-4364-b06c-2bd6abd428bc during deployment review.
EXPECTED_MACHINE_ID_SHA256 = 'c6c7bbf1c2f89700340c9afc707a01be67185bd744fcde7a3cd78aceae438076'


class GuardError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise GuardError(message)


def checked_file(path):
    for parent in reversed(path.parents):
        require(not parent.is_symlink(), 'A required parent is a symlink')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            'Expected an ordinary file with one hard link')
    require(info.st_uid == 1000 and info.st_gid == 1000 and not info.st_mode & 0o002,
            'Unexpected file owner or writable permissions')
    return info


def obs_running():
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid == 1000 and (proc / 'comm').read_text().strip() == 'obs':
                return True
        except FileNotFoundError:
            continue
    return False


def check_vm_identity():
    path = Path('/etc/machine-id')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and not info.st_mode & 0o022, 'Unexpected machine-id ownership or permissions')
    actual = hashlib.sha256(path.read_text().strip().encode()).hexdigest()
    require(actual == EXPECTED_MACHINE_ID_SHA256, 'Machine-id does not match obs-production')


def add_telemetry_entry(document):
    result = copy.deepcopy(document)
    require(isinstance(result, dict), 'Expected a scene collection object')
    modules = result.get('modules')
    require(isinstance(modules, dict), 'Expected scene collection modules')
    scripts = modules.get('scripts-tool')
    require(isinstance(scripts, list), 'Expected existing script-tool list')
    matches = [entry for entry in scripts
               if isinstance(entry, dict) and entry.get('path') == str(TELEMETRY)]
    require(len(matches) <= 1, 'Duplicate telemetry entries require review')
    if matches:
        require(isinstance(matches[0].get('settings'), dict)
                and matches[0]['settings'].get('destination') == DESTINATION,
                'Existing telemetry settings conflict with the approved destination')
        return result, False
    scripts.append({'path': str(TELEMETRY),
                    'settings': {'destination': DESTINATION}})
    check = copy.deepcopy(result)
    check['modules']['scripts-tool'].pop()
    require(check == document, 'Unexpected change outside the telemetry entry')
    return result, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Read-only check (the default)')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(socket.gethostname() == 'obs-production' and os.geteuid() == 1000
            and pwd.getpwuid(os.geteuid()).pw_name == 'ubuntu',
            'Run only as ubuntu UID 1000 inside obs-production')
    check_vm_identity()
    before = checked_file(COLLECTION)
    checked_file(TELEMETRY)
    original = COLLECTION.read_bytes()
    updated, changed = add_telemetry_entry(json.loads(original))
    running = obs_running()
    if not args.apply:
        print(json.dumps({'read_only': True, 'telemetry_entry_needed': changed,
                          'obs_running': running, 'apply_allowed_now': not running}))
        return
    require(not running, 'OBS is running; no scene configuration was changed')
    if not changed:
        print('Telemetry already configured; no change')
        return
    if not BACKUPS.exists():
        BACKUPS.mkdir(mode=0o700)
    backup_info = BACKUPS.lstat()
    require(stat.S_ISDIR(backup_info.st_mode) and backup_info.st_uid == 1000
            and stat.S_IMODE(backup_info.st_mode) == 0o700,
            'Backup directory must be a private directory owned by ubuntu')
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = BACKUPS / ('STS2.' + timestamp + '.before.json')
    with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
        f.write(original)
        f.flush()
        os.fsync(f.fileno())
    encoded = (json.dumps(updated, ensure_ascii=False, indent=4) + '\n').encode()
    require(json.loads(encoded) == updated, 'Scene JSON serialization changed data')
    fd, temporary_name = tempfile.mkstemp(prefix='.STS2.telemetry-', dir=COLLECTION.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchown(f.fileno(), -1, before.st_gid)
            os.fchmod(f.fileno(), stat.S_IMODE(before.st_mode))
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        current = checked_file(COLLECTION)
        require((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
                == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                and COLLECTION.read_bytes() == original,
                'Scene collection changed during preparation; preserved without replacement')
        require(not obs_running(), 'OBS appeared during preparation; no replacement')
        os.replace(temporary, COLLECTION)
        directory = os.open(COLLECTION.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        require(json.loads(COLLECTION.read_bytes()) == updated, 'Post-write verification failed')
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({'telemetry_added': True, 'backup': str(backup),
                      'before_sha256': hashlib.sha256(original).hexdigest()}))


if __name__ == '__main__':
    try:
        main()
    except (GuardError, OSError, ValueError) as error:
        # Scene source settings can contain secrets. Never print their contents
        # or a JSON parser's source context while reporting a failed guard.
        detail = str(error) if isinstance(error, GuardError) else type(error).__name__
        raise SystemExit('Telemetry pre-start check failed: ' + detail)
