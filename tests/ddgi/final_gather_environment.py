"""Unit-sky Lambert surface: gather must return albedo once, with zero specular."""
from falcor import *
from pathlib import Path
import runpy,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/final-gather-environment'
OUT.mkdir(exist_ok=True)
for stale in ["failure.txt", "complete.json", "complete.txt"]:
    (OUT/stale).unlink(missing_ok=True)
(OUT/'unit-sky.hdr').write_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 2 +X 4\n"+bytes([128,128,128,129])*8)
(OUT/'plane.pyscene').write_text("""from falcor import *
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
    g=runpy.run_path(str(ROOT/'scripts/RTXGIDDGIFinalGather.py'))['RTXGIDDGIFinalGather']
    for c in ['DDGI.color','DDGI.indirect','DDGI.gatherDiffuse','DDGI.gatherSpecular','Visibility.normW']:g.markOutput(c)
    m.addGraph(g);m.loadScene(str(OUT/'plane.pyscene'));m.clock.pause()
    for _ in range(4):renderFrame()
    m.frameCapture.outputDir=str(OUT);m.frameCapture.baseFilename='unit-sky';m.frameCapture.capture()
    (OUT/'complete.txt').write_text('Captured')
except Exception:
    (OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
