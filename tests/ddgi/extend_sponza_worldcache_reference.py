"""Extend the two PT sequences without rerendering the converged GI captures."""
from falcor import *
from pathlib import Path
import runpy,json,traceback,time,os
R=Path(__file__).resolve().parents[2];O=R/'build/sponza-worldcache-ddgi-1080p-20261119'
base=int(os.environ.get('PT_BASE_SEQUENCE_SPP','16384'));started=time.time()
def progress(stage):
 (O/'pt-extension-progress.json').write_text(json.dumps({'base_sequence_spp':base,'stage':stage,'elapsed':time.time()-started}))
try:
 assert all((O/(f'pt-{s}-{base}.Accumulate.output.0.exr')).exists() for s in ['a','b'])
 g=runpy.run_path(str(R/'scripts/PTReference.py'))['PTReference']
 g.updatePass('Accumulate',{'enabled':True,'autoReset':False,'precisionMode':'SingleCompensated'})
 g.unmarkOutput('Display.dst');g.markOutput('Accumulate.output')
 m.addGraph(g);m.setActiveGraph(g);m.loadScene(str(R/'scripts/scenes/SponzaLambert.pyscene'));m.clock.pause();m.scene.camera.animated=False
 m.scene.getLight('Atrium Point').active=True;m.scene.getLight('Atrium Sun').active=False
 m.frameCapture.outputDir=str(O);m.frameCapture.captureAllOutputs=False
 pt=g.getPass('PT');pt.useFixedSeed=True;acc=g.getPass('Accumulate')
 renderFrame()
 for seq,offset in [('a',1),('b',100001)]:
  acc.reset()
  for i in range(base//8):
   pt.fixedSeed=offset+base//8+i;renderFrame()
   if (i+1)%128==0:progress(f'PT {seq} +{(i+1)*8}/{base} spp')
  m.frameCapture.baseFilename=f'pt-{seq}-block-{base}-to-{2*base}';m.frameCapture.capture()
 progress('complete');(O/f'pt-extension-{base}-complete.json').write_text(json.dumps({'base_sequence_spp':base,'added_total_spp':2*base,'elapsed':time.time()-started,'same_settings':True,'seed_ranges':[[1+base//8,2*base//8],[100001+base//8,100000+2*base//8]]}))
except Exception:(O/'pt-extension-failure.txt').write_text(traceback.format_exc())
finally:exit()
