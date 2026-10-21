"""Compare independently captured Wicked alignment steps at fixed camera/budget."""
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[2]
out = root/'build/probe-wicked-alignment'
records = json.loads((out/'result.json').read_text())
moments = json.loads((out/'moments/result.json').read_text())
variants = json.loads((out/'variants.json').read_text())
old = root/'build/probe-variance-14-diagnosis'
previous = root/'build/probe-ddgi-alignment/verified'

def pixels(directory, kind='display'):
    a = np.fromfile(directory/(kind+'.f32'),dtype='<f4').reshape(720,1280,3)
    assert np.isfinite(a).all()
    return a

reference = pixels(previous/'ray-reference')
P = np.fromfile(old/'g7-c0.f32',dtype='<f4').reshape(720,1280,3)
N = np.fromfile(old/'g8-c0.f32',dtype='<f4').reshape(720,1280,3)
wall = (abs(P[...,2])<.01)&(N[...,2]<-.999)
metrics = {}
last = pixels(root/'build/probe-filter-strength/p50')
for v in variants:
    tag=v['tag']; a=pixels(out/tag)
    slopes=moments['slopes_per_screen_pixel'][tag]
    pair=[]
    for entry in records['points'][tag][:2]:
        d=entry['data']; k=next(str(i) for i in range(8) if d['probe'+str(i)]==375)
        pair.append({name:d[name+k] for name in ('weight','visibility','meanDistance','distanceVariance','queryDistance','queryHitDistance')})
    metrics[tag]={
        'wall_display_mae_vs_ray':float(abs(a-reference)[wall].mean()),
        'wall_positive_luminance_error':float(np.maximum((a-reference)@np.array([.2126,.7152,.0722]),0)[wall].mean()),
        'display_mae_vs_previous_step':float(abs(a-last).mean()),
        'm2_slope_kink':abs(slopes['m2']['left']-slopes['m2']['right']),
        'mu2_slope_kink':abs(slopes['mu2']['left']-slopes['mu2']['right']),
        'probe375_AB':pair}
    last=a

panels=[(root/'build/probe-filter-strength/p50','Before: exponent 50')]
panels += [(out/v['tag'],v['label']) for v in variants]
panels += [(root/'build/probe-filter-strength/p5','Previous strong filter: exponent 5'),(previous/'ray-reference','Ray visibility reference (same SH)')]
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17)
for crop,name in ((None,'comparison.png'),((430,140,1270,700),'wall-comparison.png')):
    canvas=Image.new('RGB',(1680,636),(22,22,22));draw=ImageDraw.Draw(canvas)
    for i,(directory,label) in enumerate(panels):
        x,y=i%4*420,i//4*318
        draw.text((x+5,y+6),label,font=font,fill='white')
        im=Image.open(directory/'display.png')
        if crop: im=im.crop(crop)
        canvas.paste(im.resize((420,280),Image.Resampling.LANCZOS),(x,y+34))
    canvas.save(out/name)
(out/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
print(json.dumps(metrics,indent=2))
