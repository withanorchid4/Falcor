from pathlib import Path
import sys,json,time
R=Path(__file__).resolve().parents[2];D=Path(sys.argv[3]) if len(sys.argv)>3 else R/'build/ddgi-raster-comparison';sys.path.insert(0,str(R/'build/final-gather-python'))
import numpy as np,OpenEXR
name=sys.argv[1];n=int(sys.argv[2])
def exr(path):
 for attempt in range(120):
  try:return OpenEXR.File(str(path)).channels()['RGB'].pixels
  except (OSError,ValueError,RuntimeError):
   if attempt==119:raise
   time.sleep(.25)
def read(k):return exr(D/(name+'-'+str(k)+'.Accumulate.output.0.exr'))
x=read(n);y=read(n//2);mask=np.linalg.norm(exr(D/(name+'-'+str(n)+'.Visibility.normW.0.exr')),axis=-1)>.5
assert np.isfinite(x).all()
rel=float(np.sqrt(np.mean((x[mask].astype('float64')-y[mask])**2)/np.mean(x[mask].astype('float64')**2)))
def display(a):
 a=np.maximum(a*2**-2.32679,0);a=np.clip(a*(2.51*a+.03)/(a*(2.43*a+.59)+.14),0,1);return np.where(a<=.0031308,a*12.92,1.055*a**(1/2.4)-.055)
d=np.abs(display(x)[mask]-display(y)[mask])*255
(D/(name+'-stability.json')).write_text(json.dumps({'frame':n,'relative_rms':rel,'mean_display_levels':float(d.mean()),'p99_display_levels':float(np.percentile(d,99)),'stable':bool(rel<.001 and d.mean()<.25 and np.percentile(d,99)<2)},indent=2))
