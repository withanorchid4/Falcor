"""Compare the fixed-setting resolution sweep (workspace Python: numpy, Pillow)."""
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw

root=Path(__file__).resolve().parents[2]
out=root/'build/wicked-resolution-sweep'
report=json.loads((out/'result.json').read_text())

def image(directory):
    values=np.fromfile(directory/'display.f32',dtype='<f4').reshape(720,1280,3)
    assert np.isfinite(values).all()
    return values

P=np.fromfile(root/'build/probe-variance-14-diagnosis/g7-c0.f32',dtype='<f4').reshape(720,1280,3)
N=np.fromfile(root/'build/probe-variance-14-diagnosis/g8-c0.f32',dtype='<f4').reshape(720,1280,3)
mask=(abs(P[...,0]-5.122)<.01)&(N[...,0]<-.99)&(abs(P[...,2])<.04)
mask[:160]=False;mask[650:]=False
reference=image(out/'ray')
canvas=Image.new('RGB',(1280,1152),(20,20,20));draw=ImageDraw.Draw(canvas)
for i,(tag,label) in enumerate([('r14','14 x 14'),('r32','32 x 32'),('r64','64 x 64'),('r128','128 x 128'),
    ('ray','Ray visibility reference'),('old14','Original 14 x 14 cache')]):
    x=i%2*640;y=i//2*384
    canvas.paste(Image.open(out/tag/'display.png').resize((640,360)),(x,y+24))
    draw.text((x+8,y+5),label,fill='white')
canvas.save(out/'comparison.png')
crop=Image.new('RGB',(900,560),(20,20,20));draw=ImageDraw.Draw(crop)
for i,tag in enumerate(('r14','r32','r64','r128','ray')):
    crop.paste(Image.open(out/tag/'display.png').crop((390,140,510,660)).resize((180,520)),(i*180,40))
    draw.text((i*180+8,12),tag,fill='white')
crop.save(out/'corner-comparison.png')
for resolution,entry in report['variants'].items():
    info=entry['points'][1]['data']
    k=next(str(i) for i in range(8) if info['probe'+str(i)]==375)
    entry['probe375_pixel433_360']={name:info[name+k] for name in
        ('meanDistance','queryDistance','queryHitDistance','visibility','weight')}
    entry['corner_display_mae_vs_ray']=float(abs(image(out/('r'+resolution))-reference)[mask].mean())
report['corner_mask_pixels']=int(mask.sum())
(out/'analysis.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:{f:v[f] for f in ('distance_texture_mib','corner_display_mae_vs_ray','probe375_pixel433_360')}
    for k,v in report['variants'].items()},indent=2))
