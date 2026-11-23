from falcor import *
from pathlib import Path
import runpy,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/surfel-smoke';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
try:
 g=runpy.run_path(str(R/'scripts/SurfelGI.py'))['SurfelGI']
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause()
 g.markOutput('Accumulate.output');m.frameCapture.outputDir=str(O)
 for _ in range(1024):renderFrame()
 m.frameCapture.baseFilename='surfel';m.frameCapture.capture()
 (O/'complete.txt').write_text(str(dict(g.getPass('Surfel').stats)))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
