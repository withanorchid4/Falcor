"""CPU scoring and image-stability checks for a completed accumulated checkpoint."""
from pathlib import Path
import sys,json,time
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-seven-accumulated-20261120'
sys.path.insert(0,str(R/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
name=sys.argv[1];n=int(sys.argv[2])
def exr(p):
 # Falcor captures are written asynchronously. Wait for a fully readable EXR.
 for attempt in range(120):
  try:
   a=OpenEXR.File(str(p)).channels()['RGB'].pixels
   assert np.isfinite(a).all(),p
   return a
  except (RuntimeError,ValueError,OSError):
   if attempt==119:raise
   time.sleep(.25)
def read(k):return exr(D/(name+'-'+str(k)+'.Accumulate.output.0.exr'))
ref=exr(R/'build/sponza-worldcache-ddgi-official-probes-20261119/reference-131072spp.exr')
mask=np.linalg.norm(exr(D/(name+'-1.Visibility.normW.0.exr')),axis=-1)>.5
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
settings=D/'metric-settings.json'
if settings.exists():cfg=json.loads(settings.read_text())
else:
 _,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
 lum=ref@np.array([.2126,.7152,.0722]);cfg={'flip_parameters':params,'display_exposure_ev':float(-np.log2(np.percentile(lum[mask],99))),'mask_pixels':int(mask.sum())};settings.write_text(json.dumps(cfg,indent=2))
def display(a):
 x=np.maximum(a*2**cfg['display_exposure_ev'],0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
a=read(n);err=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=cfg['flip_parameters'].copy())[0][:,:,0]
r={'frame':n,'mse':mse(a,ref),'hdr_flip':float(err[mask].mean()),'passed':False}
previous=D/(name+'-'+str(n//2)+'.Accumulate.output.0.exr')
if n>=16384 and previous.exists():
 b=read(n//2);delta=np.abs(display(a)[mask]-display(b)[mask]);old=json.loads((D/(name+'-'+str(n//2)+'-metrics.json')).read_text())
 r.update({'tail_mse':mse(a,b),'tail_relative_rgb_rms':float(np.sqrt(mse(a,b)/np.mean(ref[mask].astype(np.float64)**2))),'display_mean_abs_levels':float(delta.mean()*255),'display_p99_abs_levels':float(np.percentile(delta,99)*255),'relative_pt_mse_change':r['mse']/old['mse']-1,'relative_pt_flip_change':r['hdr_flip']/old['hdr_flip']-1})
 # A screen-color criterion, plus reference-error stability; no raw-frame noise test.
 r['passed']=bool(r['tail_relative_rgb_rms']<.001 and r['display_mean_abs_levels']<.25 and r['display_p99_abs_levels']<2 and abs(r['relative_pt_mse_change'])<.01 and abs(r['relative_pt_flip_change'])<.01)
(D/(name+'-'+str(n)+'-metrics.json')).write_text(json.dumps(r,indent=2))
print(json.dumps(r))
