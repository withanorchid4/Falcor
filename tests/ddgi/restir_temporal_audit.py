"""Corrected ReSTIR vs cosine FG: independent PT, cold histories, frozen probes."""
from falcor import *
from pathlib import Path
import runpy,os,json,time,traceback,hashlib
R=Path(__file__).resolve().parents[2];O=R/'build/restir-temporal-audit';O.mkdir(exist_ok=True)
for f in ['failure.txt','complete.json']:(O/f).unlink(missing_ok=True)
N=32768
checkpoints=sorted(set([2**i for i in range(16)]+list(range(32768,N+1,8192))))
record={'resolution':[640,360],'probe_warmup':8192,'probe_frozen':True,'full_resolution_integration':False,'jitter':True,'nrd':False,'checkpoints':checkpoints,'seed_offsets':[0],'frames':N,'pt_spp_per_frame':8,'pt_spp_per_sequence':131072,'runs':{},'started':time.time()}
record['source_hashes']={f:hashlib.sha256((R/f).read_bytes()).hexdigest() for f in ['Source/RenderPasses/RTXGIDDGI/ReSTIRGather.slang','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','scripts/DDGIAccumulated.py','scripts/PTReference.py']}
def progress(s):
 record['stage']=s;record['elapsed']=time.time()-record['started'];(O/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
 for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
def activate(g):
 g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output');m.addGraph(g);m.setActiveGraph(g)
 m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
try:
 (O/'scene.json').write_bytes((R/'build/highres-1080p-split-rerun/scene.json').read_bytes())
 os.environ['CORNELL_RTXGI_CONFIG']=str(O/'scene.json')
 setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 # Reuse the independent 262144 spp PT reference; renderer/material/light code is unchanged.
 record['reference_directory']=str(R/'build/restir-pt-convergence')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for trial,offset in enumerate(record['seed_offsets']):
  for name,temporal,spatial,feedback,jitter,history in [('legacy',True,True,False,True,20),('feedback',True,True,True,True,20),('initial',False,False,False,True,20),('temporal',True,False,False,True,20),('static-origin',True,True,False,False,20),('short-history',True,True,False,True,2),('history-one',True,False,False,True,1)]:
   re=True
   key=name+'-'+str(trial);progress(key+' setup');g=factory('half');g.name='PTConvergence_'+key;setup['configure_graph'](g)
   dd=g.getPass('DDGI');acc=g.getPass('Accumulate')
   dd.set_properties({'finalGather':False,'restirGather':False,'restirFullResolution':False,'jitterHalfGather':jitter,'gatherSpecular':False,'restirTemporal':temporal,'restirSpatial':spatial,'restirSpatialFeedback':feedback,'restirTemporalCellMapping':False,'restirBiasCorrection':True,'restirSpatialPasses':2,'restirSpatialSamples':4,'restirSpatialRadius':8.,'restirHistoryLength':history,'restirMaxAge':0})
   acc.enabled=False;activate(g)
   progress(key+' probe warmup');frames(8192);capture(key+'-probe')
   dd.set_properties({'updateEnabled':False});progress(key+' seed padding');frames(offset)
   dd.set_properties({'finalGather':True,'restirGather':re});acc.enabled=True;acc.reset()
   for i in range(1,N+1):
    renderFrame()
    if i in checkpoints:capture(key+'-'+str(i))
    if i%8192==0:progress(key+' '+str(i))
   stats=dict(dd.stats);assert stats['updatedFrames']==8192
   if re:assert stats['restirResetCount']==1
   assert stats['rejectedRaySamples']==0,'Nonfinite results during convergence test'
   record['runs'][key]={'stats':stats,'first_frame_index':8192+offset}
   g.markOutput('Reconstruct.color');frames(1);capture(key+'-raw');g.unmarkOutput('Reconstruct.color')
   g.markOutput('Display.dst');frames(64)
   m.profiler.enabled=True;frames(16);m.profiler.start_capture();frames(512)
   (O/(key+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
   progress(key+' complete');m.removeGraph(g)
 progress('complete');(O/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
