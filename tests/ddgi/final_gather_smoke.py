from falcor import *
from pathlib import Path
import runpy, traceback, json
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/final-gather-smoke'
OUT.mkdir(exist_ok=True)
try:
    g=runpy.run_path(str(ROOT/'scripts/RTXGIDDGIFinalGather.py'))['RTXGIDDGIFinalGather']
    m.addGraph(g)
    m.loadScene(str(ROOT/'scripts/scenes/CornellRTXGI.pyscene'))
    m.clock.pause()
    for _ in range(8): renderFrame()
    m.frameCapture.outputDir=str(OUT)
    m.frameCapture.baseFilename='smoke'
    m.frameCapture.capture()
    (OUT/'success.json').write_text(json.dumps(dict(g.getPass('DDGI').stats)))
except Exception:
    (OUT/'failure.txt').write_text(traceback.format_exc())
finally:
    exit()
