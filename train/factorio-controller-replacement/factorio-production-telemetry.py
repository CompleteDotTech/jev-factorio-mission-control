#!/usr/bin/env python3
"""Mirror the selected production controller's public telemetry to OBS, read-only."""
import importlib.util
import json
import os
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parent
SESSION = os.environ.get('JEV_FACTORIO_SESSION_ID', '3562a7a347b54be5823716bd06be5af1')
if not re.fullmatch(r'[0-9a-f]{32}', SESSION):
    raise ValueError('JEV_FACTORIO_SESSION_ID must contain exactly 32 lowercase hexadecimal characters')

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

transport = module('transport', '/home/completetrain/factorio-controller-replacement/broadcast-relay-20260923/deploy-factorio-broadcast-relay.py')
dashboard = module('dashboard', '/home/completetrain/factorio-native-overlay/dashboard.py')

def sample():
    transport.DOMAIN = 'herdr-vm'
    code = f'''from pathlib import Path
import json
pointer=json.loads(Path('/home/agent/.local/state/jev-factorio/active-replacement-production.json').read_text())
assert pointer['target']=='production' and pointer['bootstrap_ready'] is True
assert pointer['native_session_id']=={SESSION!r}
campaign=Path(pointer['campaign'])
assert campaign.parent==Path('/workspace/jev-factorio-agent/replacement-controller-f89407d/runs')
assert campaign.name.startswith('controller-production-')
args=pointer['supervisor_args']
assert args.count('--state-dir')==1
p=Path(args[args.index('--state-dir')+1]).resolve()
assert p.is_relative_to(campaign.resolve()) and p!=campaign.resolve()
with (p/'gameplay.jsonl').open('rb') as f:
 f.seek(max(0,(p/'gameplay.jsonl').stat().st_size-524288))
 lines=f.read().split(b'\\n')[:-1]
row=json.loads(lines[-1])
assert (row.get('session_id') or row.get('state',{{}}).get('session_id'))=={SESSION!r}
record={{k:row[k] for k in {dashboard.RECORD_KEYS!r} if k in row}}
for key in ('state','after_state'):
 if isinstance(row.get(key),dict): record[key]={{k:row[key][k] for k in {dashboard.STATE_KEYS!r} if k in row[key]}}
s=json.loads((p/'supervisor.json').read_text())
assert s.get('session_id')=={SESSION!r}
print(json.dumps({{'mtime':(p/'gameplay.jsonl').stat().st_mtime,'record':record,'supervisor':{{k:s[k] for k in ('session_id','phase','cutoff','started_at','attempt','repair_required') if k in s}}}}))
'''
    result, out, _ = transport.guest_exec(['/usr/sbin/runuser', '-u', 'completetrain', '--', 'env', 'XDG_RUNTIME_DIR=/run/user/1000', 'podman', 'exec', 'session-home-complete-tech', 'python3', '-c', code])
    if result:
        raise RuntimeError('Source telemetry unavailable')
    return dashboard.sanitize(json.loads(out))

def publish(data, append):
    transport.DOMAIN = 'obs-production'
    code = f'''from pathlib import Path
import json,os
assert Path('/sys/class/dmi/id/product_uuid').read_text().strip()=='fd83a53b-7bd7-4364-b06c-2bd6abd428bc'
data=json.loads({json.dumps(data)!r})
root=Path('/var/lib/jev-mission-control')
assert root.is_dir()
if {append!r}:
 p=root/'gameplay.jsonl'
 assert p.is_file() and not p.is_symlink()
 with p.open('a') as f: f.write(json.dumps(data['record'])+'\\n')
 os.utime(p,(data['mtime'],data['mtime']))
p=root/'supervisor.json';info=p.stat()
temporary=root/'supervisor.controller-mirror.tmp'
temporary.write_text(json.dumps(data['supervisor']))
os.chmod(temporary,info.st_mode&0o777);os.chown(temporary,info.st_uid,info.st_gid)
temporary.replace(p)
'''
    result, _, _ = transport.guest_exec(['/usr/bin/python3', '-c', code])
    if result:
        raise RuntimeError('OBS telemetry update failed')

def main():
    previous = None
    while True:
        status = {'updated_epoch': time.time(), 'target': 'production'}
        try:
            data = sample()
            record = json.dumps(data['record'], sort_keys=True)
            publish(data, record != previous)
            previous = record
            status.update(state='following', source_epoch=data['mtime'], phase=data['supervisor'].get('phase'))
        except Exception as error:
            status.update(state='unavailable', error_class=type(error).__name__)
        temporary = ROOT / 'status.json.tmp'
        temporary.write_text(json.dumps(status))
        temporary.replace(ROOT / 'status.json')
        time.sleep(3)

if __name__ == '__main__':
    main()
