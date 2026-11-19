from falcor import *
from pathlib import Path
import runpy,traceback,json
R=Path(__file__).resolve().parents[2];O=R/'build/emerald-black-dots'
try:
 g=runpy.run_path(str(R/'scripts/PTReference.py'))['PTReference']
 g.updatePass('PT',{'maxSurfaceBounces':0,'maxDiffuseBounces':0,'maxSpecularBounces':0,'maxTransmissionBounces':0,'primaryLodMode':'Mip0'})
 g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
 runpy.run_path(str(R/'scripts/scenes/emerald_rtxgi.py'))['configure_display'](g)
 g.markOutput('Accumulate.output');m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/EmeraldSquareLambert.pyscene'));m.clock.pause();m.scene.animated=False
 m.scene.envMap=None;m.scene.getLight('pointLight1').active=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 for adjust in [True,False]:
  g.updatePass('Visibility',{'adjustShadingNormals':adjust})
  for _ in range(4):renderFrame()
  g.getPass('Accumulate').reset()
  for _ in range(32):renderFrame()
  m.frameCapture.baseFilename='pt-sun-adjust-'+str(adjust);m.frameCapture.capture()
 (O/'pt-complete.json').write_text(json.dumps(dict(g.getPass('PT').properties),indent=2,default=str))
except:(O/'pt-failure.txt').write_text(traceback.format_exc())
exit()
