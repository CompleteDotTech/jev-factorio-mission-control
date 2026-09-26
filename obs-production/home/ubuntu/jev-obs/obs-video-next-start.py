#!/usr/bin/env python3
"""Persist 60 FPS immediately before OBS starts; never interrupt active outputs."""
import argparse
import configparser
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile

ROOT = Path('/home/ubuntu/jev-obs')
PROFILE = Path('/home/ubuntu/.config/obs-studio/basic/profiles/STS2/basic.ini')
BACKUPS = ROOT / 'video-next-start-backup'


def desired_profile(raw):
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.optionxform = str
    config.read_string(raw.decode('utf-8-sig'))
    if not config.has_section('Video'):
        raise ValueError('Missing Video section')
    settings = {'FPSType': '0', 'FPSCommon': '60', 'FPSInt': '60',
                'FPSNum': '60', 'FPSDen': '1'}
    changed = any(config.get('Video', key, fallback=None) != value
                  for key, value in settings.items())
    for key, value in settings.items():
        config.set('Video', key, value)
    out = io.StringIO()
    config.write(out, space_around_delimiters=False)
    return out.getvalue().encode(), changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('guards', ROOT / 'obs-telemetry-next-start.py')
    guards = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guards)
    guards.require(os.geteuid() == 1000, 'Run as the OBS desktop user')
    guards.check_vm_identity()
    before = guards.checked_file(PROFILE)
    raw = PROFILE.read_bytes()
    updated, changed = desired_profile(raw)
    running = guards.obs_running()
    if not args.apply:
        print(json.dumps({'target_fps': 60, 'change_needed': changed,
                          'obs_running': running, 'apply_allowed_now': not running}))
        return
    guards.require(not running, 'OBS is running; profile was not changed')
    if not changed:
        print('60 FPS already configured')
        return
    os.umask(0o077)
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    info = BACKUPS.lstat()
    guards.require(not BACKUPS.is_symlink() and BACKUPS.is_dir()
                   and info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0,
                   'Unsafe backup directory')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    with (BACKUPS / ('basic.' + stamp + '.ini')).open('xb') as backup:
        backup.write(raw)
        backup.flush()
        os.fsync(backup.fileno())
    fd, name = tempfile.mkstemp(prefix='.basic-fps-', dir=PROFILE.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), before.st_mode & 0o777)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        current = guards.checked_file(PROFILE)
        guards.require((current.st_ino, current.st_size, current.st_mtime_ns)
                       == (before.st_ino, before.st_size, before.st_mtime_ns)
                       and PROFILE.read_bytes() == raw,
                       'Profile changed during preparation')
        guards.require(not guards.obs_running(), 'OBS started during preparation')
        os.replace(temporary, PROFILE)
        guards.require(PROFILE.read_bytes() == updated, 'Profile readback mismatch')
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({'configured_fps': 60, 'applies_on_this_start': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Video pre-start check failed: ' + type(error).__name__)
