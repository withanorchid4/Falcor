from pathlib import Path
import numpy as np,json,sys
R=Path(__file__).resolve().parents[2];D=R/'build/emerald-coverage'
sys.path.insert(0,str(R/'build/final-gather-python'));import OpenEXR
sys.path.insert(0,str(R/'build/convergence-python'));import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt

def read(n):
 c=OpenEXR.File(str(D/n)).channels();return c['RGBA' if 'RGBA' in c else 'RGB'].pixels[...,:3]
p=read('coverage.Visibility.posW.0.exr');n=read('coverage.Visibility.normW.0.exr');mask=np.linalg.norm(n,axis=-1)>.5;v=p[mask]
lo=np.array([-120,-6,-120]);hi=np.array([120,114,120])
result={'source':'GBufferRT world positions at 1920x1080, fixed official camera','visible_surface_pixels':int(mask.sum()),'visible_inside_fraction':float(np.all((v>=lo)&(v<=hi),axis=1).mean()),'visible_bounds':[v.min(axis=0).tolist(),v.max(axis=0).tolist()],'visible_y_below_20_fraction':float((v[:,1]<20).mean()),'preview_grid':[32,16,32],'experiment_grid':[32,32,32],'grid_min':lo.tolist(),'grid_max':hi.tolist(),'experiment_spacing':((hi-lo)/31).tolist(),'note':'Bounding-box coverage only; does not certify usable probes, visibility interpolation or secondary-hit coverage.'}
for name,counts in [('coarse',[32,16,32]),('experiment',[32,32,32])]:
 spacing=(hi-lo)/(np.array(counts)-1);q=np.round((v-lo)/spacing)*spacing+lo;dist=np.linalg.norm(q-v,axis=1)
 result[name+'_nearest_unrelocated_distance_percentiles']=np.percentile(dist,[50,95,99,100]).tolist()
(D/'coverage.json').write_text(json.dumps(result,indent=2),encoding='utf8')
fig,axes=plt.subplots(1,2,figsize=(14,6),layout='constrained');pts=v[::80]
for ax,dims,title in [(axes[0],(0,2),'Top view: complete-city probe footprint'),(axes[1],(2,1),'Side view: vertical probe spacing')]:
 a,b=dims;ax.scatter(pts[:,a],pts[:,b],s=1,alpha=.12,label='Visible surfaces')
 for value in np.linspace(lo[a],hi[a],32):ax.axvline(value,color='orange',alpha=.18,lw=.5)
 for value in np.linspace(lo[b],hi[b],32):ax.axhline(value,color='orange',alpha=.25,lw=.5)
 ax.scatter([[-38.370411,1.460394,75.721542][a]],[[-38.370411,1.460394,75.721542][b]],marker='*',color='red',s=100,label='Camera')
 ax.set(xlabel='XYZ'[a]+' (m)',ylabel='XYZ'[b]+' (m)',title=title);ax.legend();ax.set_aspect('equal')
fig.savefig(D/'coverage.png',dpi=160);plt.close(fig)
print(json.dumps(result))
