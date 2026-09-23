"""Room-scale angular bake regression; isolated output, no user-cache writes."""
from falcor import *
from pathlib import Path
import json, os, traceback

out=Path('F:/build/probe-angular-room-validation'); out.mkdir(parents=True,exist_ok=True)
cache=out/'room.shprobe'
load_only=os.environ.get('PROBE_ROOM_LOAD')=='1'
try:
    g=RenderGraph('AngularRoomNumerics')
    g.addPass(createPass('VBufferRT',{'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',{'mode':'manual','cacheFile':str(cache),
        'gridCounts':uint3(8,6,8),'samplesPerProbe':2048,'samplesPerFrame':16,'maxBounces':3,
        'distanceBakeMode':'angular','distanceRaysPerProbe':2048,'distanceResolution':14,
        'distanceExponent':50.}),'Probes')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW')
    g.markOutput('Probes.color'); m.addGraph(g); m.clock.pause()
    m.loadScene('F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene')
    renderFrame(); renderFrame(); p=g.getPass('Probes')
    if load_only: p.loadCache()
    else: p.bake()
    for i in range(5000):
        renderFrame()
        if p.ready or not p.baking: break
    result={'ready':p.ready,'status':p.status,'frames':i+1,'SH_samples':p.completedSamples,
        'distance_samples':p.completedDistanceSamples}
    (out/('load.json' if load_only else 'result.json')).write_text(json.dumps(result,indent=2))
    assert p.ready,p.status
    if not load_only:
        m.frameCapture.outputDir=str(out); m.frameCapture.baseFilename='room'; m.frameCapture.capture()
    print('Room angular numerics passed', result); exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc()); exit(1)
