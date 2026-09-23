"""Create a Room issue snapshot with non-default camera and runtime parameters."""
from falcor import *
from pathlib import Path
import sys, json, traceback
sys.path.insert(0,'F:/scripts')
from probe_snapshot import save_snapshot
out=Path('F:/build/probe-snapshot-validation'); out.mkdir(parents=True,exist_ok=True)
try:
    g=RenderGraph('TraditionalProbeGI')
    g.addPass(createPass('VBufferRT',{'samplePattern':'Center'}),'Visibility')
    g.addPass(createPass('TraditionalProbeGI',{'mode':'manual',
        'cacheFile':'F:/build/probe-angular-room-validation/room.shprobe',
        'distanceBakeMode':'angular','distanceResolution':14,'distanceRaysPerProbe':2048,
        'normalBias':.075,'viewBias':.12,'varianceBase':2e-6}),'Probes')
    g.addPass(createPass('ToneMapper',{'autoExposure':False,'exposureCompensation':.5}),'Display')
    g.addEdge('Visibility.vbuffer','Probes.vbuffer'); g.addEdge('Visibility.viewW','Probes.viewW')
    g.addEdge('Probes.color','Display.src'); g.markOutput('Display.dst'); m.addGraph(g); m.clock.pause()
    m.loadScene('F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene')
    m.scene.camera.position=float3(4.3,1.3,-2.5); m.scene.camera.target=float3(4.8,1.,-.02)
    m.scene.camera.animated=False
    m.scene.camera.up=float3(0,1,0); m.scene.camera.focalLength=31.; m.scene.camera.frameHeight=23.8
    m.scene.envMap.intensity=17.
    renderFrame(); renderFrame(); p=g.getPass('Probes'); p.loadCache(); renderFrame(); assert p.ready,p.status
    p.inspectSurfacePoint(float3(4.5,.6,-.003),float3(0,0,-1)); renderFrame()
    before=dict(p.settings); old_debug=p.debugInfo['enabled']
    case=save_snapshot(m,renderFrame,out/'cases')
    assert p.settings==before and p.debugInfo['enabled']==old_debug
    (out/'case.txt').write_text(str(case),encoding='utf-8')
    print('Snapshot saved:',case); exit()
except Exception:
    (out/'capture-failure.txt').write_text(traceback.format_exc(),encoding='utf-8'); exit(1)
