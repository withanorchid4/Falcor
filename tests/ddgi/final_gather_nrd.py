"""NRD on/off, static noise, motion reuse, native specular, and GPU timestamps."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/final-gather-nrd'
OUT.mkdir(exist_ok=True)
for stale in ['complete.json','failure.txt']:(OUT/stale).unlink(missing_ok=True)
record={"resolution":[480,270],"warmup":2048,"nrd":"RelaxDiffuseSpecular","static_history_frames":128,"static_capture_frames":32}
def save(): (OUT/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
    for _ in range(n):renderFrame()
def capture(tag):
    m.frameCapture.baseFilename=tag;m.frameCapture.capture()
def timing(tag):
    m.profiler.enabled=True;frames(16);m.profiler.start_capture();frames(128)
    (OUT/(tag+'-timing.json')).write_text(json.dumps(m.profiler.end_capture(),indent=2));m.profiler.enabled=False
try:
    os.environ['CORNELL_RTXGI_CONFIG']=str(ROOT/'build/final-gather-comparison/scene.json')
    g=runpy.run_path(str(ROOT/'scripts/RTXGIDDGIFinalGather.py'))['RTXGIDDGIFinalGather']
    for c in ['DDGI.color','DDGI.indirect','DDGI.gatherDiffuse','DDGI.gatherSpecular','DDGI.unfilteredColor',
        'DDGI.diffuseRadianceHitDist','DDGI.specularRadianceHitDist','DDGI.diffuseReflectance','DDGI.specularReflectance',
        'Compose.output','Visibility.normW']:g.markOutput(c)
    dd=g.getPass('DDGI');nrd=g.getPass('Denoiser')
    dd.set_properties({'gridCounts':uint3(9,9,9),'raysPerProbe':256,'autoBounds':False,
        'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
        'normalBias':.02/.3,'viewBias':.1/.3,'finalGather':False})
    nrd.set_properties({'enabled':False})
    m.addGraph(g);m.loadScene(str(ROOT/'tests/ddgi/final_gather_lambert.pyscene'))
    m.clock.pause();m.scene.camera.animated=False
    m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
    record['stage']='warm probes';save();frames(2048)
    dd.set_properties({'updateEnabled':False,'finalGather':True})
    frames(1);capture('off')
    nrd.set_properties({'enabled':True})
    record['stage']='static NRD';save()
    for i in range(1,161):
        renderFrame()
        if i in [1,8,32,64,128] or i>128:capture('static-'+str(i))
    record['static_resets']=nrd.resetHistoryCount
    # No accumulated image average here: NRD alone uses current and previous frames.
    for i in range(8):
        x=.1+.04*i;m.scene.camera.position=float3(x,1.,4.);m.scene.camera.target=float3(x,1.,0.)
        frames(1);capture('motion-'+str(i))
    record['motion_resets']=nrd.resetHistoryCount-record['static_resets']
    nrd.set_properties({'enabled':False});frames(1);capture('off-after-motion')
    count=nrd.resetHistoryCount
    nrd.set_properties({'enabled':True});frames(1);capture('on-after-toggle')
    record['toggle_reset_count']=nrd.resetHistoryCount-count
    assert record['toggle_reset_count']>=1
    dd.set_properties({'finalGather':False});frames(1);capture('legacy')
    dd.set_properties({'finalGather':True,'updateEnabled':True})
    for enabled in [False,True]:
        nrd.set_properties({'enabled':enabled});frames(32);timing('on' if enabled else 'off')
    record['lambert_stats']=dict(dd.stats)
    # Native StandardMaterial exercises the specular signal and demodulation.
    m.loadScene(str(ROOT/'scripts/scenes/CornellRTXGI.pyscene'))
    record['stage']='native materials';save();frames(512)
    dd.set_properties({'updateEnabled':False});frames(128);capture('native-on')
    nrd.set_properties({'enabled':False});frames(1);capture('native-off')
    record['native_stats']=dict(dd.stats)
    record['stage']='complete';save();(OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:
    (OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
