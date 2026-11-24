from pathlib import Path
import sys,json
R=Path(__file__).resolve().parents[2];O=R/'build/brightness-audit';sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,numpy as np
read=lambda p:OpenEXR.File(str(p)).channels()['RGB'].pixels
refpath=O/'1080-pt-8192.Accumulate.output.0.exr'
ref=read(refpath if refpath.exists() else R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr');norm=read(O/'1080-pt-8192.Visibility.normW.0.exr' if refpath.exists() else R/'build/sponza-sharc-official-20261122/pt-512.Visibility.normW.0.exr');mask=(norm**2).sum(-1)>.5;L=np.array([.2126,.7152,.0722]);lum=ref@L;rows=[]
files=list(O.glob('1080-*.Accumulate.output.*.exr'))+list((R/'build/sponza-sharc-official-20261122').glob('*-16384.Accumulate.output.*.exr'))
for f in files:
 a=read(f);la=a@L;row={'name':f.name.split('.Accumulate')[0],'mse':float(np.mean((a[mask]-ref[mask])**2))}
 for label,m in [('all',mask),('dark',mask&(lum<.05)),('mid',mask&(lum>=.05)&(lum<.2)),('bright',mask&(lum>=.2))]:
  row[label]={'ratio':float(la[m].sum()/lum[m].sum()),'bias':float((la[m]-lum[m]).mean()),'count':int(m.sum())}
 rows.append(row);print(row['name'],'mse',row['mse'],'all%',100*(row['all']['ratio']-1),'dark%',100*(row['dark']['ratio']-1))
(O/'metrics1080.json').write_text(json.dumps(rows,indent=2))
