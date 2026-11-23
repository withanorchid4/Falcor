from pathlib import Path
import sys,json
R=Path('C:/workspace/1116GitFalcor/Falcor');O=R/'build/probe-position-precompute'
sys.path.insert(0,str(R/'build/final-gather-python'));sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR
from PIL import Image,ImageDraw
out=[]
for mode in ['raster','multiview','across']:
 paths=[next(O.glob(mode+'-'+tag+'.Accumulate.output.*.exr'),None) for tag in ['before','after']]
 if None in paths:continue
 a,b=[OpenEXR.File(str(p)).channels()['RGB'].pixels for p in paths]
 diff=np.abs(a-b)
 pngs=[next(O.glob(mode+'-'+tag+'.Display.dst.*.png'),None) for tag in ['before','after']]
 row={'mode':mode,'shape':list(a.shape),'finite':bool(np.isfinite(a).all() and np.isfinite(b).all()),'linear_mae':float(diff.mean()),'linear_rmse':float(np.sqrt(np.mean(diff**2))),'linear_max':float(diff.max()),'relative_l1':float(diff.sum()/np.abs(a).sum()),'linear_equal_pixels_fraction':float(np.mean(np.all(a==b,axis=-1)))}
 if None not in pngs:
  x,y=[np.asarray(Image.open(p).convert('RGB')) for p in pngs];delta=np.abs(x.astype(float)-y.astype(float))
  row.update({'display_mae_255':float(delta.mean()),'display_max_255':float(delta.max()),'display_pixels_gt1_fraction':float(np.mean(delta.max(axis=-1)>1)),'display_pixels_gt5_fraction':float(np.mean(delta.max(axis=-1)>5))})
  canvas=Image.new('RGB',(1440,300),(20,20,20));draw=ImageDraw.Draw(canvas)
  for i,(im,label) in enumerate([(Image.fromarray(x),'Before'),(Image.fromarray(y),'After'),(Image.fromarray(np.uint8(np.minimum(delta*16,255))),'Abs difference x16')]):
   canvas.paste(im.resize((480,270)),(480*i,30));draw.text((480*i+10,8),mode+' / '+label,fill='white')
  canvas.save(O/(mode+'-comparison.png'))
 out.append(row)
(O/'image-summary.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
