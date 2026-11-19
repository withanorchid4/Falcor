from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/emerald-black-dots';O.mkdir(exist_ok=True)
try:
 g=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']('ddgi')
 setup=runpy.run_path(str(R/'scripts/scenes/emerald_rtxgi.py'));setup['configure_graph'](g);setup['configure_display'](g)
 g.markOutput('Accumulate.output');g.markOutput('Visibility.posW');g.markOutput('Visibility.normW')
 g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/EmeraldSquareLambert.pyscene'));m.clock.pause();m.scene.animated=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 p=g.getPass('DDGI');acc=g.getPass('Accumulate')
 for _ in range(512):renderFrame()
 def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
 p.set_properties({'enableGI':False})
 for mode in ['both','sun','sun-flat']:
  if mode!='both':m.scene.getLight('pointLight1').active=False
  if mode=='sun-flat':
   for mat in m.scene.materials:mat.clearTexture(MaterialTextureSlot.Normal)
  for _ in range(4):renderFrame()
  acc.reset()
  for i in range(256):
   renderFrame()
   if i in [0,1,255]:capture(mode+'-'+str(i+1))
 (O/'complete.json').write_text(json.dumps({'scene':'EmeraldSquareLambert','GI':False,'frames':256,'cases':['both','sun','sun-flat']},indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
