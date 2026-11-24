"""Run sequential before/after GPU A/B/B/A and matched 1080p image comparisons.
Build Release RTXGIDDGI first. Run with host Python, while Mogwai is closed.
The deployed shader copies are restored to current source bytes on exit.
"""
from pathlib import Path
import subprocess as sp,json,hashlib,argparse
R=Path(__file__).resolve().parents[2];O=R/'build/material-normal-fix';O.mkdir(parents=True,exist_ok=True)
S=R/'Source/RenderPasses/RTXGIDDGI';deployed=R/'build/windows-vs2022/bin/Release/shaders/RenderPasses/RTXGIDDGI'
names=['RTXGIDDGI.rt.slang','LumenWorldCacheTrace.slang','SharcTrace.slang']
fixed={n:(S/n).read_bytes() for n in names}
parser=argparse.ArgumentParser()
parser.add_argument('--generate-reference',action='store_true',help='Also accumulate a fresh 65536 spp PT Reference.')
args=parser.parse_args()
base='311c0e88'
before={n:sp.check_output(['git','show',base+':Source/RenderPasses/RTXGIDDGI/'+n],cwd=R) for n in names}
plan=[{'tag':'before-0','before':True,'quality':True},{'tag':'after-0','quality':True},{'tag':'after-1','modes':['ddgi','sharc','worldcache']},{'tag':'before-1','before':True,'modes':['ddgi','sharc','worldcache']},{'tag':'pt-current','modes':['pt'],'warmup':64,'timingFrames':128}]
if args.generate_reference or not (R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr').exists():
 plan[-1].update(quality=True,imageFrames=8192)
(O/'provenance.json').write_text(json.dumps({'baseline':base,'plan':plan,'fixed_source_sha256':{n:hashlib.sha256(b).hexdigest() for n,b in fixed.items()},'resolution':[1920,1080],'PT_reference':'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr','PT_spp':65536},indent=2))
try:
 for case in plan:
  for n,b in (before if case.get('before') else fixed).items():(deployed/n).write_bytes(b)
  (O/'case.json').write_text(json.dumps(case));(O/(case['tag']+'-failure.txt')).unlink(missing_ok=True)
  sp.run([str(R/'build/windows-vs2022/bin/Release/Mogwai.exe'),'--headless','--device-type','d3d12','--script',str(R/'tests/ddgi/material_normal_fix.py'),'--width','1920','--height','1080','--logfile',str(O/(case['tag']+'.log'))],cwd=R/'build/windows-vs2022/bin/Release',check=True,creationflags=sp.CREATE_NO_WINDOW)
  if (O/(case['tag']+'-failure.txt')).exists():raise RuntimeError(case['tag'])
finally:
 for n,b in fixed.items():(deployed/n).write_bytes(b)
 (O/'restored.txt').write_text('Deployed shaders restored to fixed source')
