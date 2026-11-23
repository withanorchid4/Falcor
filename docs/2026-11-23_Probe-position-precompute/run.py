from falcor import *
from pathlib import Path
import runpy,json,traceback,hashlib
R=Path('C:/workspace/1116GitFalcor/Falcor');O=R/'build/probe-position-precompute'
result={'runs':[],'validation':[]}
def save(stage):
 (O/'progress.json').write_text(json.dumps({'stage':stage,**result},indent=2))
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi');p=g.getPass('DDGI')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 p.set_properties({'batchProbeUpdates':False,'tetrahedralInterpolation':False,'useRTXDI':False})
 g.updatePass('Visibility',{'adjustShadingNormals':True});g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 save('warm ray field')
 for _ in range(512):renderFrame()
 p.set_properties({'captureOnly':True})
 p.set_properties({'rasterProbeUpdate':True,'batchProbeUpdates':True,'wrapProbeBatches':True,'probesPerFrame':32,'probeCubemapSize':32})
 for offset,count in [(0,32),(5000,32),(10640,32),(10640,8),(1024,17)]:
  p.set_properties({'probeCaptureTestOffset':offset,'probesPerFrame':count,'validateCapture':True,'optimizedProbeCapture':False,'multiviewProbeCapture':False})
  for _ in range(2):renderFrame()
  for mode in ['raster','multiview','across']:
   for pre in [False,True]:
    save('validate '+str((offset,count,mode,pre)))
    p.set_properties({'optimizedProbeCapture':True,'multiviewProbeCapture':mode!='raster','multiviewAcrossProbes':mode=='across','precomputeProbePositions':pre})
    for _ in range(2):renderFrame()
    s=dict(p.capture_stats);result['validation'].append({'offset':offset,'count':count,'mode':mode,'precompute':pre,'stats':s})
    assert s['captureNonFinite']==0,s
 p.set_properties({'validateCapture':False,'probesPerFrame':1024,'probeCaptureTestOffset':0,'captureOnly':False})
 for mode in ['raster','multiview','across']:
  for repeat,pre in enumerate([False,True,True,False]):
   save('measure '+str((mode,repeat,pre)))
   p.set_properties({'optimizedProbeCapture':True,'multiviewProbeCapture':mode!='raster','multiviewAcrossProbes':mode=='across','precomputeProbePositions':pre})
   for _ in range(32):renderFrame()
   m.profiler.enabled=True;m.profiler.start_capture()
   for _ in range(128):renderFrame()
   timing=m.profiler.end_capture();m.profiler.enabled=False
   name='timing-'+mode+'-'+str(repeat)+'.json';(O/name).write_text(json.dumps(timing))
   result['runs'].append({'mode':mode,'precompute':pre,'file':name,'stats':dict(p.stats),'properties':dict(p.properties)})
 (O/'complete.json').write_text(json.dumps(result,indent=2));save('complete')
except:
 (O/'failure.txt').write_text(traceback.format_exc());save('failed')
exit()
