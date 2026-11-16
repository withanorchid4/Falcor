"""Score captured official Test Harness linear buffers; no rendering algorithm edits."""
import csv, hashlib, json, pathlib, struct, sys
sys.path.insert(0, 'F:/build/official-ddgi/python-libs')
import numpy as np
import OpenEXR
import flip_evaluator
from PIL import Image, ImageDraw, ImageFont

state = json.loads(pathlib.Path('F:/build/official-ddgi/evaluation-current.json').read_text(encoding='utf-8-sig'))
work, out = pathlib.Path(state['work']), pathlib.Path(state['result'])
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save_json(p, x): p.write_text(json.dumps(x, indent=2, ensure_ascii=False), encoding='utf-8')
def raw(p):
    data = p.read_bytes()
    w,h,fmt,rowbytes = struct.unpack('<4I', data[:16])
    dtype = {10:'<f2', 2:'<f4'}[fmt]
    assert rowbytes == w * 4 * np.dtype(dtype).itemsize
    a = np.frombuffer(data[16:], dtype=dtype).reshape(h,w,4).astype(np.float32)
    assert np.isfinite(a).all(), p
    return a
def rgb(p, pt=False):
    a = raw(p)
    if pt:
        assert np.all(a[:,:,3] == a[0,0,3]) and a[0,0,3] > 0
        a[:,:,:3] /= a[:,:,3:]
    v = np.ascontiguousarray(a[:,:,:3])
    assert (v >= 0).all(), p
    return v
def exr(p, a):
    channels = {'RGB':np.ascontiguousarray(a,dtype=np.float32)} if a.ndim==3 else {'Y':np.ascontiguousarray(a,dtype=np.float32)}
    OpenEXR.File({'compression':OpenEXR.ZIP_COMPRESSION}, channels).write(str(p))
def score(ref, cand):
    error,_,_ = flip_evaluator.evaluate(ref,cand,'HDR',applyMagma=False,parameters=params.copy())
    error = error[:,:,0]
    return float(error[mask].mean(dtype=np.float64)),float(np.square(cand[mask].astype(np.float64)-ref[mask]).mean()),error

ref = rgb(work/'pt-a/capture/frame-32769.raw', True)
independent = rgb(work/'pt-b/capture/frame-32769.raw', True)
mask = raw(work/'ddgi-final/capture/gbuffer-position.raw')[:,:,3] >= 0
Image.fromarray(mask.astype('uint8')*255).save(out/'mask.png')
exr(out/'reference/pt.exr',ref)
exr(out/'reference/pt-independent.exr',independent)
params = json.loads((work/'flip-parameters.json').read_text())
noise_flip, noise_mse, _ = score(ref,independent)
half = rgb(work/'pt-a/capture/frame-16385.raw',True)
half_flip, half_mse, _ = score(ref,half)
rows=[]
for i,frame in enumerate(range(65537,65569)):
    cand=rgb(work/f'ddgi-final/capture/frame-{frame}.raw')
    path=f'frames/candidate-{i:04d}.exr'
    exr(out/path,cand)
    f,m,err=score(ref,cand)
    rows.append(dict(capture_index=i,render_frame_id=frame,elapsed_seconds='',candidate_path=path,mean_hdr_flip=f,linear_rgb_mse=m,gi_gpu_ms='',valid_pixels=int(mask.sum()),status='valid',note='Timing measured in preceding steady-state frames; wall-clock frame time not captured'))
    print(f'Frame {frame}: HDR-FLIP={f:.6f}, MSE={m:.9g}',flush=True)
exr(out/'errors/flip-representative.exr',err)
with (out/'metrics.csv').open('w',newline='',encoding='utf-8') as fp:
    writer=csv.DictWriter(fp,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

# GPU timestamp intervals from the sample, excluding all readback checkpoints.
with (work/'ddgi-final/capture/gpu-timing.csv').open() as fp:
    timing=[r for r in csv.DictReader(fp) if 14350<=int(r['frame'])<=16370 and float(r['DDGI'])>0]
with (out/'timing.csv').open('w',newline='',encoding='utf-8') as fp:
    writer=csv.DictWriter(fp,fieldnames=list(timing[0]));writer.writeheader();writer.writerows(timing)
gpu=float(np.mean([float(r['DDGI']) for r in timing]))
stages={k.strip():float(np.mean([float(r[k]) for r in timing])) for k in ['  Probe Trace','  Blend','  Relocate','  Classify','  Lighting','GBuffer','Frame']}
with (work/'pt-a/capture/gpu-timing.csv').open() as fp:
    pt_times=[float(r['Path Tracing']) for r in csv.DictReader(fp) if 14350<=int(r['frame'])<=16370 and float(r['Path Tracing'])>0]
mean_flip=float(np.mean([r['mean_hdr_flip'] for r in rows]));mean_mse=float(np.mean([r['linear_rgb_mse'] for r in rows]))
steady={}
for frame in [513,1025,2049,4097,8193,16385,32769,65537]:
    a=rgb(work/f'ddgi-final/capture/frame-{frame}.raw')
    f,m,_=score(ref,a)
    steady[str(frame)]={'mean_hdr_flip':f,'linear_rgb_mse':m,'mean_luminance':float((a[mask]@np.array([.2126,.7152,.0722])).mean())}
lum_ref=float((ref[mask]@np.array([.2126,.7152,.0722])).mean())
lum_cand=float((cand[mask]@np.array([.2126,.7152,.0722])).mean())
reference_check={'spp_each':32768,'independent_seed_frame_offset':104729,'mean_hdr_flip':noise_flip,'linear_rgb_mse':noise_mse,'flip_fraction_of_candidate_error':noise_flip/mean_flip,'half_spp_vs_full':{'spp':16384,'mean_hdr_flip':half_flip,'linear_rgb_mse':half_mse},'reliability':'Independent-reference error is measured and compared with candidate error; finite-sample PT is not an exact solution.'}

# Fixed shared visualization: ACES fitted curve, +3 EV, standard sRGB OETF.
display_ev=3.0
def display(a):
    x=a*(2**display_ev)
    x=np.clip((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(np.clip(x,0,1)*255+.5))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',23)
small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',18)
canvas=Image.new('RGB',(1944,618),(23,26,31));draw=ImageDraw.Draw(canvas)
draw.text((16,12),'Official DDGI | frame 65568 | 9 x 9 x 9 probes',font=font,fill='white')
draw.text((984,12),'Official Path Tracer | 32,768 spp | indirect diffuse',font=font,fill='white')
canvas.paste(display(cand),(8,48));canvas.paste(display(ref),(976,48))
draw.text((16,593),f'Same camera / lights / display (+3 EV, ACES, sRGB)   |   representative HDR-FLIP {rows[-1]["mean_hdr_flip"]:.4f}   |   black background excluded from scores',font=small,fill=(200,207,218))
canvas.save(out/'comparison.png')

# Standard Matplotlib Magma LUT, loaded as data (no plotting GUI dependencies).
import ast
tree=ast.parse(pathlib.Path('F:/build/official-ddgi/python-libs/matplotlib/_cm_listed.py').read_text(encoding='utf-8'))
lut=np.array(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_magma_data' for t in n.targets)))
def cm(x): return lut[np.minimum((np.clip(x,0,1)*256).astype(int),255)]
heat=np.uint8(cm(np.clip(err,0,1))[:,:,:3]*255+.5);heat[~mask]=(32,35,40)
hcanvas=Image.new('RGB',(1100,618),(23,26,31));hd=ImageDraw.Draw(hcanvas)
hd.text((16,12),'HDR-FLIP | DDGI frame 65568 vs PT | fixed scale 0-1',font=font,fill='white')
hcanvas.paste(Image.fromarray(heat),(8,48))
gradient=np.repeat(np.linspace(1,0,480)[:,None],24,axis=1)
hcanvas.paste(Image.fromarray(np.uint8(cm(gradient)[:,:,:3]*255+.5)),(986,70))
for v in [0,.25,.5,.75,1]: hd.text((1018,int(70+(1-v)*480)-10),f'{v:.2f}',font=small,fill='white')
hd.text((16,593),f'Masked mean {rows[-1]["mean_hdr_flip"]:.4f} | PPD 67 | ACES | exposures {params["startExposure"]:.2f} to {params["stopExposure"]:.2f} EV | {params["numExposures"]} samples',font=small,fill=(200,207,218))
hcanvas.save(out/'flip-heatmap.png')

limitations=[
 'Static Cornell Box, one camera and one ceiling point light only; no dynamic stability conclusion.',
 'After 65,536 warmup frames, checkpoint HDR-FLIP still changes by about 0.001 over the last doubling. This is a bounded long-warmup, near-steady snapshot, not proof of exact convergence.',
 'Measurement patch exports linear float textures, suppresses bounce-0 direct contribution in PT, and changes only the second PT random sequence. Official DDGI SDK and DDGI shaders are unchanged.',
 'PT uses official 20-bounce cap, maxAlbedo=0.9 and throughput termination 0.005; reference is the official finite-path model, not an infinite-bounce physical truth.',
 'Official DDGI screen albedo is encoded in the GBuffer and decoded; PT uses hit albedo directly. The harness original color-conversion and quantization differences are preserved.',
 'GI timing is measured over preceding steady-state frames separately from readback-heavy capture frames. Per-capture wall-clock time is unavailable.',
 'FLIP exposure bounds are selected once from the PT visible-scene bounding rectangle; including the large black background would give a degenerate median. FLIP itself is evaluated on the full image before masking.'
]
summary={'schema_version':'gi-evaluation-v1','run_id':state['run_id'],'case_id':'cornell-ceiling-indirect','status':'complete','target_frame_count':32,'valid_frame_count':32,'invalid_frame_count':0,'mean_hdr_flip':mean_flip,'linear_rgb_mse':mean_mse,'gi_gpu_ms_mean':gpu,'timing_sample_count':len(timing),'gpu_stage_ms':stages,'pt_gpu_ms_per_1spp':float(np.mean(pt_times)),'reference_check':reference_check,'candidate_steady_check':steady,'luminance':{'reference':lum_ref,'candidate_representative':lum_cand,'relative_difference':lum_cand/lum_ref-1},'representative':{'capture_index':31,'render_frame_id':65568,'mean_hdr_flip':rows[-1]['mean_hdr_flip'],'linear_rgb_mse':rows[-1]['linear_rgb_mse'],'comparison':'comparison.png','heatmap':'flip-heatmap.png','error':'errors/flip-representative.exr'},'limitations':limitations}
save_json(out/'summary.json',summary)
manifest={'schema_version':'gi-evaluation-v1','run_id':state['run_id'],'case_id':summary['case_id'],'created_at':state['created_at'],'status':'complete','comparison_project':'NVIDIA Test Harness DDGI vs Path Tracer - Cornell Box indirect diffuse','result_directory':str(out),'timezone':'Asia/Hong_Kong',
 'candidate':{'name':'NVIDIA RTXGI-DDGI Test Harness','version':'1.3.7','source_root':'F:/build/official-ddgi/RTXGI-DDGI-1.3.7','patch':'reproduction/capture.patch','shader_changes':'none for DDGI','parameters_config':'reproduction/ddgi.ini','random_seed':'SDK volume rngSeed=12345; static volume, successive frames'},
 'reference':{'name':'Official Test Harness Path Tracer','version':'1.3.7','path':'reference/pt.exr','sha256':sha(out/'reference/pt.exr'),'independent_path':'reference/pt-independent.exr','independent_sha256':sha(out/'reference/pt-independent.exr'),'spp':32768,'max_bounces':20,'samples_per_frame':1,'progressive':True,'denoiser':False,'antialiasing':False,'seed':'pixelIndex * frameNumber; independent run uses frameNumber + 104729','check':reference_check,'patches':['reproduction/pt-pt-a.patch','reproduction/pt-pt-b.patch']},
 'scene':{'asset':'RTXGI-DDGI-1.3.7/samples/test-harness/data/gltf/cornell/cornell.glb','sha256':sha('F:/build/official-ddgi/RTXGI-DDGI-1.3.7/samples/test-harness/data/gltf/cornell/cornell.glb'),'configuration':'reproduction/ddgi.ini','lighting':'Ceiling point at (0,1.9,0), white, power=1, radius=4; sun=0, spot=0, black sky','material':'Official original Cornell glTF materials, no edits'},
 'camera':{'configuration':'reproduction/ddgi.ini','position':[.1,1,4],'yaw':0,'pitch':0,'vertical_fov_degrees':45,'aspect':16/9,'pixel_sampling':'center (0.5,0.5), no jitter, no lens sampling','primary_ray_tmin':0,'primary_ray_tmax':1e27},
 'signal':{'name':'indirect_diffuse_radiance','definition':'DDGI output float texture before composite; PT sum of surface direct-light estimates at bounceIndex > 0 weighted by path throughput. Black environment. Both contain primary surface albedo/BRDF. Camera-hit direct excluded.','color_space':'linear RGB in sample working primaries (sRGB assumed)','scale':'native sample radiance units, no normalization or fitted scaling'},
 'image':{'width':960,'height':540,'format':'OpenEXR float32 RGB, ZIP lossless; DDGI source float16 RGBA','mask':'mask.png','mask_sha256':sha(out/'mask.png'),'mask_definition':'GBufferB.w >= 0, fixed for all frames','valid_pixels':int(mask.sum()),'nonfinite_values':0,'negative_rgb_values':0,'input_handling':'assert finite/nonnegative; no radiance clamp'},
 'display':{'exposure_ev':display_ev,'tone_mapper':'ACES fitted x*(2.51*x+0.03)/(x*(2.43*x+0.59)+0.14)','transfer':'standard sRGB OETF','shared':True},
 'flip':{'implementation':'NVIDIA flip-evaluator','version':'1.7','mode':'HDR','parameters':params,'exposure_selection':'reference-only valid scene rectangle x=241..675 y=53..486; frozen for all candidate/reference checks','input_clamp':'none; finite nonnegative assertions','reduction':'compute full-frame error map then mean over fixed surface mask','error_channel':'Y','legend':[0,1]},
 'capture':{'warmup_frames':65536,'warmup_seconds':None,'frame_ids':[65537,65568],'target_frame_count':32,'actual_frame_count':32,'representative_index':31,'stability_check':steady,'stability_assessment':'Near steady; small residual drift remains.','fixed_budget_test':True,'per_frame_wall_time_available':False},
 'timing':{'tool':'Official sample D3D12 GPU timestamp queries','gpu':'NVIDIA GeForce RTX 5080','driver':'617.14','resolution':[960,540],'scope':'DDGI aggregate: probe tracing, blending, relocation, classification, indirect screen query','excluded':'GBuffer, composite, UI, presentation, readback, CPU','sample_count':len(timing),'frame_range':[14350,16370],'method':'same DDGI run preceding capture, no readback checkpoints in interval','path':'timing.csv','gpu_stage_ms':stages},
 'reproduction':{'work_directory':str(work),'configurations':{v:{'path':f'reproduction/{v}.ini','sha256':sha(out/f'reproduction/{v}.ini')} for v in ['ddgi','pt-a','pt-b']},'capture_instructions':'reproduction/README.md','scoring_script':'reproduction/evaluate_cornell.py','binary':'F:/build/official-ddgi/build/samples/bin/d3d12/Release/TestHarness-Evaluation.exe','binary_sha256':sha('F:/build/official-ddgi/build/samples/bin/d3d12/Release/TestHarness-Evaluation.exe')},'limitations':limitations}
save_json(out/'manifest.json',manifest)
print(json.dumps(summary,indent=2,ensure_ascii=False),flush=True)
