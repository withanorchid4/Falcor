from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/probe-batch-smoke';O.mkdir(exist_ok=True)
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 g.markOutput('DDGI.color');m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 p=g.getPass('DDGI');rows=[]; (O/'stage.txt').write_text('scene loaded')
 for tag,batch,budget,fg,wrc in [('full',False,1024,False,False),('equivalent',True,32768,False,False),('batch',True,1024,False,False),('wrc',True,1024,True,True)]:
  p.set_properties({'batchProbeUpdates':batch,'probesPerFrame':budget,'finalGather':fg,'halfResolutionGather':True,'useWRC':wrc});p.reset()
  for i in range(22):
   (O/'stage.txt').write_text(tag+str(i)+' before render');renderFrame();(O/'stage.txt').write_text(tag+str(i)+' after render')
   if i in [0,9,10,11,21]: rows.append({'tag':tag,'frame':i+1,'stats':dict(p.stats)})
  m.frameCapture.baseFilename=tag;m.frameCapture.capture()
  assert p.stats['finite']
 p.set_properties({'updateEnabled':False});before=dict(p.stats);renderFrame();after=dict(p.stats)
 assert before['probeUpdatesTotal']==after['probeUpdatesTotal']
 for row in rows:
  s=row['stats'];f=row['frame'];budget=1024 if row['tag'] in ['batch','wrc'] else 10648
  expectedStart=((f-1)%11)*1024 if budget==1024 else 0
  assert s['lastProbeBatchStart']==expectedStart
  assert s['lastProbeBatchCount']==min(budget,10648-expectedStart)
  assert s['completedProbeSweeps']==(f//11 if budget==1024 else f)
 (O/'complete.json').write_text(json.dumps(rows,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
