import subprocess as sp,json
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=R/'build/brightness-audit';S=R/'build/windows-vs2022/bin/Release/shaders/RenderPasses/RTXGIDDGI'
O.mkdir(parents=True,exist_ok=True)
names=['RTXGIDDGI.rt.slang','SharcTrace.slang','LumenWorldCacheTrace.slang'];original={n:(S/n).read_bytes() for n in names}
for n,b in original.items():(O/(n+'.original')).write_bytes(b)
import argparse
parser=argparse.ArgumentParser(description="Render brightness-audit cases sequentially; temporarily patches deployed shaders and restores them on exit.")
parser.add_argument('--case', action='append', help='Case name; repeat to select multiple. Omit to run all cases.')
args=parser.parse_args()
cases=[{'name':'1080-pt','mode':'pt','width':1920,'height':1080,'warmup':16,'frames':8192}, {'name': 'pt', 'mode': 'pt'}, {'name': 'sharc-half', 'mode': 'sharc', 'half': True}, {'name': 'sharc-full', 'mode': 'sharc'}, {'name': 'wc-half', 'mode': 'wc', 'half': True}, {'name': 'wc-full', 'mode': 'wc'}, {'name': 'uncached-raw', 'mode': 'sharc', 'bypass': True}, {'name': 'uncached-material', 'mode': 'sharc', 'bypass': True, 'material': True}, {'name': 'sharc-material', 'mode': 'sharc', 'material': True}, {'name': 'wc-material', 'mode': 'wc', 'material': True}, {'name': 'uncached-strict-raw', 'mode': 'sharc', 'bypass': True, 'strict': True}, {'name': 'uncached-strict', 'mode': 'sharc', 'bypass': True, 'material': True, 'strict': True}, {'name': 'pt-noNormals', 'mode': 'pt', 'noNormals': True}, {'name': 'sharc-noNormals', 'mode': 'sharc', 'noNormals': True}, {'name': 'wc-noNormals', 'mode': 'wc', 'noNormals': True}, {'name': 'sharc-material-fine', 'mode': 'sharc', 'material': True, 'scale': 60}, {'name': '1080-sharc-original', 'mode': 'sharc', 'half': True, 'width': 1920, 'height': 1080, 'warmup': 4096, 'frames': 8192}, {'name': '1080-sharc-material', 'mode': 'sharc', 'half': True, 'material': True, 'width': 1920, 'height': 1080, 'warmup': 4096, 'frames': 8192}, {'name': '1080-wc-material', 'mode': 'wc', 'half': True, 'material': True, 'width': 1920, 'height': 1080, 'warmup': 4096, 'frames': 8192}, {'name': 'ddgi-half', 'mode': 'ddgi', 'half': True}, {'name': 'ddgi-material', 'mode': 'ddgi', 'half': True, 'material': True}]
if args.case:
 unknown=set(args.case)-{c['name'] for c in cases}
 if unknown:parser.error('Unknown cases: '+str(sorted(unknown)))
 cases=[c for c in cases if c['name'] in args.case]

try:
 for c in cases:
  (O/(c['name']+'-failure.txt')).unlink(missing_ok=True)
  (O/'case.json').write_text(json.dumps(c))
  for n,b in original.items():
   s=b.decode()
   if c.get('material'):
    if n=='RTXGIDDGI.rt.slang':s=s.replace('return albedo * (max(0.f, dot(sd.frame.N, direction)) / M_PI);','return finiteRadiance(material.eval(sd, direction, sg), 0u);')
    else:s=s.replace('sd.frame.N','properties.guideNormal')
   if c.get('strict') and n=='SharcTrace.slang':
    query,update=s.split('[shader("raygeneration")]')
    query=query.replace('bounce < gSharcBounces','bounce < 32u').replace('bounce == gSharcBounces - 1u','bounce == 31u')
    query=query.replace('sharcLuminance(primaryWeight) < .01f','false').replace('sharcLuminance(weight*primaryWeight) < .01f','false').replace('if (bounce > 3u)','if (false)')
    query=query.replace('ray.TMax = 1000.f','ray.TMax = FLT_MAX')
    query=query.replace('ray.Direction = sharcCosine(properties.guideNormal,sg);', 'BSDFSample sample = {}; if (!material.sample(sd,sg,sample,true)) break; ray.Direction = sample.wo;')
    if c.get('material'):query=query.replace('weight *= finiteRadiance(properties.diffuseReflectionAlbedo,0u);','weight *= sample.weight;')
    s=query+'[shader("raygeneration")]'+update
   if c.get('bypass') and n=='SharcTrace.slang':s=s.replace('if (segmentLength > cell','if (false && segmentLength > cell')
   (S/n).write_text(s)
  (O/'progress.txt').write_text(c['name'])
  sp.run([str(R/'build/windows-vs2022/bin/Release/Mogwai.exe'),'--headless','--device-type','d3d12','--script',str(Path(__file__).with_name('render.py')),'--width',str(c.get('width',480)),'--height',str(c.get('height',270)),'--logfile',str(O/(c['name']+'.log'))],cwd=R/'build/windows-vs2022/bin/Release',check=True,creationflags=sp.CREATE_NO_WINDOW)
  if (O/(c['name']+'-failure.txt')).exists():raise RuntimeError(c['name'])
finally:
 for n,b in original.items():(S/n).write_bytes(b)
 (O/'restored.txt').write_text('deployed shaders restored')

