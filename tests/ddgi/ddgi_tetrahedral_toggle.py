from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/ddgi-tetrahedral'
try:
 g=runpy.run_path(str(R/'scripts/RTXGIDDGI.py'))['RTXGIDDGI'];m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause()
 p=g.getPass('DDGI');assert not p.properties['tetrahedralInterpolation']
 for _ in range(16):renderFrame()
 for v in [True,False,True,False]:
  p.set_properties({'tetrahedralInterpolation':v});renderFrame();assert p.properties['tetrahedralInterpolation']==v and p.updatedFrames<=1
  for _ in range(4):renderFrame()
 (O/'toggle-check.json').write_text(json.dumps({'defaultEight':True,'toggleResetPassed':True}))
except:(O/'toggle-failure.txt').write_text(traceback.format_exc())
exit()
