from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/probe-raster-toggle';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
try:
 g=runpy.run_path(str(R/'scripts/RTXGIDDGI.py'))['RTXGIDDGI'];p=g.getPass('DDGI')
 p.set_properties({'gridCounts':uint3(2,2,2),'raysPerProbe':64,'enableClassification':False,'enableRelocation':False})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause()
 for _ in range(8):renderFrame()
 assert not p.properties['rasterProbeUpdate']
 for raster,size in [(True,16),(False,32),(True,32),(True,64),(False,32)]:
  p.set_properties({'rasterProbeUpdate':raster,'probeCubemapSize':size});renderFrame()
  assert p.updatedFrames==1
  for _ in range(8):renderFrame()
  assert p.stats['finite']
 (O/'complete.json').write_text(json.dumps({'defaultRay':True,'toggleResetsHistory':True,'resolutions':[16,32,64],'finite':True}))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
