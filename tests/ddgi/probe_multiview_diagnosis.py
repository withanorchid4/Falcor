from falcor import *
from pathlib import Path
import runpy,json,traceback,ctypes
R=Path(__file__).resolve().parents[2];O=R/'build/probe-multiview-diagnosis-routed';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True);results={'runs':[]}
nv=ctypes.WinDLL('nvml.dll');nv.nvmlInit_v2();nvDevice=ctypes.c_void_p();nv.nvmlDeviceGetHandleByIndex_v2(0,ctypes.byref(nvDevice))
def clocks():
 values={}
 for name,kind in [('graphics',0),('sm',1),('memory',2)]:
  value=ctypes.c_uint();nv.nvmlDeviceGetClockInfo(nvDevice,kind,ctypes.byref(value));values[name]=value.value
 return values

def save(stage):(O/'progress.json').write_text(json.dumps({'stage':stage,**results},indent=2))
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi');p=g.getPass('DDGI')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 p.set_properties({'batchProbeUpdates':False,'tetrahedralInterpolation':False,'useRTXDI':False})
 g.updatePass('Visibility',{'adjustShadingNormals':True});g.updatePass('Accumulate',{'enabled':False,'autoReset':False})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 save('warm ray field')
 for _ in range(512):renderFrame()
 p.set_properties({'captureOnly':True});p.set_properties({'rasterProbeUpdate':True,'batchProbeUpdates':True,'wrapProbeBatches':True,'probesPerFrame':32,'probeCubemapSize':32,'optimizedProbeCapture':True,'probeCaptureDiagnosticRestore':True})
 validation=[]
 p.set_properties({'probeCaptureDiagnosticRestore':False})
 for across in [False,True]:
  offsets=list(range(0,10648,32)) if not across else [0,5000,10000]
  for offset in offsets:
   p.set_properties({'probeCapturePipelineStats':False,'probeCaptureTestOffset':offset,'probesPerFrame':min(32,10648-offset),'validateCapture':True,'optimizedProbeCapture':False,'multiviewProbeCapture':False,'multiviewAcrossProbes':across})
   for _ in range(2):renderFrame()
   p.set_properties({'optimizedProbeCapture':True,'multiviewProbeCapture':True})
   for _ in range(2):renderFrame()
   v=dict(p.capture_stats);validation.append({'across':across,'offset':offset,'stats':v})
   assert v['missingCapturePixels']==0 and v['extraCapturePixels']==0 and v['captureNonFinite']==0,v
   if offset%1024==0:save('validate '+str((across,offset)))
 (O/'validation.json').write_text(json.dumps(validation,indent=2))
 p.set_properties({'probeCaptureDiagnosticRestore':True,'validateCapture':False,'probesPerFrame':32,'multiviewAcrossProbes':False})
 for offset in [0,5000,10000]:
  for mode,divisor in [(0,1),(1,1),(2,1),(3,1),(4,1),(5,1),(3,2),(3,4),(3,0)]:
   for repeat,mv in enumerate([False,True,True,False]):
    save('measure '+str((offset,mode,divisor,repeat)))
    p.set_properties({'probeCapturePipelineStats':True,'probeCaptureDiagnosticMode':mode,'probeCaptureTriangleDivisor':divisor,'probeCaptureTestOffset':offset,'multiviewProbeCapture':mv,'multiviewAcrossProbes':False})
    for attempt in range(4):
     for _ in range(32 if attempt==0 else 128):renderFrame()
     _=dict(p.capture_pipeline_stats)  # Drain the GPU before the timed interval.
     beforeClock=clocks()
     if beforeClock['graphics']>=2500:break
    p.set_properties({'probeCapturePipelineStats':False})
    m.profiler.enabled=True;m.profiler.start_capture()
    for frame in range(128):renderFrame()
    timing=m.profiler.end_capture();m.profiler.enabled=False
    filename='timing-%s-%s-%s-%s.json'%(offset,mode,divisor,repeat);(O/filename).write_text(json.dumps(timing))
    p.set_properties({'probeCapturePipelineStats':True})
    for _ in range(2):renderFrame()
    counters=dict(p.capture_pipeline_stats)
    gpuClocks=[beforeClock,clocks()]
    results['runs'].append({'offset':offset,'mode':mode,'triangleDivisor':divisor,'clocks':gpuClocks,'multiview':mv,'repeat':repeat,'file':filename,'pipeline':counters,'capture':dict(p.capture_stats)})
 p.set_properties({'probeCapturePipelineStats':False,'probeCaptureDiagnosticMode':0,'probeCaptureTriangleDivisor':1})
 # Recheck the real 1024-probe live-update case after the diagnostic-only tests.
 p.set_properties({'probeCaptureDiagnosticRestore':False,'probeCaptureTriangleDivisor':1,'probeCaptureDiagnosticMode':0,'probeCapturePipelineStats':False,'probesPerFrame':1024})
 p.set_properties({'captureOnly':False})
 g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
 normal=[]
 for repeat,mv in enumerate([False,True,True,False]):
  save('live 1024 '+str(repeat));p.set_properties({'multiviewProbeCapture':mv,'probeCaptureTestOffset':0})
  for _ in range(32):renderFrame()
  m.profiler.enabled=True;m.profiler.start_capture()
  for _ in range(128):renderFrame()
  timing=m.profiler.end_capture();m.profiler.enabled=False
  filename='live-1024-'+str(repeat)+'.json';(O/filename).write_text(json.dumps(timing))
  normal.append({'multiview':mv,'file':filename,'stats':dict(p.stats)})
 results['normal1024']=normal
 (O/'complete.json').write_text(json.dumps(results,indent=2));save('complete')
except:(O/'failure.txt').write_text(traceback.format_exc());save('failed')
exit()
