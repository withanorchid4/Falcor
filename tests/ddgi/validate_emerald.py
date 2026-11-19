"""Asset-dependent Emerald smoke render, not a convergence/quality benchmark.
Run Mogwai --headless --width 960 --height 540 --script <this file>.
"""
from falcor import *
from pathlib import Path
import os,runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/emerald-integration';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
(O/'complete.json').unlink(missing_ok=True)
try:
 os.environ['FALCOR_START_SCENE']='EmeraldSquareLambert'
 os.environ['FALCOR_START_RENDERER']='DDGI'
 graphs=runpy.run_path(str(R/'scripts/GIPreview.py'))['graphs']
 results={}
 m.clock.pause()
 m.frameCapture.outputDir=str(O)
 for scene in ('EmeraldSquare','EmeraldSquareLambert'):
  m.loadScene(str(R/'scripts/scenes'/ (scene+'.pyscene')))
  m.scene.animated=False
  results[scene]={'stats':dict(m.scene.stats),'bounds':str(m.scene.bounds)}
  modes=('DDGI','HalfFG','WorldCache','PT') if scene.endswith('Lambert') else ('DDGI','PT')
  for mode in modes:
   g=graphs['PTReference' if mode=='PT' else 'LumenWorldCache' if mode=='WorldCache' else 'RTXGIDDGI']
   if mode in ('DDGI','HalfFG'):g.getPass('DDGI').set_properties({'finalGather':mode=='HalfFG','halfResolutionGather':True})
   m.setActiveGraph(g)
   for _ in range(64 if mode=='PT' else 192):renderFrame()
   m.frameCapture.baseFilename=scene+'-'+mode;m.frameCapture.capture()
   if mode!='PT':
    stats=dict(g.getPass('WorldCache' if mode=='WorldCache' else 'DDGI').stats)
    assert stats.get('finite', True) and stats.get('nonFiniteTexels', 0)==0, stats
    results[scene][mode]=stats
   (O/'progress.json').write_text(json.dumps(results,indent=2),encoding='utf8')
 (O/'complete.json').write_text(json.dumps(results,indent=2),encoding='utf8')
except: (O/'failure.txt').write_text(traceback.format_exc(),encoding='utf8')
exit()
