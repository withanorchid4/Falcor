"""Image and visibility-error report for the fixed-memory angular filter sweep."""
from pathlib import Path
import json, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[2]
out = root/'build/probe-filter-strength'
previous = root/'build/probe-ddgi-alignment/verified'
old = root/'build/probe-variance-14-diagnosis'
records = json.loads((out/'result.json').read_text())
moments = json.loads((out/'moments/result.json').read_text())
font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 19)


def pixels(directory, kind='display'):
    a = np.fromfile(directory/(kind+'.f32'), dtype='<f4').reshape(720,1280,3)
    assert np.isfinite(a).all()
    return a


reference = pixels(previous/'ray-reference')
positions = np.fromfile(old/'g7-c0.f32', dtype='<f4').reshape(720,1280,3)
normals = np.fromfile(old/'g8-c0.f32', dtype='<f4').reshape(720,1280,3)
wall = (abs(positions[...,2]) < .01) & (normals[...,2] < -.999)
assert wall.sum() > 10000
same = float(abs(pixels(out/'p50','hdr')-pixels(previous/'ddgi-weights','hdr')).max())
assert same < .001, same
metrics = {'wall_pixel_count':int(wall.sum()), 'p50_replay_hdr_max_difference':same,
           'reference':'Same SH, ray visibility backend; not a PathTracer reference', 'variants':{}}
for p in (50,25,10,5):
    tag = f'p{p}'
    a = pixels(out/tag)
    luminance_diff = (a-reference) @ np.array([.2126,.7152,.0722])
    r = {'kernel_half_weight_degrees':math.degrees(math.acos(.5**(1/p))),
         'display_rgb_mae_vs_ray':float(np.mean(abs(a-reference))),
         'wall_display_rgb_mae_vs_ray':float(np.mean(abs(a-reference)[wall])),
         'wall_positive_luminance_error':float(np.maximum(luminance_diff[wall],0).mean()),
         'original_AB_display_max_difference':float(abs(a[417,520]-a[417,521]).max())}
    pair = []
    for rec in records['points'][tag][:2]:
        d = rec['data']
        k = next(str(i) for i in range(8) if d['probe'+str(i)] == 375)
        pair.append({'pixel':rec['pixel'], **{key:d[key+k] for key in (
            'weight','visibility','meanDistance','distanceVariance','queryDistance','visible','queryHitDistance') if key+k in d}})
    r['probe375_AB'] = pair
    slopes = moments['slopes_per_screen_pixel'][tag]
    r['m2_slope_kink'] = abs(slopes['m2']['left']-slopes['m2']['right'])
    r['mu2_slope_kink'] = abs(slopes['mu2']['left']-slopes['mu2']['right'])
    metrics['variants'][tag] = r

panels = [(out/f'p{p}', f'p={p}'+(' (previous DDGI preset)' if p==50 else ' (stronger filter)')) for p in (50,25,10,5)]
panels += [(previous/'ray-reference','Ray visibility reference'),(previous/'baseline','Original texel-local / range 2')]
canvas = Image.new('RGB',(1440,612),(22,22,22))
draw = ImageDraw.Draw(canvas)
for i,(directory,label) in enumerate(panels):
    x,y=i%3*480,i//3*306
    draw.text((x+6,y+5),label,font=font,fill='white')
    canvas.paste(Image.open(directory/'display.png').resize((480,270),Image.Resampling.LANCZOS),(x,y+32))
canvas.save(out/'comparison.png')
canvas = Image.new('RGB',(1440,612),(22,22,22));draw=ImageDraw.Draw(canvas)
for i,(directory,label) in enumerate(panels):
    x,y=i%3*480,i//3*306
    draw.text((x+6,y+5),label,font=font,fill='white')
    im=Image.open(directory/'display.png').crop((430,190,1230,640)).resize((480,270),Image.Resampling.LANCZOS)
    canvas.paste(im,(x,y+32))
canvas.save(out/'wall-comparison.png')
(out/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
print(json.dumps(metrics,indent=2))
