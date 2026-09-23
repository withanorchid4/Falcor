"""Headless replay and numerical/visual comparison. Run with a Python containing numpy."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import uuid
import numpy as np
from probe_snapshot import verify, png, write_json

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--overrides',type=Path,help='JSON object of explicit Probe settings to change')
    parser.add_argument('--rebake',action='store_true',help='Bake into the new run directory; never overwrite the baseline')
    parser.add_argument('--executable',type=Path,help='Optional isolated Mogwai runtime for testing')
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    case=args.snapshot.resolve(); data=verify(case)
    overrides=json.loads(args.overrides.read_text(encoding='utf-8-sig')) if args.overrides else {}
    if not isinstance(overrides,dict): raise ValueError('Overrides must be a JSON object.')
    if any(k in overrides for k in ('mode','cacheFile')): raise ValueError('Use --rebake; mode/cacheFile cannot override snapshot isolation.')
    output=case/'runs'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    executable=(args.executable or root/'build/windows-vs2022/bin/Release/Mogwai.exe').resolve()
    env=os.environ.copy()
    env.update(PROBE_SNAPSHOT_CASE=str(case),PROBE_SNAPSHOT_OUTPUT=str(output),
        PROBE_SNAPSHOT_OVERRIDES=json.dumps(overrides),PROBE_SNAPSHOT_REBAKE='1' if args.rebake else '0',
        PROBE_SNAPSHOT_RUNTIME=str(executable.parent),FALCOR_MEDIA_FOLDERS='F:/media')
    command=[str(executable),'--headless','--deferred','--device-type','d3d12',
        '--width',str(data['resolution'][0]),'--height',str(data['resolution'][1]),
        '--script',str(root/'scripts/ReplayProbeSnapshot.py'),'--logfile',str(output/'Mogwai.log')]
    write_json(output/'request.json',{'command':command,'overrides':overrides,'rebake':args.rebake})
    with (output/'console.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=executable.parent,env=env,stdout=log,stderr=subprocess.STDOUT,
            timeout=args.timeout,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:
        failure=output/'failure.txt'
        raise RuntimeError(f'Replay failed: {output}\n'+(failure.read_text(encoding='utf-8') if failure.exists() else 'See console.log'))
    metrics={}
    for name in ('hdr','display'):
        w,h=data['resolution']
        before=np.fromfile(case/'baseline'/(name+'.f32'),dtype='<f4').reshape(h,w,3).astype(np.float64)
        after=np.fromfile(output/(name+'.f32'),dtype='<f4').reshape(h,w,3).astype(np.float64)
        if before.shape!=after.shape or not np.isfinite(after).all(): raise RuntimeError('Invalid replay image dimensions/data')
        diff=after-before
        metrics[name]={'mae':float(np.abs(diff).mean()),'rmse':float(np.sqrt(np.square(diff).mean())),
            'max_abs':float(np.abs(diff).max())}
        if name=='display':
            png(output/'before-after.png',np.concatenate((before,after),axis=1))
            png(output/'difference-x8.png',np.abs(after-before)*8)
    rendered=json.loads((output/'render.json').read_text(encoding='utf-8'))
    metrics['camera_matches']=rendered['camera']==data['camera']
    metrics['same_cache']=rendered['cacheSha256']==data['cacheSha256']
    metrics['selection_before']=data['selection']; metrics['selection_after']=rendered['selection']
    write_json(output/'comparison.json',metrics)
    # Catch modifications during execution as well as before launch.
    verify(case)
    print(json.dumps({'output':str(output),'hdr':metrics['hdr'],'display':metrics['display'],
        'camera_matches':metrics['camera_matches'],'same_cache':metrics['same_cache']},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
