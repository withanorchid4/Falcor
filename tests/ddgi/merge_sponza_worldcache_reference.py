"""Merge equal-size independent PT continuation blocks and update capture metadata."""
from pathlib import Path
import argparse,json,sys,hashlib
import numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-worldcache-ddgi-1080p-20261119'
sys.path.insert(0,str(R/'build/final-gather-python'));import OpenEXR
p=argparse.ArgumentParser();p.add_argument('--base',type=int,default=16384);args=p.parse_args();base=args.base
info=json.loads((D/'complete.json').read_text());assert info['pt_sequence_spp']==base
ext=json.loads((D/f'pt-extension-{base}-complete.json').read_text())
assert not (D/'pt-extension-failure.txt').exists()
for seq in ['a','b']:
 def read(tag):
  a=OpenEXR.File(str(D/(tag+'.Accumulate.output.0.exr'))).channels()['RGB'].pixels
  assert a.shape==(1080,1920,3) and np.isfinite(a).all();return a
 previous=read(f'pt-{seq}-{base}');block=read(f'pt-{seq}-block-{base}-to-{2*base}')
 merged=np.ascontiguousarray((previous.astype(np.float64)+block)*.5,dtype=np.float32)
 OpenEXR.File({}, {'RGB':merged}).write(str(D/f'pt-{seq}-{2*base}.Accumulate.output.0.exr'))
(D/f'capture-before-pt-extension-{base}.json').write_text(json.dumps(info,indent=2))
info.setdefault('initial_pt_total_spp',info['pt_total_spp']);info['pt_sequence_spp']=base*2;info['pt_total_spp']=base*4
info.setdefault('pt_extensions',[]).append(ext);info['elapsed_seconds']+=ext['elapsed']
info['completion_reason']='Additional independent PT continuation samples added because the previous reference doubling changed WorldCache HDR-FLIP by more than 1%.'
for f in ['tests/ddgi/extend_sponza_worldcache_reference.py','tests/ddgi/merge_sponza_worldcache_reference.py']:
 info['source_hashes'][f]=hashlib.sha256((R/f).read_bytes()).hexdigest()
(D/'complete.json').write_text(json.dumps(info,indent=2));print('PT reference total spp:',info['pt_total_spp'])
