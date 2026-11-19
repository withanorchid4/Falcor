from pathlib import Path
import numpy as np,json
R=Path(__file__).resolve().parents[2]
p=R/Path('media/ORCA_EmeraldSquare/EmeraldSquare_v4_1/symmetrical_garden_4k.hdr')
with p.open('rb') as f:
 while f.readline().strip():pass
 line=f.readline().decode().split();h=int(line[1]);w=int(line[3]);a=np.empty((h,w,4),np.uint8)
 for y in range(h):
  assert f.read(4)==bytes([2,2,w>>8,w&255])
  for c in range(4):
   x=0
   while x<w:
    n=f.read(1)[0]
    if n>128:
     n-=128;a[y,x:x+n,c]=f.read(1)[0]
    else:a[y,x:x+n,c]=np.frombuffer(f.read(n),np.uint8)
    x+=n
rgb=a[...,:3].astype(np.float32)*np.exp2(a[...,3].astype(np.float32)-136)[...,None]
lum=rgb@np.array([.2126,.7152,.0722]);stats={'resolution':[w,h],'rgb_max':float(rgb.max()),'luminance_percentiles':dict(zip(['50','90','99','99.9','99.99','100'],map(float,np.percentile(lum,[50,90,99,99.9,99.99,100])))),'texel_fraction_luminance_over_100':float((lum>100).mean()),'note':'Unweighted lat-long texel statistics; not solid-angle integration. FG misses use BSDF sampling without environment NEE/MIS.'}
(R/'build/emerald-coverage/environment.json').write_text(json.dumps(stats,indent=2));print(stats)
