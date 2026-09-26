#!/usr/bin/env python3
"""Install the reviewed Factorio relay on the pinned OBS guest over QGA."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

DOMAIN = 'obs-production'
OBS_UUID = 'fd83a53b-7bd7-4364-b06c-2bd6abd428bc'
DEV_UUID = '564e3c76-b917-451f-9fe0-4e7a30838328'
STAGE = Path('/home/completetrain/factorio-controller-replacement/broadcast-relay-20260923')
SCRIPT = STAGE / 'factorio-broadcast-relay.py'
UNIT = STAGE / 'factorio-broadcast-relay.service'


def qga(payload):
    result = subprocess.check_output([
        'virsh', '-c', 'qemu:///system', 'qemu-agent-command', DOMAIN,
        json.dumps(payload),
    ], text=True, timeout=20)
    return json.loads(result)['return']


def guest_exec(argv, timeout=30):
    result = qga({'execute': 'guest-exec', 'arguments': {
        'path': argv[0], 'arg': argv[1:], 'capture-output': True,
    }})
    pid = result['pid']
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = qga({'execute': 'guest-exec-status', 'arguments': {'pid': pid}})
        if status.get('exited'):
            decode = lambda key: base64.b64decode(status.get(key, '')).decode(
                'utf-8', 'replace')
            return status.get('exitcode'), decode('out-data'), decode('err-data')
        time.sleep(0.25)
    raise TimeoutError('OBS guest command timed out')


def guest_write(path, data):
    handle = qga({'execute': 'guest-file-open', 'arguments': {
        'path': str(path), 'mode': 'w',
    }})
    try:
        for offset in range(0, len(data), 4096):
            chunk = data[offset:offset + 4096]
            qga({'execute': 'guest-file-write', 'arguments': {
                'handle': handle,
                'buf-b64': base64.b64encode(chunk).decode('ascii'),
                'count': len(chunk),
            }})
    finally:
        qga({'execute': 'guest-file-close', 'arguments': {'handle': handle}})


def main():
    script, unit = SCRIPT.read_bytes(), UNIT.read_bytes()
    script_hash = hashlib.sha256(script).hexdigest()
    observed_uuid = guest_exec(['/usr/bin/cat', '/sys/class/dmi/id/product_uuid'])[1].strip()
    if observed_uuid != OBS_UUID:
        raise RuntimeError('QGA reached an unexpected OBS VM')

    token = uuid.uuid4().hex
    staged_script = f'/tmp/factorio-broadcast-relay-{token}.py'
    staged_unit = f'/tmp/factorio-broadcast-relay-{token}.service'
    guest_write(staged_script, script)
    guest_write(staged_unit, unit)
    install = f'''from pathlib import Path
import hashlib,json,os
root=Path('/home/ubuntu/jev-obs/factorio-broadcast')
assert not root.exists()
root.mkdir(mode=0o700)
media=json.loads(Path('/home/ubuntu/jev-obs/factorio-b-media.json').read_text())
profile=json.loads(Path('/home/ubuntu/.config/obs-studio/basic/profiles/STS2/service.json').read_text())
settings=profile.get('settings',{{}})
assert media.get('input_format')=='mpegts' and media['input'].startswith('srt://192.168.124.92:24022?')
assert settings.get('service')=='Twitch' and len(settings.get('key',''))>20
cfg={{'authorized':True,'target':'dev','vm_uuid':{DEV_UUID!r},'input':media['input'],'input_format':'mpegts','output':'rtmp://ingest.global-contribute.live-video.net/app/'+settings['key']}}
p=root/'active.json'; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: json.dump(cfg,f); f.write('\\n'); f.flush(); os.fsync(f.fileno())
app=root/'factorio-broadcast-relay.py'; app.write_bytes(Path({staged_script!r}).read_bytes()); app.chmod(0o700)
unit=Path('/home/ubuntu/.config/systemd/user/factorio-broadcast-relay.service'); unit.parent.mkdir(parents=True,exist_ok=True)
unit.write_bytes(Path({staged_unit!r}).read_bytes()); unit.chmod(0o644)
print(json.dumps({{'installed':True,'config_mode':oct(p.stat().st_mode&0o777),'relay_mode':oct(app.stat().st_mode&0o777),'script_sha256':hashlib.sha256(app.read_bytes()).hexdigest(),'input_format':'mpegts','target':'dev','audio_track_required':True,'output_scheme':'rtmp','ingest_host':'ingest.global-contribute.live-video.net'}}))
'''
    code, stdout, stderr = guest_exec(['/usr/sbin/runuser', '-u', 'ubuntu', '--',
                                       '/usr/bin/python3', '-c', install])
    if code:
        raise RuntimeError('OBS relay installation failed: ' + stderr[:300])
    result = guest_exec(['/usr/sbin/runuser', '-u', 'ubuntu', '--',
                         '/usr/bin/python3',
                         '/home/ubuntu/jev-obs/factorio-broadcast/factorio-broadcast-relay.py',
                         '--check'])
    if result[0]:
        raise RuntimeError('OBS relay configuration check failed: ' + result[2][:300])
    print(json.dumps({'obs_uuid': observed_uuid, 'installed': json.loads(stdout),
                      'configuration_check': json.loads(result[1]),
                      'local_script_sha256': script_hash}, indent=2))


if __name__ == '__main__':
    main()
