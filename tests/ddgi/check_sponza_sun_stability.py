from pathlib import Path
import sys,json,time
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-sun50-20261120'
if len(sys.argv)>3:D=Path(sys.argv[3])
sys.path.insert(0,str(R/'build/final-gather-python'))
import numpy as np,OpenEXR
name=sys.argv[1];n=int(sys.argv[2])
def exr(p):
 for i in range(120):
  try:
   a=OpenEXR.File(str(p)).channels()['RGB'].pixels
   assert np.isfinite(a).all()
   return a
  except (OSError,ValueError,RuntimeError):
   if i==119:raise
   time.sleep(.25)
def read(k):return exr(D/(name+'-'+str(k)+'.Accumulate.output.0.exr'))
a=read(n);mask=np.linalg.norm(exr(D/'pt-512.Visibility.normW.0.exr'),axis=-1)>.5
settings=D/'display.json'
if settings.exists():cfg=json.loads(settings.read_text())
else:
 lum=a@np.array([.2126,.7152,.0722]);cfg={'exposure_ev':float(-np.log2(np.percentile(lum[mask],99))),'mask_pixels':int(mask.sum()),'source':'first PT checkpoint, fixed for all images'};settings.write_text(json.dumps(cfg,indent=2))
def display(x):
 x=np.maximum(x*2**cfg['exposure_ev'],0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
r={'frame':n,'spp':n*8 if name=='pt' else n,'passed':False}
if n>=1024 and (D/(name+'-'+str(n//2)+'.Accumulate.output.0.exr')).exists():
 b=read(n//2);delta=np.abs(display(a)[mask]-display(b)[mask]);mse=float(np.mean((a[mask].astype(np.float64)-b[mask])**2));energy=float(np.mean(a[mask].astype(np.float64)**2))
 r.update({'tail_mse':mse,'relative_rgb_rms':float(np.sqrt(mse/max(energy,1e-20))),'display_mean_abs_levels':float(delta.mean()*255),'display_p99_abs_levels':float(np.percentile(delta,99)*255)})
 r['passed']=bool(r['relative_rgb_rms']<.001 and r['display_mean_abs_levels']<.25 and r['display_p99_abs_levels']<2)
(D/(name+'-'+str(n)+'-stability.json')).write_text(json.dumps(r,indent=2));print(json.dumps(r))
