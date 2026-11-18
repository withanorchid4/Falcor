from pathlib import Path
import sys,json,os
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR
DATA=Path(os.environ.get('NRD_TUNING_OUT',ROOT/'build/nrd-half-tuning'));OLD=ROOT/'build/three-way-half-gather'
info=json.loads((DATA/'complete.json').read_text());assert not (DATA/'failure.txt').exists()
assert '(Error)' not in Path(str(DATA)+'.log').read_text(errors='replace')
def read(p):
    a=OpenEXR.File(str(p)).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all(),p
    return a
def audit(ch):return read(ROOT/'build/nrd-half-tuning'/('audit.'+ch+'.0.exr'))
target=read(ROOT/'build/accumulated-gather-comparison/half-65536.Accumulate.output.0.exr')
pt=read(OLD/'reference-65536spp.exr')
mask=np.linalg.norm(read(OLD/'pt-a-32768.Visibility.normW.0.exr'),axis=-1)>.5
def mse(a,b):return float(np.mean((a[mask].astype(float)-b[mask])**2))
rows={}
for name in info['variants']:
    images=np.array([read(DATA/(name+'-'+str(i)+'.Reconstruct.color.0.exr')) for i in range(32)])
    mean=images.mean(axis=0)
    rows[name]={'mse_to_accumulate':float(np.mean([mse(a,target) for a in images])),
        'mean_image_mse_to_accumulate':mse(mean,target),'mse_to_pt':float(np.mean([mse(a,pt) for a in images])),
        'temporal_variance':float(np.var(images[:,mask].astype(float),axis=0).mean()),
        'mean_rgb':float(mean[mask].mean()),'parameters':info['variants'][name]}
    assert info['resets'][name]==0
    assert info[name+'_stats']['finite']
raw=audit('RawReconstruct.color');bypass=audit('Reconstruct.color')
checks={'bypass_relative_l1':float(np.abs(raw-bypass).sum()/max(np.abs(raw).sum(),1e-12)),
    'half_depth_max_error':float(np.abs(audit('Guides.halfDepth')-audit('Visibility.linearZ')[::2,::2]).max()),
    'half_motion_max_error':float(np.abs(audit('Guides.halfMotion')-audit('Visibility.mvecW')[::2,::2]).max()),
    'static_world_motion_max':float(np.abs(audit('Guides.halfMotion')).max()),
    'demodulated_diffuse_max':float(audit('DDGI.diffuseRadianceHitDist').max()),
    'lambert_specular_max':float(np.abs(audit('DDGI.specularRadianceHitDist')).max())}
enc=audit('Guides.halfNormalRoughness')[:,:,:2]*2-1
n=np.concatenate([enc,1-np.abs(enc).sum(axis=-1,keepdims=True)],axis=-1)
flip=n[:,:,2]<0
n[:,:,:2]=np.where(flip[:,:,None],(1-np.abs(n[:,:,1::-1]))*np.where(n[:,:,:2]>=0,1,-1),n[:,:,:2])
n/=np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-8)
valid=mask[::2,::2]
checks['decoded_guide_normal_max_error']=float(np.abs(n[valid]-audit('Visibility.normW')[::2,::2][valid]).max())
assert checks['bypass_relative_l1']<.001
assert checks['half_depth_max_error']==0 and checks['half_motion_max_error']==0
assert checks['decoded_guide_normal_max_error']<.01
assert checks['demodulated_diffuse_max']<10000 and checks['lambert_specular_max']==0
result={'variants':rows,'integration_checks':checks,'target_mean_rgb':float(target[mask].mean()),'capture':info}
(DATA/'scores.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'ranked':sorted(rows.items(),key=lambda pair:pair[1]['mse_to_accumulate']),'checks':checks},indent=2))
