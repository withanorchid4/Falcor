"""Host-only rejection checks; mutates only disposable copies of a snapshot."""
from pathlib import Path
import json, shutil, sys, tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from probe_snapshot import verify

root=Path(__file__).resolve().parents[2]/'build/probe-snapshot-validation'
case=root/'cases'/Path((root/'case.txt').read_text(encoding='utf-8').strip()).name
data=verify(case)
checks=[]
with tempfile.TemporaryDirectory(dir=root) as temp:
    temp=Path(temp)
    assert temp.resolve().is_relative_to(root.resolve())
    for name in ('snapshot.json','graph.py','probes.shprobe'): shutil.copyfile(case/name,temp/name)
    for name in ('graph.py','probes.shprobe'):
        with (temp/name).open('ab') as stream: stream.write(b'changed')
        try: verify(temp)
        except RuntimeError as e: assert 'Snapshot modified' in str(e)
        else: raise AssertionError('Modified snapshot accepted: '+name)
        checks.append(name+' corruption rejected')
        shutil.copyfile(case/name,temp/name)
    bad=dict(data); bad['assets']=dict(data['assets']); bad['assets'][next(iter(bad['assets']))]='bad-hash'
    (temp/'snapshot.json').write_text(json.dumps(bad),encoding='utf-8')
    try: verify(temp)
    except RuntimeError as e: assert 'Scene asset changed' in str(e)
    else: raise AssertionError('Changed scene identity accepted')
    checks.append('changed asset rejected')
assert verify(case)['cacheSha256']==data['cacheSha256']
(root/'integrity.json').write_text(json.dumps({'checks':checks,'source_intact':True},indent=2),encoding='utf-8')
print('Snapshot integrity checks passed')
