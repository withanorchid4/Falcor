"""Cold-start equal new-FG-ray-budget convergence with a frozen shared probe field."""
from falcor import *
from pathlib import Path
import runpy,os,json,time,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/restir-equal-budget';O.mkdir(exist_ok=True)
for f in ['failure.txt','complete.json']:(O/f).unlink(missing_ok=True)
checkpoints=[2**i for i in range(13)]
record={'resolution':[1920,1080],'probe_warmup':8192,'probe_frozen':True,'full_resolution_integration':False,
 'checkpoints':checkpoints,'trials':3,'seed_offsets':[0,4096,8192],'jitter':True,'runs':{},'started':time.time()}
def progress(stage):
 record['stage']=stage;record['elapsed']=time.time()-record['started'];(O/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(R/'build/highres-1080p-split-rerun/scene.json')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 for trial,offset in enumerate(record['seed_offsets']):
  for name,enabled in [('fg',False),('restir',True)]:
   key=name+'-'+str(trial);progress(key+' setup')
   g=factory('half');g.name='EqualBudget_'+key;setup['configure_graph'](g)
   dd=g.getPass('DDGI');acc=g.getPass('Accumulate')
   dd.set_properties({'finalGather':False,'restirGather':False,'restirFullResolution':False,
     'jitterHalfGather':True,'gatherSpecular':False,'restirHistoryLength':20,'restirSpatialPasses':2,
     'restirSpatialSamples':4,'restirTemporal':True,'restirSpatial':True})
   acc.enabled=False
   g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output')
   if enabled:g.markOutput('DDGI.restirDebug')
   m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'))
   m.clock.pause();m.scene.camera.animated=False
   m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
   progress(key+' probe warmup')
   for stop in [4096,8192]:
    frames(4096)
    if trial==0:capture(name+'-probe-'+str(stop))
   warm_stats=dict(dd.stats)
   assert warm_stats['updatedFrames']==8192 and warm_stats['restirResetCount']==0
   # Freeze the identical converged probe state. Seed padding performs NO FG,
   # NO reservoir updates and NO accumulation, and preserves the probe field.
   dd.set_properties({'updateEnabled':False});frames(offset)
   dd.set_properties({'finalGather':True,'restirGather':enabled})
   acc.enabled=True;acc.reset()
   # These properties invalidate the reservoir before dispatch of measured frame 1.
   # Never call dd.reset(): that would clear the already warmed probes as well.
   progress(key+' cold start')
   for i in range(1,4097):
    renderFrame()
    if i in checkpoints:capture(key+'-'+str(i))
   final_stats=dict(dd.stats)
   assert final_stats['updatedFrames']==8192,'Probe field changed during measurement'
   if enabled:assert final_stats['restirResetCount']==1,'History was not initialized exactly once'
   record['runs'][key]={'warm_stats':warm_stats,'final_stats':final_stats,
     'first_frame_index':8192+offset,'accumulate_reset_before_first_frame':True}
   # Timing is outside the measured sample budget, with diagnostic output removed.
   if enabled:g.unmarkOutput('DDGI.restirDebug')
   g.markOutput('Display.dst');frames(64);m.profiler.enabled=True;frames(16)
   m.profiler.start_capture();frames(256)
   (O/(key+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
   progress(key+' complete');m.removeGraph(g)
 progress('complete');(O/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
