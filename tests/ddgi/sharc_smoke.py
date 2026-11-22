from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/sharc-smoke';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
try:
 g=runpy.run_path(str(R/'scripts/SHaRC.py'))['SHaRC']
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause()
 assert not m.scene.getLight('Atrium Point').active
 assert m.scene.getLight('Atrium Sun').active
 g.markOutput('Accumulate.output');m.frameCapture.outputDir=str(O)
 for i in range(128):renderFrame()
 p=g.getPass('WorldCache');stats=dict(p.stats)
 assert stats['sharcHits']>0 and stats['sharcOccupied']>0 and stats['sharcNonFinite']==0
 m.frameCapture.baseFilename='sharc';m.frameCapture.capture()
 (O/'result.json').write_text(json.dumps(stats,indent=2))
 # Verify backend switches reset resources/program permutations and keep outputs finite.
 for enabled in [False,True]:
  p.set_properties({'sharc':enabled})
  for _ in range(8):renderFrame()
  assert p.stats['finite'] and p.stats['sharc']==enabled
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
