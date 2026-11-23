from falcor import *
from pathlib import Path
import runpy,json,traceback,time
R=Path(__file__).resolve().parents[2];O=R/'build/probe-raster-smoke';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi');p=g.getPass('DDGI')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 p.set_properties({'rasterProbeUpdate':True,'batchProbeUpdates':True,'probesPerFrame':32,'probeCubemapSize':32})
 g.markOutput('Accumulate.output');m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 t=time.time()
 for _ in range(8):renderFrame()
 m.profiler.enabled=True;m.profiler.start_capture()
 for _ in range(32):renderFrame()
 (O/'timing.json').write_text(json.dumps(m.profiler.end_capture()))
 (O/'complete.json').write_text(json.dumps({'stats':dict(p.stats),'seconds':time.time()-t}))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
