from falcor import *
from pathlib import Path
import runpy,json,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/emerald-primary-normal-fix';O.mkdir(exist_ok=True)
try:
 factory=runpy.run_path(str(R/'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
 g=factory('ddgi');setup=runpy.run_path(str(R/'scripts/scenes/emerald_rtxgi.py'));setup['configure_graph'](g);setup['configure_display'](g)
 g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'});g.markOutput('Accumulate.output')
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/EmeraldSquareLambert.pyscene'));m.clock.pause();m.scene.animated=False;m.scene.getLight('pointLight1').active=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 p=g.getPass('DDGI');p.set_properties({'enableGI':False})
 for adjust in [True,False,True]:
  g.updatePass('Visibility',{'adjustShadingNormals':adjust})
  for _ in range(4):renderFrame()
  g.getPass('Accumulate').reset()
  for _ in range(32):renderFrame()
  m.frameCapture.baseFilename='ddgi-adjust-'+str(adjust);m.frameCapture.capture()
 p.set_properties({'enableGI':True})
 for _ in range(512):renderFrame()
 g.getPass('Accumulate').reset()
 for _ in range(256):renderFrame()
 m.frameCapture.baseFilename='ddgi-static';m.frameCapture.capture()
 stats={'ddgi':dict(p.stats)}
 # Compile and execute both FG dispatch variants and the optional ReSTIR path.
 for tag,half,restir in [('fg-half',True,False),('fg-full',False,False),('restir-half',True,True)]:
  p.set_properties({'finalGather':True,'halfResolutionGather':half,'restirGather':restir})
  for _ in range(16):renderFrame()
  m.frameCapture.baseFilename=tag;m.frameCapture.capture();stats[tag]=dict(p.stats)
  assert stats[tag]['finite'] and stats[tag]['nonFiniteTexels']==0
 m.removeGraph(g)
 g=factory('half',world_cache=True);setup['configure_display'](g);g.markOutput('Accumulate.output');m.addGraph(g);m.setActiveGraph(g)
 m.loadScene(str(R/'scripts/scenes/EmeraldSquareLambert.pyscene'));m.clock.pause();m.scene.animated=False
 for _ in range(32):renderFrame()
 m.frameCapture.baseFilename='worldcache-half';m.frameCapture.capture();stats['worldcache']=dict(g.getPass('WorldCache').stats)
 (O/'complete.json').write_text(json.dumps(stats,indent=2))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
