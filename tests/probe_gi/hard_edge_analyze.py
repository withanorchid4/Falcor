"""Visualize linear diagnostic captures; preserve numeric samples and normalization scales."""
import argparse, json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('output',type=Path); ap.add_argument('--ray-run',type=Path)
    args=ap.parse_args(); out=args.output
    meta=json.loads((out/'diagnostic-identity.json').read_text()); case=Path(meta['snapshot'])
    if not case.exists(): case=Path(__file__).resolve().parents[2]/'build/probe-issues'/case.name
    data=json.loads((case/'snapshot.json').read_text()); w,h=data['resolution']
    def load(p): return np.fromfile(p,dtype='<f4').reshape(h,w,3)
    a={g:np.stack([load(out/f'g{g}-c{c}.f32') for c in range(8 if g<7 else 1)]) for g in range(10)}
    assert all(np.isfinite(v).all() for v in a.values())
    preview=out/'analysis'; preview.mkdir(exist_ok=True)
    def im(v):
        if v.ndim==2: v=np.repeat(v[:,:,None],3,axis=2)
        return Image.fromarray(np.uint8(np.clip(v,0,1)*255+.5))
    def grid(values,name,lo=0,hi=1):
        canvas=Image.new('RGB',(1280,400),(24,24,24)); draw=ImageDraw.Draw(canvas)
        for c,v in enumerate(values):
            panel=im((v-lo)/(hi-lo)).resize((320,180))
            x,y=c%4*320,c//4*200; canvas.paste(panel,(x,y+20))
            draw.text((x+4,y+3),f'corner {c}: ({c&1},{(c>>1)&1},{(c>>2)&1})  [{lo:.3g}, {hi:.3g}]',fill='white')
        canvas.save(preview/(name+'.png'))
    grid(a[0][:,:,:,0],'01-final-weight'); grid(a[0][:,:,:,2],'02-visibility')
    grid(a[1][:,:,:,0],'03-trilinear'); grid(a[1][:,:,:,1],'04-normal-weight',0,1.2)
    grid(np.log10(np.maximum(a[2][:,:,:,1],1e-8)),'05-log10-variance',-6,0)
    grid(a[2][:,:,:,2]-a[2][:,:,:,0],'06-distance-minus-mean',-.1,.1)
    grid(a[5]@np.array([.2126,.7152,.0722]),'07-weighted-irradiance',0,1)
    grid(a[6][:,:,:,1],'08-ray-visible')
    im(a[8][0]*.5+.5).save(preview/'normal.png'); im(a[9][0]).save(preview/'albedo.png')
    im(a[1][0,:,:,2]).save(preview/'total-weight.png')
    baseline=load(case/'baseline/hdr.f32'); replay=load(out/'baseline/hdr.f32')
    reconstructed=np.maximum(a[5].sum(axis=0),0)*a[9][0]/np.pi*data['probeSettings']['intensity']
    wall=(a[7][0,:,:,2]>-.02)&(a[7][0,:,:,2]<.02)&(np.abs(a[8][0,:,:,2])>.99)
    errors={'baseline_max_abs':float(np.max(np.abs(baseline-replay))),
        'wall_pixels':int(wall.sum()),'wall_reconstruction_max_abs':float(np.max(np.abs(reconstructed[wall]-baseline[wall]))),
        'wall_normal_min':a[8][0][wall].min(axis=0).tolist(),'wall_normal_max':a[8][0][wall].max(axis=0).tolist(),
        'wall_albedo_min':a[9][0][wall].min(axis=0).tolist(),'wall_albedo_max':a[9][0][wall].max(axis=0).tolist(),
        'wall_sum_weight_range':[float(a[1][0,:,:,2][wall].min()),float(a[1][0,:,:,2][wall].max())]}
    # Strong adjacent HDR gradients inside the three user-marked boxes.
    luma=baseline@np.array([.2126,.7152,.0722]); regions={'upper':[760,65,995,245],'left':[385,280,580,520],'middle':[730,285,985,510]}
    samples={}
    for name,(x0,y0,x1,y1) in regions.items():
        candidates=[]
        for dx,dy in ((1,0),(0,1)):
            for y in range(y0,y1):
                for x in range(x0,x1):
                    if wall[y,x] and wall[y+dy,x+dx]: candidates.append((abs(luma[y+dy,x+dx]-luma[y,x]),x,y,dx,dy))
        candidates.sort(reverse=True); picked=[]
        for diff,x,y,dx,dy in candidates:
            if all(abs(x-p[1])+abs(y-p[2])>20 for p in picked): picked.append((diff,x,y,dx,dy))
            if len(picked)==5: break
        records=[]
        for diff,x,y,dx,dy in picked:
            def point(x,y):
                return {'pixel':[x,y],'hdr':baseline[y,x].tolist(),'position':a[7][0,y,x].tolist(),
                    'normal':a[8][0,y,x].tolist(),'albedo':a[9][0,y,x].tolist(),
                    'probes':[{'id':int(a[3][c,y,x,0]),'w':float(a[0][c,y,x,0]),'raw':float(a[0][c,y,x,1]),
                        'V':float(a[0][c,y,x,2]),'tri':float(a[1][c,y,x,0]),'normalWeight':float(a[1][c,y,x,1]),
                        'totalWeight':float(a[1][c,y,x,2]),'mean':float(a[2][c,y,x,0]),'variance':float(a[2][c,y,x,1]),
                        'd':float(a[2][c,y,x,2]),'uv':a[3][c,y,x,1:].tolist(),'E':a[4][c,y,x].tolist(),
                        'weightedE':a[5][c,y,x].tolist(),'hit':float(a[6][c,y,x,0]),'ray':float(a[6][c,y,x,1])} for c in range(8)]}
            records.append({'luminance_difference':float(diff),'a':point(x,y),'b':point(x+dx,y+dy)})
        samples[name]=records
    (preview/'checks.json').write_text(json.dumps(errors,indent=2)); (preview/'edge-samples.json').write_text(json.dumps(samples,indent=2))
    # Fixed IDs avoid the cell-dependent corner discontinuities in the eight-slot overview.
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',16)
    columns=[('Upper / Probe 382',382,(735,65,1035,265)),('Left / Probe 375',375,(350,280,650,480)),
        ('Middle / Probe 374',374,(715,285,1015,485))]
    rows=['Original display','Final weight [0, 0.06]','Visibility [0, 1]','log10 variance, world units [-5, -1]','d - mean [-0.03, 0.03]']
    canvas=Image.new('RGB',(900,5*230+30),(24,24,24)); draw=ImageDraw.Draw(canvas)
    original=Image.open(case/'baseline/display.png').convert('RGB')
    for col,(label,id,box) in enumerate(columns):
        draw.text((col*300+5,5),label,font=font,fill='white')
        mask=a[3][:,:,:,0]==id
        values=[original,im((a[0][:,:,:,0]*mask).sum(0)/.06),im((a[0][:,:,:,2]*mask).sum(0)),
            im((np.log10(np.maximum((a[2][:,:,:,1]*mask).sum(0),1e-8))+5)/4),
            im((( (a[2][:,:,:,2]-a[2][:,:,:,0])*mask).sum(0)+.03)/.06)]
        for row,value in enumerate(values):
            y=30+row*230; draw.text((col*300+3,y),rows[row],font=font,fill='white')
            canvas.paste(value.crop(box),(col*300,y+25))
    canvas.save(preview/'fixed-probe-breakdown.png')
    # Reconstruct the four actual cache taps at the strongest adjacent-pixel edges.
    lines=(case/'probes.shprobe').read_text().splitlines(); marker=lines.index('DISTANCE_MOMENTS')
    config=lines[6].split(); res=int(config[1]); aw,ah=int(config[4]),int(config[5]); tile=res+2
    atlas=np.loadtxt(lines[marker+1:]).reshape(ah,aw,2)
    bounds=np.array([float(x) for x in lines[5].split()]); counts=np.array(data['probeSettings']['gridCounts'])
    D=data['probeSettings']['distanceRangeScale']*np.linalg.norm((bounds[3:]-bounds[:3])/(counts-1))
    def wrap(x,y):
        if x<0: x,y=0,res-1-y
        elif x>=res: x,y=res-1,res-1-y
        if y<0: x,y=res-1-x,0
        elif y>=res: x,y=res-1-x,res-1
        return int(x),int(y)
    taps_report={}
    for region,id in [('upper',382),('left',375),('middle',374)]:
        taps_report[region]=[]
        for side in ('a','b'):
            point=samples[region][0][side]; q=next(p for p in point['probes'] if p['id']==id)
            p=np.array(q['uv'])*res-.5; base=np.floor(p).astype(int); t=p-base; taps=[]
            for dx,dy in ((0,0),(1,0),(0,1),(1,1)):
                x,y=wrap(base[0]+dx,base[1]+dy); m=atlas[(id//(aw//tile))*tile+1+y,(id%(aw//tile))*tile+1+x]
                wt=float((t[0] if dx else 1-t[0])*(t[1] if dy else 1-t[1]))
                taps.append({'xy':[x,y],'weight':wt,'mean':float(m[0]*D),'second':float(m[1]*D*D),
                    'variance':float(max(0,m[1]-m[0]**2)*D*D)})
            mean=sum(v['weight']*v['mean'] for v in taps)
            within=sum(v['weight']*v['variance'] for v in taps); between=sum(v['weight']*(v['mean']-mean)**2 for v in taps)
            assert abs(mean-q['mean'])<1e-5 and abs(within+between-q['variance'])<1e-5
            taps_report[region].append({'pixel':point['pixel'],'id':id,'uv':q['uv'],'taps':taps,
                'variance_within_texels':within,'variance_between_texels':between,'variance_total':within+between,
                'base_variance_world':float(D*D*data['probeSettings']['varianceBase']),
                'GPUvariance':q['variance'],'GPUmean':q['mean'],'CPUmean':mean})
    (preview/'taps.json').write_text(json.dumps(taps_report,indent=2))
    attribution={}
    for region,id in [('upper',382),('left',375),('middle',374)]:
        record=samples[region][0]
        pa,pb=[next(p for p in record[side]['probes'] if p['id']==id) for side in ('a','b')]
        def V(d,mean,var):
            effective=var+D*D*data['probeSettings']['varianceBase']
            return (effective/(effective+max(d-mean,0)**2))**data['probeSettings']['visibilityPower']
        attribution[region]={'id':id,'V_A':pa['V'],'V_B':pb['V'],
            'change_only_d':V(pb['d'],pa['mean'],pa['variance']),
            'change_only_mean':V(pa['d'],pb['mean'],pa['variance']),
            'change_only_variance':V(pa['d'],pa['mean'],pb['variance']),
            'all_B_reconstructed':V(pb['d'],pb['mean'],pb['variance'])}
    (preview/'visibility-factor-attribution.json').write_text(json.dumps(attribution,indent=2))
    if args.ray_run:
        ray=load(args.ray_run/'hdr.f32'); ray_luma=ray@np.array([.2126,.7152,.0722]); comparison={}
        for region,records in samples.items():
            record=records[0]; x,y=record['a']['pixel']; xx,yy=record['b']['pixel']
            comparison[region]={'pixels':[[x,y],[xx,yy]],'original_difference':record['luminance_difference'],
                'ray_difference':float(abs(ray_luma[yy,xx]-ray_luma[y,x]))}
        (preview/'ray-reference-check.json').write_text(json.dumps(comparison,indent=2))
        canvas=Image.new('RGB',(1280,390),(24,24,24)); draw=ImageDraw.Draw(canvas)
        draw.text((10,5),'Original: distance moments',font=font,fill='white')
        draw.text((650,5),'Diagnostic reference: ray visibility (same cache)',font=font,fill='white')
        canvas.paste(original.resize((640,360)),(0,30))
        canvas.paste(Image.open(args.ray_run/'display.png').resize((640,360)),(640,30))
        canvas.save(preview/'original-vs-ray.png')
    print(json.dumps(errors,indent=2))

if __name__=='__main__': main()
