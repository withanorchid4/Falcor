"""Analyze coupled resolution/ray-density/angular-kernel captures after Mogwai exits."""
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[2]
out = root / 'build/wicked-angular-precision'
report = json.loads((out / 'result.json').read_text())
stages = [('baseline', '14 / 2048 rays / p64'), ('r32', '32 / 10704 / p334'),
          ('r64', '64 / 42800 / p1337'), ('r128-wide', '128 / 171200 / p64'),
          ('r128', '128 / 171200 / p5350'), ('ray', 'Ray visibility reference')]

def read(tag):
    a = np.fromfile(out / tag / 'display.f32', dtype='<f4').reshape(720, 1280, 3)
    assert np.isfinite(a).all()
    return a

P = np.fromfile(root / 'build/probe-variance-14-diagnosis/g7-c0.f32', dtype='<f4').reshape(720,1280,3)
N = np.fromfile(root / 'build/probe-variance-14-diagnosis/g8-c0.f32', dtype='<f4').reshape(720,1280,3)
yy, xx = np.indices((720,1280))
mask = (abs(P[...,0]-5.122)<.01) & (N[...,0]<-.99) & (xx>=390) & (xx<510) & (yy>=160) & (yy<650)
reference = read('ray')
canvas = Image.new('RGB', (1280,1152), (20,20,20)); draw = ImageDraw.Draw(canvas)
crop = Image.new('RGB', (1080,560), (20,20,20)); dc = ImageDraw.Draw(crop)
report['left_wall_roi'] = {'pixels':int(mask.sum()), 'screen_bounds':[390,160,510,650], 'metrics':{}}
for i,(tag,label) in enumerate(stages):
    img = Image.open(out / tag / 'display.png')
    x,y = i%2*640,i//2*384
    canvas.paste(img.resize((640,360)),(x,y+24)); draw.text((x+8,y+5),label,fill='white')
    crop.paste(img.crop((390,140,510,660)).resize((180,520)),(i*180,40)); dc.text((i*180+6,12),tag,fill='white')
    delta = read(tag)-reference
    luma_delta = delta @ np.array([.2126,.7152,.0722])
    report['left_wall_roi']['metrics'][tag] = {
        'display_rgb_mae':float(abs(delta)[mask].mean()),
        'pixels_positive_luma_error_above_0_1':int(((luma_delta>.1)&mask).sum()),
        'pixels_negative_luma_error_below_minus_0_1':int(((luma_delta<-.1)&mask).sum())}
canvas.save(out / 'comparison.png'); crop.save(out / 'corner-comparison.png')
(out / 'analysis.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report['left_wall_roi'],indent=2))
