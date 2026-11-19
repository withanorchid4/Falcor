from falcor import *
from pathlib import Path
import os,runpy,json,time,traceback,subprocess
R=Path(__file__).resolve().parents[2];D=R/'build/restir-pt-convergence';O=R/'build/restir-pt-failure-replay';O.mkdir(exist_ok=True)
record={'started':time.time(),'seed_offset':262144,'precision':'Single','captures':[]}
def frames(n):
 for _ in range(n):renderFrame()
def progress(s):
 record['stage']=s;record['elapsed']=time.time()-record['started'];(O/'progress.json').write_text(json.dumps(record,indent=2))
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
 os.environ['CORNELL_RTXGI_CONFIG']=str(D/'scene.json')
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated'];setup=runpy.run_path(str(R/'scripts/scenes/cornell_rtxgi.py'))
 g=factory('half');g.name='FailureReplay';setup['configure_graph'](g);dd=g.getPass('DDGI');acc=g.getPass('Accumulate')
 dd.set_properties({'finalGather':False,'restirGather':False,'restirFullResolution':False,'jitterHalfGather':True,'gatherSpecular':False,'restirTemporal':True,'restirSpatial':True,'restirBiasCorrection':True,'restirSpatialPasses':2,'restirSpatialSamples':4,'restirSpatialRadius':8.,'restirHistoryLength':20})
 acc.enabled=False;g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output');g.markOutput('Reconstruct.color')
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/CornellLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 progress('probe warmup');frames(8192);dd.set_properties({'updateEnabled':False});progress('seed padding');frames(262144)
 dd.set_properties({'finalGather':True,'restirGather':True});acc.enabled=True;acc.reset()
 progress('replay to 114688');frames(114688);capture('frame-114688')
 for stop in range(114944,123137,256):
  frames(256);capture('frame-'+str(stop));record['captures'].append({'frame':stop,'stats':dict(dd.stats)});progress('frame '+str(stop))
 progress('complete');(O/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(O/'failure.txt').write_text(traceback.format_exc())
finally:exit()
