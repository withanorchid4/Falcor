from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/brightness-audit';case=json.loads((O/'case.json').read_text());name=case['name']
try:
 if case['mode']=='pt':g=runpy.run_path(str(R/'scripts/PTReference.py'))['render_graph_PTReference']()
 else:
  g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('half' if case.get('half') else 'full',world_cache=case['mode']!='ddgi')
  p=g.getPass('DDGI' if case['mode']=='ddgi' else 'WorldCache');p.set_properties({'sharc':case['mode']=='sharc','sharcSceneScale':20.,'gatherSpecular':False,'primaryShadingNormalCorrection':True,'jitterHalfGather':False})
 if case['mode']=='ddgi':runpy.run_path(str(R/'scripts/scenes/sponza_rtxgi.py'))['configure_graph'](g)
 g.updatePass('Visibility',{'adjustShadingNormals':True})
 g.updatePass('Accumulate',{'enabled':False,'autoReset':False,'precisionMode':'SingleCompensated'})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.animated=False
 if case.get('noNormals'):
  for mat in m.scene.materials:mat.clearTexture(MaterialTextureSlot.Normal)
 if case.get('scale') and case['mode']!='pt':p.set_properties({'sharcSceneScale':case['scale'],'worldCacheDensity':case['scale']})
 for _ in range(case.get('warmup',16 if case['mode']=='pt' else 2048)):renderFrame()
 g.getPass('Accumulate').enabled=True;g.getPass('Accumulate').reset()
 g.markOutput('Accumulate.output');g.markOutput('Visibility.normW');g.markOutput('Visibility.posW')
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 for i in range(1,(case.get('frames',1024 if case['mode']=='pt' else 4096))+1):
  renderFrame()
  if i in [512,1024,2048,4096,8192]:
   m.frameCapture.baseFilename=name+'-'+str(i);m.frameCapture.capture()
 (O/(name+'-done.json')).write_text(json.dumps({'case':case,'properties':dict((g.getPass('PT') if case['mode']=='pt' else p).properties)},indent=2))
except:(O/(name+'-failure.txt')).write_text(traceback.format_exc())
exit()
