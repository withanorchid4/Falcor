"""Full-resolution control for the half-resolution experiment; unchanged lighting/reference."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/full-gather-nrd-comparison';OUT.mkdir(exist_ok=True)
for stale in ['complete.json','failure.txt']:(OUT/stale).unlink(missing_ok=True)
def frames(n):
    for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
    os.environ['CORNELL_RTXGI_CONFIG']=str(ROOT/'build/three-way-half-gather/scene.json')
    g=runpy.run_path(str(ROOT/'scripts/RTXGIDDGIFinalGather.py'))['RTXGIDDGIFinalGather']
    g.removeEdge('Accumulate.output','Display.src');g.removeEdge('Compose.output','Accumulate.input')
    g.removePass('Accumulate');g.addEdge('Compose.output','Display.src')
    dd=g.getPass('DDGI');dd.set_properties({'halfResolutionGather':False,
        'gridCounts':uint3(9,9,9),'raysPerProbe':256,'autoBounds':False,
        'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
        'normalBias':.02/.3,'viewBias':.1/.3,'hysteresis':.97,'useWRC':False})
    for c in ['Compose.output','Visibility.normW']:g.markOutput(c)
    m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
    m.clock.pause();m.scene.camera.animated=False
    m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
    frames(2048);g.getPass('Denoiser').set_properties({'resetHistory':True})
    frames(256);capture('full-warm-256');frames(256);capture('full-warm-512')
    for i in range(64):frames(1);capture('full-'+str(i))
    g.markOutput('DDGI.diffuseRadianceHitDist');frames(1);capture('full-dimensions')
    g.unmarkOutput('DDGI.diffuseRadianceHitDist')
    frames(128);m.profiler.enabled=True;frames(32);m.profiler.start_capture();frames(256)
    (OUT/'full-timing.json').write_text(json.dumps(m.profiler.end_capture(),indent=2));m.profiler.enabled=False
    (OUT/'complete.json').write_text(json.dumps({'resolution':[480,270],'gather_resolution':[480,270],
        'probe_warmup':2048,'nrd_warmup':512,'capture_frames':64,'stats':dict(dd.stats)},indent=2))
except Exception:(OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
