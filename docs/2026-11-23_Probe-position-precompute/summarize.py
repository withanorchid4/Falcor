from pathlib import Path
import json,statistics
O=Path(__file__).parent
f=O/'complete.json'
d=json.loads((f if f.exists() else O/'progress.json').read_text())
rows=[]
for r in d['runs']:
 e=json.loads((O/r['file']).read_text())['events']
 v={k.split('/')[-2]:statistics.mean(t['records'][4:]) for k,t in e.items() if k.endswith('/gpu_time')}
 rows.append({**r,'gpu_ms':v})
groups=[]
for mode in ['raster','multiview','across']:
 for pre in [False,True]:
  a=[r for r in rows if r['mode']==mode and r['precompute']==pre]
  if not a:continue
  v={k:statistics.mean(r['gpu_ms'][k] for r in a) for k in a[0]['gpu_ms']}
  groups.append({'mode':mode,'precompute':pre,'gpu_ms':v})
  print(mode,pre,{k:round(x,4) for k,x in v.items() if k in ['ProbeUpdate','RasterVisibility','PrecomputeProbePositions','RenderGraphExe::execute()']})
for r in rows:print('run',r['mode'],r['precompute'],round(r['gpu_ms']['ProbeUpdate'],4))
print('validation')
for v in d['validation']:
 s=v['stats'];print(v['offset'],v['count'],v['mode'],v['precompute'],*[s[k] for k in ['missingCapturePixels','extraCapturePixels','capturePositionMismatch','captureSameTrianglePositionMismatch','captureMaxPositionError']])
(O/'summary.json').write_text(json.dumps({'complete':f.exists(),'groups':groups,'runs':rows,'validation':d['validation']},indent=2))
