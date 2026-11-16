import ast,csv,hashlib,json,pathlib,shutil,subprocess,sys
sys.path.insert(0,'F:/build/official-ddgi/python-libs')
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
state=json.loads(pathlib.Path('F:/build/gi-evaluation-current.json').read_text());work=pathlib.Path(state['work']);root=pathlib.Path(state['result'])
official_dir=pathlib.Path('F:/docs/2026-11-16_12-04_NVIDIA-DDGI-vs-PT_CornellBox')
official=json.loads((official_dir/'summary.json').read_text());params=json.loads((official_dir/'manifest.json').read_text())['flip']['parameters']
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding='utf-8')
def read(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels.astype(np.float32)
 assert np.isfinite(a).all(),str(p)
 return np.ascontiguousarray(a)
def exr(p,a):OpenEXR.File({'compression':OpenEXR.ZIP_COMPRESSION},{'RGB' if a.ndim==3 else 'Y':np.ascontiguousarray(a,dtype=np.float32)}).write(str(p))
def score(ref,cand,mask):
 assert (ref>=0).all() and (cand>=0).all()
 err=flip_evaluator.evaluate(ref,cand,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 return float(err[mask].mean(dtype=np.float64)),float(np.square(cand[mask].astype(np.float64)-ref[mask]).mean()),err
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',23);small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
tree=ast.parse(pathlib.Path('F:/build/official-ddgi/python-libs/matplotlib/_cm_listed.py').read_text())
lut=np.array(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_magma_data' for t in n.targets)))
def cm(x):return lut[np.minimum((np.clip(x,0,1)*256).astype(int),255)]
def display(a):
 x=a*8;x=np.clip((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0,1);x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(np.clip(x,0,1)*255+.5))
def pictures(out,ref,cand,err,mask,score_value,label):
 canvas=Image.new('RGB',(1944,618),(23,26,31));d=ImageDraw.Draw(canvas)
 d.text((16,12),'Falcor DDGI | frame 16416 | Lambert approximation',font=font,fill='white');d.text((984,12),'Falcor PT | 32,768 spp | '+label,font=font,fill='white')
 canvas.paste(display(cand),(8,48));canvas.paste(display(ref),(976,48))
 d.text((16,593),f'Indirect diffuse | Same camera / lights / display (+3 EV, ACES, sRGB) | representative HDR-FLIP {score_value:.4f}',font=small,fill=(200,207,218));canvas.save(out/'comparison.png')
 heat=np.uint8(cm(err)*255+.5);heat[~mask]=(32,35,40)
 canvas=Image.new('RGB',(1100,618),(23,26,31));d=ImageDraw.Draw(canvas);d.text((16,12),'HDR-FLIP | '+label+' | fixed scale 0-1',font=font,fill='white');canvas.paste(Image.fromarray(heat),(8,48))
 gradient=np.repeat(np.linspace(1,0,480)[:,None],24,axis=1);canvas.paste(Image.fromarray(np.uint8(cm(gradient)*255+.5)),(986,70))
 for v in [0,.25,.5,.75,1]:d.text((1018,int(70+(1-v)*480)-10),f'{v:.2f}',font=small,fill='white')
 d.text((16,593),f'Masked mean {score_value:.4f} | PPD 67 | ACES | exposures {params["startExposure"]:.2f} to {params["stopExposure"]:.2f} EV',font=small,fill=(200,207,218));canvas.save(out/'flip-heatmap.png')
all_results={}
for case,prefix,label in [('native','','Frostbite + GGX'),('lambert-control','lambert-','Lambert control')]:
 out=root/case
 for sub in ['frames','reference','errors']: (out/sub).mkdir(parents=True,exist_ok=True)
 dd=work/(prefix+'ddgi');pt=work/(prefix+'pt-a');pb=work/(prefix+'pt-b')
 dr=json.loads((dd/'complete.json').read_text());pr=json.loads((pt/'complete.json').read_text())
 ref=read(pt/'frame-4096.Accumulate.output.0.exr');ind=read(pb/'frame-4096.Accumulate.output.0.exr')
 mask=np.linalg.norm(read(pt/'frame-4096.Visibility.normW.0.exr'),axis=2)>.5
 assert np.array_equal(mask,np.linalg.norm(read(dd/'frame-16416.Visibility.normW.0.exr'),axis=2)>.5)
 assert np.array_equal(mask,np.array(Image.open(official_dir/'mask.png'))>0)
 Image.fromarray(mask.astype('uint8')*255).save(out/'mask.png');exr(out/'reference/pt.exr',ref);exr(out/'reference/pt-independent.exr',ind)
 noise_f,noise_m,_=score(ref,ind,mask);half_f,half_m,_=score(ref,read(pt/'frame-2048.Accumulate.output.0.exr'),mask)
 elapsed={r['frame']:r['elapsed_seconds'] for r in dr['captures']};rows=[];lums=[]
 lum=lambda a:float((a[mask].astype(np.float64)@np.array([.2126,.7152,.0722])).mean())
 for i,frame in enumerate(range(16385,16417)):
  cand=read(dd/f'frame-{frame}.DDGI.indirect.0.exr');exr(out/f'frames/candidate-{i:04d}.exr',cand)
  f,m,err=score(ref,cand,mask);lums.append(lum(cand))
  rows.append(dict(capture_index=i,render_frame_id=frame,elapsed_seconds=elapsed[frame],candidate_path=f'frames/candidate-{i:04d}.exr',mean_hdr_flip=f,linear_rgb_mse=m,gi_gpu_ms='',valid_pixels=int(mask.sum()),status='valid',note='GPU timestamps captured separately after image capture'))
  if i%8==0:print(case,frame,f,flush=True)
 exr(out/'errors/flip-representative.exr',err)
 with (out/'metrics.csv').open('w',newline='',encoding='utf-8') as fp:
  writer=csv.DictWriter(fp,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 times=json.loads((dd/'timing.json').read_text());base='/onFrameRender/RenderGraphExe::execute()/DDGI'
 stages={name:times['events'][base+suffix+'/gpu_time'] for name,suffix in [('gi',''),('probe_update','/ProbeUpdate'),('probe_trace','/ProbeUpdate/OriginalTrace'),('sdk_update','/ProbeUpdate/SDKUpdate'),('screen_query','/raytraceScene')]}
 with (out/'timing.csv').open('w',newline='',encoding='utf-8') as fp:
  writer=csv.writer(fp);writer.writerow(['sample_index']+[n+'_gpu_ms' for n in stages]);writer.writerows([i]+[v['records'][i] for v in stages.values()] for i in range(times['frame_count']))
 mean_f=float(np.mean([r['mean_hdr_flip'] for r in rows]));mean_m=float(np.mean([r['linear_rgb_mse'] for r in rows]))
 steady={}
 for frame in [256,1024,4096,8192,16384]:
  a=read(dd/f'frame-{frame}.DDGI.indirect.0.exr');f,m,_=score(ref,a,mask);steady[str(frame)]={'mean_hdr_flip':f,'linear_rgb_mse':m,'mean_luminance':lum(a)}
 check={'spp_each':32768,'mean_hdr_flip':noise_f,'linear_rgb_mse':noise_m,'flip_fraction_of_candidate_error':noise_f/mean_f,'half_spp_vs_full':{'mean_hdr_flip':half_f,'linear_rgb_mse':half_m},'reliability':'Finite-sample reference, independent-sequence noise measured; not an exact infinite-bounce solution.'}
 limitations=['Static Cornell scene and one camera only; not a relocation flicker or moving-camera test.','20 surface vertices maximum, no RR; finite-path PT rather than infinite-bounce ground truth.','DDGI uses Lambertian albedo/pi. Native StandardMaterial PT uses Frostbite diffuse + GGX; Lambert control explicitly replaces materials in an isolated scene.','Official baseline uses a different point-light falloff, packed probe formats, relocation minimum distance, thresholds and warmup budget. Cross-engine comparison is descriptive, not a controlled integration pass/fail test.','FLIP exposures frozen from the previous official reference for a common viewing range, not refitted to each new scene variant.','Measured DDGI pass includes probe update, screen query and unavoidable pass overhead; excludes GBuffer, UI, file IO and PT.','16,384 warmup frames: checkpoint evolution recorded, no claim of exact convergence.']
 summary={'schema_version':'gi-evaluation-v1','run_id':state['run_id'],'case_id':case,'status':'complete','target_frame_count':32,'valid_frame_count':32,'invalid_frame_count':0,'mean_hdr_flip':mean_f,'linear_rgb_mse':mean_m,'gi_gpu_ms_mean':float(np.mean(stages['gi']['records'])),'timing_sample_count':times['frame_count'],'gpu_stage_ms':{n:float(np.mean(v['records'])) for n,v in stages.items()},'reference_check':check,'candidate_steady_check':steady,'luminance':{'reference':lum(ref),'candidate_mean_32_frames':float(np.mean(lums)),'relative_difference':float(np.mean(lums))/lum(ref)-1},'representative':{'capture_index':31,'render_frame_id':16416,'mean_hdr_flip':rows[-1]['mean_hdr_flip'],'linear_rgb_mse':rows[-1]['linear_rgb_mse'],'comparison':'comparison.png','heatmap':'flip-heatmap.png','error':'errors/flip-representative.exr'},'limitations':limitations}
 save(out/'summary.json',summary);pictures(out,ref,cand,err,mask,rows[-1]['mean_hdr_flip'],label)
 asset=pathlib.Path('F:/build/windows-vs2022/_deps/rtxgi_ddgi-src/samples/test-harness/data/gltf/cornell/cornell.glb')
 manifest={'schema_version':'gi-evaluation-v1','run_id':state['run_id'],'case_id':case,'created_at':state['created_at'],'status':'complete','comparison_project':'Falcor DDGI vs Falcor PT - '+label,'result_directory':str(out),'timezone':'Asia/Hong_Kong','candidate':{'name':'Falcor RTXGIDDGI','sdk':'1.3.7','git_commit':subprocess.check_output(['git','-C','F:/','rev-parse','HEAD'],text=True).strip(),'source_snapshot':'../reproduction/source-record.json','parameters':dr['options'],'random_seed':'Existing renderer sequence; saved host implementation in reproduction/source'},'reference':{'name':'Falcor PathTracer','parameters':pr['options'],'path':'reference/pt.exr','sha256':sha(out/'reference/pt.exr'),'spp':32768,'independent_path':'reference/pt-independent.exr','independent_sha256':sha(out/'reference/pt-independent.exr'),'seed':'fixedSeed=frame (1..4096), second sequence frame+104729; 8 samples/pixel/frame','check':check,'measurement_patch':'../reproduction/pt-indirect.patch'},'scene':{'asset':str(asset),'sha256':sha(asset),'configuration':'../reproduction/scene.json','material':label,'control_scene':'../reproduction/lambert.pyscene' if prefix else None,'environment':'disabled / black','lighting':'Falcor native ceiling point, white intensity 1 at (0,1.9,0); directional disabled'},'camera':dict(pr['camera'],vertical_fov_degrees=45,pixel_sampling='Center; no DOF; clock paused; camera animation disabled',near_plane=None,far_plane=None),'signal':{'name':'indirect_diffuse_radiance','definition':'DDGI.indirect, and PT nrdDiffuseRadianceHitDist with useNRDDemodulation=False after suppressing only primary-hit direct/emission. Primary albedo/BRDF included; camera specular omitted. Later bounces use each renderer material model.','color_space':'linear RGB, scene working sRGB primaries','scale':'native radiance; no fitting or normalization'},'image':{'width':960,'height':540,'format':'OpenEXR float32 RGB ZIP','mask':'mask.png','mask_sha256':sha(out/'mask.png'),'valid_pixels':int(mask.sum()),'mask_definition':'PT GBufferRT normW length > 0.5; exactly matches DDGI and official geometry mask','nonfinite_values':0,'negative_rgb_values':0},'display':{'exposure_ev':3,'tone_mapper':'ACES fitted','transfer':'standard sRGB','shared':True},'flip':{'implementation':'NVIDIA flip-evaluator','version':'1.7','mode':'HDR','parameters':params,'input_clamp':'none; finite nonnegative asserted','reduction':'full image FLIP then fixed mask mean','error_channel':'Y','legend':[0,1]},'capture':{'warmup_frames':16384,'warmup_seconds':elapsed[16384],'target_frame_count':32,'actual_frame_count':32,'frame_ids':[16385,16416],'representative_index':31,'fixed_budget_test':True,'stability_check':steady},'timing':{'tool':'Falcor GPU profiler D3D12 timestamps','gpu':'NVIDIA GeForce RTX 5080','driver':'617.14','sample_count':times['frame_count'],'path':'timing.csv','scope':'DDGI pass aggregate; stages overlap with aggregate, do not sum','method':'16 frames profiler warmup then 512 render calls, profiler returned 511 complete intervals; after readback captures'},'reproduction':{'work_directory':str(work),'runtime':str(work/'runtime/Mogwai.exe'),'script':'../reproduction/capture.py','instructions':'../reproduction/README.md'},'limitations':limitations+['Camera near/far clip values not exported; GBufferRT center rays and surface mask agree exactly with baseline.']}
 save(out/'manifest.json',manifest);all_results[case]=summary
 print(case,json.dumps({k:summary[k] for k in ['mean_hdr_flip','linear_rgb_mse','gi_gpu_ms_mean','luminance','reference_check']}),flush=True)
save(root/'summary.json',{'status':'complete','cases':all_results,'official_baseline':str(official_dir),'official_summary':official})
save(root/'manifest.json',dict(state,schema_version='gi-evaluation-v1',status='complete',cases={k:k+'/manifest.json' for k in all_results},timezone='Asia/Hong_Kong'))
