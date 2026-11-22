from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/probe-wrap-smoke';O.mkdir(exist_ok=True)
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi')
 runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause()
 p=g.getPass('DDGI');rows=[]
 for budget,wrc in [(800,False),(1274,False),(10648,False),(800,True)]:
  p.set_properties({'batchProbeUpdates':True,'wrapProbeBatches':True,'probesPerFrame':budget,'useWRC':wrc});p.reset()
  for i in range(1,28):
   renderFrame();s=dict(p.stats)
   assert s['finite'] and s['lastProbeBatchStart']==((i-1)*budget)%10648
   assert s['lastProbeBatchCount']==budget and s['probeUpdatesTotal']==i*budget
   assert s['completedProbeSweeps']==i*budget//10648
  rows.append({'budget':budget,'wrc':wrc,'stats':s})
 (O/'complete.json').write_text(json.dumps(rows,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
