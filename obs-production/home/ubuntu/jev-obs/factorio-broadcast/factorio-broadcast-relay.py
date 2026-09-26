#!/usr/bin/env python3
"""Forward the selected GPU-encoded Factorio feed without decoding or encoding."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path('/home/ubuntu/jev-obs/factorio-broadcast')
MACHINE = 'c6c7bbf1c2f89700340c9afc707a01be67185bd744fcde7a3cd78aceae438076'
TARGETS = {
    'dev': ('564e3c76-b917-451f-9fe0-4e7a30838328', '192.168.124.92', 24022),
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def read_private(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_mode & 0o077 == 0, 'Invalid private configuration permissions')
    return json.loads(path.read_text())


def validate(config):
    target = config.get('target')
    require(target in TARGETS, 'Unknown feed target')
    uuid, host, port = TARGETS[target]
    require(config.get('vm_uuid') == uuid, 'Feed VM identity mismatch')
    source = urlsplit(config['input'])
    query = parse_qs(source.query, strict_parsing=True)
    require(config.get('input_format') == 'mpegts', 'Unexpected private media format')
    require(source.scheme == 'srt' and source.hostname == host and source.port == port
            and not source.username and source.path == '', 'Unexpected feed endpoint')
    require(query.get('mode') == ['listener'] and query.get('pbkeylen') in
            (['16'], ['24'], ['32']) and len(query.get('passphrase', [])) == 1
            and 10 <= len(query['passphrase'][0]) <= 79, 'Invalid encrypted listener')
    output = urlsplit(config['output'])
    require(output.scheme == 'rtmp' and output.hostname ==
            'ingest.global-contribute.live-video.net' and output.port is None
            and output.path.startswith('/app/') and len(output.path) > 20
            and not output.username and not output.query and not output.fragment,
            'Unexpected public ingest endpoint')
    require(config.get('authorized') is True, 'Broadcast activation is not recorded')


def command(config):
    return ['/usr/bin/ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error',
            '-stats_period', '2', '-progress', 'pipe:1', '-thread_queue_size', '1024',
            '-rw_timeout', '15000000', '-f', 'mpegts', '-i', config['input'],
            '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-c:a', 'copy',
            '-bsf:a', 'aac_adtstoasc', '-flvflags', 'no_duration_filesize',
            '-f', 'flv', config['output']]


def write_status(value):
    value['updated_epoch'] = time.time()
    temporary = ROOT / 'status.json.tmp'
    temporary.write_text(json.dumps(value))
    temporary.replace(ROOT / 'status.json')


def obs_running():
    for path in Path('/proc').glob('[0-9]*/comm'):
        try:
            if path.stat().st_uid == os.getuid() and path.read_text().strip() == 'obs':
                return True
        except FileNotFoundError:
            pass
    return False


def run(config):
    require(not obs_running(), 'Legacy OBS must be stopped before relay activation')
    lock = (ROOT / 'relay.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # FFmpeg can put private URLs in errors; keep stderr out of the journal.
    child = subprocess.Popen(command(config), stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    began = time.time()
    status = {'state': 'connecting', 'target': config['target'], 'vm_uuid': config['vm_uuid'],
              'started_epoch': began, 'pid': child.pid, 'video_mode': 'copy',
              'audio_mode': 'copy', 'audio_track_required': True}
    write_status(status)
    last_progress = time.monotonic()
    last_metrics = None
    buffer = b''
    values = {}
    failure = None
    try:
        while not stopping:
            if child.poll() is not None:
                raise RuntimeError('Media relay exited')
            for key, events in selector.select(1):
                data = os.read(key.fd, 8192)
                if not data:
                    continue
                buffer += data
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    name, separator, value = line.decode('ascii', 'replace').partition('=')
                    if name in ('frame', 'fps', 'total_size', 'out_time_us', 'speed'):
                        values[name] = value.strip()
                    if name == 'progress':
                        metrics = tuple(values.get(key) for key in
                                        ('frame', 'out_time_us', 'total_size'))
                        if metrics != last_metrics and any(
                                value not in (None, 'N/A') for value in metrics):
                            last_progress = time.monotonic()
                        last_metrics = metrics
                        status.update(state='forwarding', progress=dict(values))
                        write_status(status)
            if time.monotonic() - last_progress > 45:
                raise RuntimeError('Media relay stopped advancing')
    except Exception as error:
        failure = type(error).__name__
        raise
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        selector.close()
        status.update(state='failed' if failure else 'stopped', exit_code=child.returncode,
                      failure=failure)
        write_status(status)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    require(os.getuid() == 1000, 'Run as the OBS guest user')
    require(hashlib.sha256(Path('/etc/machine-id').read_text().strip().encode()).hexdigest()
            == MACHINE, 'Wrong relay VM')
    config = read_private(ROOT / 'active.json')
    validate(config)
    if args.check:
        print(json.dumps({'valid': True, 'target': config['target'],
                          'legacy_obs_running': obs_running(), 'transcode': False,
                          'audio_track_required': True,
                          'audio_codec': 'AAC stream copied to Twitch'}))
        return
    run(config)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Exception text may contain a private endpoint. Do not include it.
        print('Factorio relay stopped: ' + type(error).__name__, flush=True)
        raise SystemExit(1)
