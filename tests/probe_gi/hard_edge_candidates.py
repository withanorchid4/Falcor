"""Screen reconstruction changes using captured GPU geometry, SH and ray visibility."""
from pathlib import Path
import json, sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from probe_snapshot import png

def main():
    case=ROOT/'build/probe-issues/20260924-021543-642825'
    source=ROOT/'build/probe-hard-edge-diagnosis-03'
    out=ROOT/'build/probe-hard-edge-candidates'; out.mkdir(exist_ok=True)
    meta=json.loads((case/'snapshot.json').read_text()); w,h=meta['resolution']
    def load(g,c): return np.fromfile(source/f'g{g}-c{c}.f32',dtype='<f4').reshape(h,w,3)
    positions=load(7,0); normal=load(8,0); albedo=load(9,0)
    ids=np.stack([load(3,c)[:,:,0].astype(int) for c in range(8)])
    uv=np.stack([load(3,c)[:,:,1:] for c in range(8)])
    tri=np.stack([load(1,c)[:,:,0] for c in range(8)])
    facing=np.stack([load(1,c)[:,:,1] for c in range(8)])
    d=np.stack([load(2,c)[:,:,2] for c in range(8)])
    sh=np.stack([load(4,c) for c in range(8)])
    ray=np.stack([load(6,c)[:,:,1] for c in range(8)])
    baseline=np.fromfile(case/'baseline/hdr.f32',dtype='<f4').reshape(h,w,3)
    reference=np.fromfile(case/'runs/20260924-023100-9a017f/hdr.f32',dtype='<f4').reshape(h,w,3)
    lines=(case/'probes.shprobe').read_text().splitlines(); marker=lines.index('DISTANCE_MOMENTS')
    atlas=np.loadtxt(lines[marker+1:],dtype=np.float32).reshape(320,320,2)
    bounds=np.fromstring(lines[5],sep=' ',dtype=np.float32); counts=np.array([8,6,8]); spacing=(bounds[3:]-bounds[:3])/(counts-1)
    D=np.float32(2*np.linalg.norm(spacing)); base=np.float32(meta['probeSettings']['varianceBase'])
    probe_grid=np.stack([ids%8,(ids//8)%6,ids//48],axis=-1)
    direction=bounds[:3]+probe_grid*spacing-positions
    cosine=(direction*normal).sum(-1)/np.maximum(np.linalg.norm(direction,axis=-1),1e-8)
    gate=np.clip(cosine/.2,0,1); gate=gate*gate*(3-2*gate)
    res=14
    def wrap(x,y):
        x=x.copy(); y=y.copy()
        mask=x<0; x[mask]=0; y[mask]=res-1-y[mask]
        mask=x>=res; x[mask]=res-1; y[mask]=res-1-y[mask]
        mask=y<0; y[mask]=0; x[mask]=res-1-x[mask]
        mask=y>=res; y[mask]=res-1; x[mask]=res-1-x[mask]
        return x,y
    def fetch(atlas,ids,x,y):
        x,y=wrap(x,y); return atlas[(ids//20)*16+1+y,(ids%20)*16+1+x]
    def sample(atlas,smooth):
        p=uv*res-.5; b=np.floor(p).astype(int); t=p-b
        if smooth: t=t*t*(3-2*t)
        a=fetch(atlas,ids,b[:,:,:,0],b[:,:,:,1]); b1=fetch(atlas,ids,b[:,:,:,0]+1,b[:,:,:,1])
        c=fetch(atlas,ids,b[:,:,:,0],b[:,:,:,1]+1); e=fetch(atlas,ids,b[:,:,:,0]+1,b[:,:,:,1]+1)
        tx,ty=t[:,:,:,0,None],t[:,:,:,1,None]
        return (a*(1-tx)+b1*tx)*(1-ty)+(c*(1-tx)+e*tx)*ty
    def filtered(atlas):
        result=atlas.copy(); yy,xx=np.mgrid[:14,:14]
        for i in range(384):
            total=np.zeros((14,14,2))
            for dy,wy in [(-1,.125),(0,.75),(1,.125)]:
                for dx,wx in [(-1,.125),(0,.75),(1,.125)]: total+=wx*wy*fetch(atlas,i,xx+dx,yy+dy)
            result[(i//20)*16+1:(i//20)*16+15,(i%20)*16+1:(i%20)*16+15]=total
        return result
    rois={'upper':(760,65,995,245),'left':(385,280,580,520),'middle':(730,285,985,510)}
    wall=(np.abs(positions[:,:,2])<.02)&(normal[:,:,2]<-.99)
    results={}
    for name,smooth,blur,hemi in [('original',False,False,False),('smooth',True,False,False),
        ('prefilter',False,True,False),('smooth_prefilter',True,True,False),('hemisphere',False,False,True),('smooth_hemisphere',True,False,True)]:
        moments=sample(filtered(atlas) if blur else atlas,smooth)
        variance=np.maximum(moments[:,:,:,1]-moments[:,:,:,0]**2,0)
        delta=np.maximum(d/D-moments[:,:,:,0],0)
        vis=((variance+base)/(variance+base+delta**2))**3
        raw=tri*facing*vis*(gate if hemi else 1)
        weights=raw/np.maximum(raw.sum(0),1e-4)
        image=np.maximum((sh*weights[:,:,:,None]).sum(0),0)*albedo/np.pi
        np.save(out/(name+'.npy'),image)
        lum=image@np.array([.2126,.7152,.0722]); report={}
        for region,(x0,y0,x1,y1) in rois.items():
            sl=np.s_[y0:y1,x0:x1]; l=lum[sl]
            report[region]={'mae_to_ray':float(abs(image[sl]-reference[sl]).mean()),
                'max_adjacent_luma':float(max(abs(np.diff(l,axis=0)).max(),abs(np.diff(l,axis=1)).max())),
                'mean_blocked_weight':float((weights*(1-ray))[:,y0:y1,x0:x1].sum(0).mean())}
        report['wall_mae_to_ray']=float(abs(image[wall]-reference[wall]).mean())
        report['min_total_weight_wall']=float(raw.sum(0)[wall].min())
        if name=='original': report['GPU_reconstruction_max_error']=float(abs(image[wall]-baseline[wall]).max())
        results[name]=report
        print(name,json.dumps(report),flush=True)
    (out/'metrics.json').write_text(json.dumps(results,indent=2))

if __name__=='__main__': main()
