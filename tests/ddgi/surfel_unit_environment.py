from falcor import *
from pathlib import Path
import runpy,traceback
R=Path(__file__).resolve().parents[2];O=R/'build/surfel-unit';O.mkdir(exist_ok=True)
(O/'failure.txt').unlink(missing_ok=True)
(O/'unit-sky.hdr').write_bytes(b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 2 +X 4\n'+bytes([128,128,128,129])*8)
(O/'plane.pyscene').write_text("""from falcor import *
material=PBRTDiffuseMaterial('Lambert')
material.baseColor=float4(.5,.5,.5,1)
sceneBuilder.addMeshInstance(sceneBuilder.addNode('Floor',Transform(scaling=float3(8,1,8))),sceneBuilder.addTriangleMesh(TriangleMesh.createQuad(),material))
sceneBuilder.envMap=EnvMap('unit-sky.hdr')
camera=Camera()
camera.position=float3(0,2,4)
camera.target=float3(0,.6,0)
sceneBuilder.addCamera(camera)
""")
try:
 g=runpy.run_path(str(R/'scripts/SurfelGI.py'))['SurfelGI'];m.addGraph(g);m.setActiveGraph(g)
 m.loadScene(str(O/'plane.pyscene'));m.clock.pause()
 g.updatePass('Accumulate',{'enabled':False,'autoReset':False})
 g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
 for _ in range(1024):renderFrame()
 g.getPass('Accumulate').enabled=True;g.getPass('Accumulate').reset()
 for _ in range(512):renderFrame()
 m.frameCapture.outputDir=str(O);m.frameCapture.baseFilename='unit';m.frameCapture.capture()
 (O/'complete.txt').write_text(str(dict(g.getPass('Surfel').stats)))
except:(O/'failure.txt').write_text(traceback.format_exc())
exit()
