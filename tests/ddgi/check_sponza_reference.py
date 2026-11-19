"""Check a saved PT doubling; optionally finalize metadata after stopping our renderer.

Two disjoint equal-size sample blocks are A=first half, B=2*full-A.
Their averaged-reference noise estimate MSE(A,B)/4 equals MSE(full,A).
The checkpoint is accepted only if this estimate is below 1% of the lowest
method error AND its RMS is below 0.5% of reference RGB RMS.
"""
from pathlib import Path
import argparse, json, sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import OpenEXR
p=argparse.ArgumentParser();p.add_argument('--spp',type=int,required=True)
p.add_argument('--finalize',action='store_true');args=p.parse_args()
D=ROOT/'build/sponza-lambert-1080p-20261119'
def read(tag,channel='Accumulate.output'):
    a=OpenEXR.File(str(D/(tag+'.'+channel+'.0.exr'))).channels()['RGB'].pixels
    assert a.shape==(1080,1920,3) and np.isfinite(a).all()
    return a
mask=np.linalg.norm(read('mask','Visibility.normW'),axis=-1)>.5
ref=read('pt-a-'+str(args.spp));prev=read('pt-a-'+str(args.spp//2))
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
noise=mse(ref,prev)
errors={k:mse(read(k+'-65536'),ref) for k in ['ddgi','half','full']}
energy=float(np.mean(ref[mask].astype(np.float64)**2))
gate={'spp':args.spp,'reference_mode':'disjoint_halves','reference_noise_estimate':noise,
    'reference_noise_over_min_error':noise/min(errors.values()),
    'relative_rgb_rms_noise':float(np.sqrt(noise/energy)), 'method_mse':errors,
    'threshold_noise_over_error':.01,'threshold_relative_rgb_rms':.005,
    'independent_block_seed_ranges':[[1,args.spp//16],[args.spp//16+1,args.spp//8]],
    'note':'Doubling difference and disjoint-block noise are the same statistic, not independent checks.'}
gate['passed']=gate['reference_noise_over_min_error']<.01 and gate['relative_rgb_rms_noise']<.005
(D/('pt-gate-'+str(args.spp)+'.json')).write_text(json.dumps(gate,indent=2))
print(json.dumps(gate,indent=2))
if args.finalize:
    assert gate['passed'],'Reference did not pass the convergence gate'
    assert not (D/'failure.txt').exists()
    info=json.loads((D/'progress.json').read_text())
    assert all(k in info['runs'] for k in ['ddgi','half','full'])
    assert not (D/'complete.json').exists()
    info['planned_pt_total_spp']=info['pt_total_spp'];info['pt_total_spp']=args.spp
    info['reference_gate']=gate;info['reference_mode']='disjoint_halves'
    info['stage']='complete';info['completion_reason']='PT stopped externally after saved checkpoint passed the explicit convergence gate; all three GI runs and timing windows completed.'
    (D/'complete.json').write_text(json.dumps(info,indent=2))
