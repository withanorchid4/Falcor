"""Summarize the GPU captures. Uses the workspace Python (numpy + Pillow)."""
from pathlib import Path
import json, sys
import numpy as np
from PIL import Image, ImageDraw

root=Path(__file__).resolve().parents[2]
out=root/'build/wicked-static-validation'
sys.path.insert(0,str(root/'scripts'))
from probe_snapshot import read_image
for tag in ('wicked','wrapped-zero-bias'):
    folder=out/tag/'moments'
    for probe in (375,382):
        for field in ('m2','mu2','variance'):
            name=f'p{probe}-{field}'
            files=list(folder.glob(name+'.Probes.color.*'))
            assert len(files)==1,files
            w,h,values=read_image(files[0])
            (folder/(name+'.f32')).write_bytes(values.tobytes())
variants=['current','wicked','wrapped-zero-bias','wrapped-same-bias','ray','ray-wrapped-zero-bias']
canvas=Image.new('RGB',(1280,3*384),(20,20,20));draw=ImageDraw.Draw(canvas)
for i,name in enumerate(variants):
    im=Image.open(out/name/'display.png').convert('RGB').resize((640,360))
    x=(i%2)*640;y=(i//2)*384
    canvas.paste(im,(x,y+24));draw.text((x+8,y+5),name,fill='white')
canvas.save(out/'comparison.png')

def load(path):
    a=np.fromfile(path,dtype='<f4').reshape(720,1280,3)
    assert np.isfinite(a).all(),path
    return a

P=load(root/'build/probe-variance-14-diagnosis/g7-c0.f32')
N=load(root/'build/probe-variance-14-diagnosis/g8-c0.f32')
wall=(abs(P[...,2])<.01)&(N[...,2]<-.999)
metrics={}
for tag,ref in [('wicked','ray'),('wrapped-zero-bias','ray-wrapped-zero-bias')]:
    a=load(out/tag/'display.f32');b=load(out/ref/'display.f32')
    metrics[tag]={'wall_mae_vs_matching_ray':float(abs(a-b)[wall].mean()),
        'wall_mean_display':float(a[wall].mean()),'ray_wall_mean_display':float(b[wall].mean())}
    # Each pair shares an intensity scale. Variance uses its own scale, labeled explicitly.
    canvas=Image.new('RGB',(3*300,3*244),(20,20,20));draw=ImageDraw.Draw(canvas)
    for j,(probe,x,y,label) in enumerate(((375,520,417,'left'),(382,1057,192,'upper'),(382,1092,325,'right'))):
        fields=[load(out/tag/'moments'/f'p{probe}-{f}.f32')[...,0] for f in ('m2','mu2','variance')]
        x0=max(0,min(980,x-150));y0=max(0,min(500,y-110))
        crop=[f[y0:y0+220,x0:x0+300] for f in fields]
        lo,hi=np.percentile(np.concatenate([crop[0].ravel(),crop[1].ravel()]),[1,99])
        vhi=max(float(np.percentile(crop[2],99)),1e-10)
        for i,(values,title) in enumerate(zip(crop,['m2','mu^2','variance (separate scale)'])):
            gray=np.clip((values-lo)/(hi-lo) if i<2 else values/vhi,0,1)
            panel=Image.fromarray(np.rint(gray*255).astype('uint8')).convert('RGB')
            mark=ImageDraw.Draw(panel);xx=x-x0;yy=y-y0;mark.ellipse((xx-3,yy-3,xx+3,yy+3),outline='orange')
            canvas.paste(panel,(j*300,i*244+24))
            draw.text((j*300+5,i*244+5),f'{label} P{probe}: {title}',fill='white')
    canvas.save(out/f'{tag}-moments.png')

report=json.loads((out/'result.json').read_text())
report['image_metrics']=metrics
(out/'analysis.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'checks':report['checks'],'legacy_p50_max_error':report['legacy_p50_max_error'],'metrics':metrics},indent=2))
