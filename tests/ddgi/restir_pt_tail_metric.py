from pathlib import Path
import sys,json,numpy as np
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR
D=R/'build/restir-pt-convergence';T=R/'build/restir-pt-long-tail'
name,n,previous=sys.argv[1],int(sys.argv[2]),int(sys.argv[3])
def read(p):return OpenEXR.File(str(p)).channels()['RGB'].pixels
mask=np.linalg.norm(read(D/'mask.Visibility.normW.0.exr'),axis=-1)>.5
ref=(read(D/'pt-a-131072.Accumulate.output.0.exr')+read(D/'pt-b-131072.Accumulate.output.0.exr'))*.5
x=read(T/(name+'-'+str(n)+'.Accumulate.output.0.exr'))
def mse(a,b):return float(np.mean((a[mask].astype(float)-b[mask])**2))
v={'mse':mse(x,ref)}
if previous:
 y=read(T/(name+'-'+str(previous)+'.Accumulate.output.0.exr'))
 v.update(relative_mse_change=v['mse']/mse(y,ref)-1,tail_delta_mse=mse(x,y),tail_over_error=mse(x,y)/v['mse'])
if n==131072:
 y=read(D/(name+'-0-131072.Accumulate.output.0.exr'))
 v.update(single_vs_compensated_mse=mse(x,y),single_vs_compensated_max_abs=float(np.max(abs(x-y))))
print(json.dumps(v))
