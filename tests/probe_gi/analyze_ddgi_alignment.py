"""Offline image comparisons for the fixed DDGI alignment experiment."""
from pathlib import Path
import json, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[2]
out = root/'build/probe-ddgi-alignment/verified'
result = json.loads((out/'result.json').read_text())
tags = ['baseline','angular-only','angular-range15','ddgi-weights','ray-reference','ddgi-sparse4']

def pixels(tag, kind):
    a = np.fromfile(out/tag/(kind+'.f32'),dtype='<f4').reshape(720,1280,3)
    assert np.isfinite(a).all(), (tag,kind)
    return a

metrics = {}
for a,b in [('angular-range15','restored'),('ray-ddgi-on','ray-reference'),('ddgi-weights','ddgi-reloaded')]:
    error = float(np.max(np.abs(pixels(a,'hdr')-pixels(b,'hdr'))))
    assert error < 2e-5, (a,b,error)
    metrics[a+' vs '+b] = error
reference = np.fromfile(root/'build/probe-issues/20260924-104702-ae8fb0/baseline/hdr.f32',dtype='<f4').reshape(720,1280,3)
metrics['original_snapshot_hdr_max'] = float(np.max(np.abs(pixels('baseline','hdr')-reference)))
assert metrics['original_snapshot_hdr_max'] < .001
for tag in tags:
    a = pixels(tag,'display')
    metrics[tag] = {'ab_rgb_jump':float(np.max(abs(a[417,520]-a[417,521]))),
                    'ray_display_mae':float(np.mean(abs(a-pixels('ray-reference','display'))))}
    records = result['points'].get(tag,[])
    if records:
        metrics[tag]['probe375_AB'] = []
        for record in records[:2]:
            d = record['data']
            k = next(str(i) for i in range(8) if d['probe'+str(i)] == 375)
            metrics[tag]['probe375_AB'].append({name:d[name+k] for name in (
                'weight','visibility','meanDistance','distanceVariance','queryDistance','appliedVisibility')})

font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',20)
labels=['Original texel-local / range 2','Angular only / range 2','Angular / range 1.5',
        'Angular / range 1.5 / DDGI weights','Ray visibility reference','DDGI + sparse 4 x 4']
canvas=Image.new('RGB',(1280,3*390),(22,22,22)); draw=ImageDraw.Draw(canvas)
for i,(tag,label) in enumerate(zip(tags,labels)):
    x,y=i%2*640,i//2*390
    draw.text((x+8,y+3),label,font=font,fill='white')
    canvas.paste(Image.open(out/tag/'display.png').resize((640,360)),(x,y+30))
canvas.save(out/'comparison.png')
# Same source crop, magnified without smoothing, for local hard-edge inspection.
canvas=Image.new('RGB',(3*520,2*380),(22,22,22));draw=ImageDraw.Draw(canvas)
for i,(tag,label) in enumerate(zip(tags,labels)):
    x,y=i%3*520,i//3*380
    draw.text((x+8,y+3),label,font=font,fill='white')
    canvas.paste(Image.open(out/tag/'display.png').crop((420,310,680,485)).resize((520,350),Image.Resampling.NEAREST),(x,y+30))
canvas.save(out/'edge-crops.png')
(out/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
print(json.dumps(metrics,indent=2))
