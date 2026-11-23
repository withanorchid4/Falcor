from falcor import *
from pathlib import Path
import runpy,json,traceback,time,subprocess,os
R=Path(__file__).resolve().parents[2];O=R/'build/ddgi-raster-comparison';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True);info={}
if os.environ.get('PROBE_RASTER_RESUME')=='1':info=json.loads((O/'progress.json').read_text())['runs']
def save(s):(O/'progress.json').write_text(json.dumps({'stage':s,'runs':info},indent=2))
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 for name,raster in [('ray',False),('raster',True)]:
  if name in info and (O/(name+'-timing.json')).exists():continue
  save(name+' setup');g=factory('ddgi');runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
  p=g.getPass('DDGI');p.set_properties({'rasterProbeUpdate':raster,'probeCubemapSize':32,'batchProbeUpdates':True,'wrapProbeBatches':True,'probesPerFrame':32,'tetrahedralInterpolation':False,'useRTXDI':False})
  g.updatePass('Visibility',{'adjustShadingNormals':True});g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
  g.updatePass('Display',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.})
  for c in ['Accumulate.output','Visibility.normW','Visibility.posW']:g.markOutput(c)
  m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
  m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
  assert list(p.properties['gridCounts'])==[22,22,22]
  start=time.time()
  for i in range(65536):
   renderFrame()
   if (i+1)%8192==0:save(name+' warmup '+str(i+1))
  acc=g.getPass('Accumulate');acc.enabled=True;acc.reset()
  for i in range(1,32769):
   renderFrame()
   if i in [4096,8192,16384,32768]:
    m.frameCapture.baseFilename=name+'-'+str(i);m.frameCapture.capture();save(name+' accumulate '+str(i))
    if i>=8192:
     q=subprocess.run([os.environ.get('PYTHON_EXE','C:/Users/luozilong01/AppData/Local/Programs/Python/Python312/python.exe'),str(R/'tests/ddgi/check_probe_raster_stability.py'),name,str(i)],capture_output=True,text=True)
     assert q.returncode==0,q.stderr
     if json.loads((O/(name+'-stability.json')).read_text())['stable']:break
  info[name]={'accumulated':i,'warmup':65536,'seconds':time.time()-start,'properties':dict(p.properties),'stats':dict(p.stats)};assert p.stats['finite']
  m.profiler.enabled=True
  for _ in range(32):renderFrame()
  m.profiler.start_capture()
  for _ in range(512):renderFrame()
  (O/(name+'-timing.json')).write_text(json.dumps(m.profiler.end_capture()));m.profiler.enabled=False
  m.removeGraph(g)
 (O/'complete.json').write_text(json.dumps(info,indent=2));save('complete')
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
