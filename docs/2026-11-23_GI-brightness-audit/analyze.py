from pathlib import Path
import sys,json
R=Path(__file__).resolve().parents[2];O=R/'build/brightness-audit';sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,numpy as np

def read(p):return OpenEXR.File(str(p)).channels()['RGB'].pixels
p=O/'pt-1024.Accumulate.output.0.exr'
if not p.exists():print('waiting for reference');raise SystemExit
ref=read(p);lum=ref@np.array([.2126,.7152,.0722]);norm=read(O/'pt-1024.Visibility.normW.0.exr');mask=(norm**2).sum(-1)>.5
rows=[]
for f in sorted(O.glob('*.Accumulate.output.*.exr')):
 name=f.name.split('.Accumulate')[0]
 if name.startswith('1080-'):continue
 ref=read(O/'pt-noNormals-1024.Accumulate.output.0.exr') if 'noNormals' in name else read(p)
 lum=ref@np.array([.2126,.7152,.0722])
 a=read(f);la=a@np.array([.2126,.7152,.0722]);row={'name':name,'mse':float(np.mean((a[mask]-ref[mask])**2))}
 for label,m in [('all',mask),('dark',mask&(lum<.05)),('mid',mask&(lum>=.05)&(lum<.2)),('bright',mask&(lum>=.2))]:
  row[label]={'ratio':float(la[m].sum()/lum[m].sum()),'bias':float((la[m]-lum[m]).mean()),'count':int(m.sum())}
 rows.append(row);print(name,'mse',round(row['mse'],8),'all%',round((row['all']['ratio']-1)*100,3),'dark%',round((row['dark']['ratio']-1)*100,3))
(O/'metrics.json').write_text(json.dumps(rows,indent=2))
