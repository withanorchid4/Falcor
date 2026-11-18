"""Compare converged raw estimators and distinguish NRD noise from mean-image changes."""
from pathlib import Path
import sys,json,csv,hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/accumulated-gather-comparison';OLD=ROOT/'build/three-way-half-gather'
OUT=ROOT/'docs/2026-11-18_DDGI-accumulated-final-gather';OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
assert '(Error)' not in (ROOT/'build/accumulated-gather-comparison.log').read_text(errors='replace')
previous=json.loads((ROOT/'docs/2026-11-18_DDGI-full-vs-half-final-gather/summary.json').read_text())
params=previous['flip_parameters']
def read(p):
    a=OpenEXR.File(str(p)).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all(),p
    return np.ascontiguousarray(a)
def current(tag):return read(DATA/(tag+'.Accumulate.output.0.exr'))
ref=read(OLD/'reference-65536spp.exr')
mask=np.linalg.norm(read(OLD/'pt-a-32768.Visibility.normW.0.exr'),axis=-1)>.5
def mse(x,y):return float(np.mean((x[mask].astype(float)-y[mask])**2))
def score(a):
    error=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    return {'mse':mse(ref,a),'hdr_flip':float(error[mask].mean())}
metrics={};convergence={};timing={};images={};rows=[]
for mode in ['ddgi','half','full']:
    assert info[mode+'_stats']['finite']
    for k in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:assert info[mode+'_stats'][k]==0
    assert np.array_equal(mask,np.linalg.norm(read(DATA/(mode+'-65536.Visibility.normW.0.exr')),axis=-1)>.5)
    checkpoints={str(n):score(current(mode+'-'+str(n))) for n in info['checkpoints']}
    a=current(mode+'-32768');b=current(mode+'-65536');images[mode]=b
    convergence[mode]={'checkpoints':checkpoints,'mse_change_32768_to_65536':checkpoints['65536']['mse']/checkpoints['32768']['mse']-1,
        'flip_change_32768_to_65536':checkpoints['65536']['hdr_flip']/checkpoints['32768']['hdr_flip']-1,
        'late_doubling_image_difference_mse':mse(a,b),'estimated_residual_over_error':mse(a,b)/checkpoints['65536']['mse']}
    stack=[current(mode+'-stable-'+str(i)) for i in range(64)]
    scored=[score(x) for x in stack]
    for i,r in enumerate(scored):rows.append({'mode':mode,'frame':65537+i,**r})
    metrics[mode]={k:float(np.mean([r[k] for r in scored])) for k in ['mse','hdr_flip']}
    metrics[mode]['temporal_rgb_variance']=float(np.var(np.array(stack)[:,mask].astype(float),axis=0).mean())
    t=json.loads((DATA/(mode+'-timing.json')).read_text())
    stages=['Visibility','DDGI','Accumulate','Display']+(['Reconstruct'] if mode=='half' else [])
    timing[mode]={'samples':t['frame_count'],'passes':{s:t['events']['/onFrameRender/RenderGraphExe::execute()/'+s+'/gpu_time']['stats']['mean'] for s in stages},
        'gpu_frame_ms':t['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['mean']}
nrd_comparison={};nrd_means={}
for mode,folder,ch in [('half',OLD,'Reconstruct.color'),('full',ROOT/'build/full-gather-nrd-comparison','Compose.output')]:
    nrd_means[mode]=np.ascontiguousarray(np.mean([read(folder/(mode+'-'+str(i)+'.'+ch+'.0.exr')) for i in range(64)],axis=0))
    nrd_comparison[mode]={'nrd_single_frame_mean_metrics':previous['metrics'][mode],
        'nrd_64_frame_mean_image_metrics':score(nrd_means[mode]),
        'nrd_mean_vs_converged_raw_mse':mse(nrd_means[mode],images[mode]),
        'accumulate_mse_change_from_nrd':metrics[mode]['mse']/previous['metrics'][mode]['mse']-1}
refnoise=previous['reference_convergence']['estimated_65536spp_reference_noise_mse']
checks={'late_change_within_3_percent':all(abs(v['mse_change_32768_to_65536'])<.03 and abs(v['flip_change_32768_to_65536'])<.03 for v in convergence.values()),
    'estimated_tail_below_5_percent':all(v['estimated_residual_over_error']<.05 for v in convergence.values()),
    'reference_noise_below_5_percent':refnoise/min(v['mse'] for v in metrics.values())<.05}
result={'metrics':metrics,'timing':timing,'convergence':convergence,'nrd_comparison':nrd_comparison,
    'convergence_checks':checks,'reference_noise_estimate':refnoise,'flip_parameters':params,'capture':info}
(OUT/'summary.json').write_text(json.dumps(result,indent=2))
with (OUT/'metrics.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print(json.dumps({'metrics':metrics,'timing':timing,'convergence':convergence,'checks':checks,'nrd':nrd_comparison},indent=2))
assert all(checks.values()),'More convergence work needed; inspect summary.json'
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
def display(a):
    x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
def panel(items,columns=2):
    canvas=Image.new('RGB',(480*columns,308*((len(items)+columns-1)//columns)),(23,26,31));draw=ImageDraw.Draw(canvas)
    for i,(label,a) in enumerate(items):
        x=i%columns*480;y=i//columns*308
        draw.text((x+10,y+10),label,font=font,fill='white');canvas.paste(display(a),(x,y+38))
    return canvas
panel([('DDGI + Accumulate',images['ddgi']),('Half FG + Accumulate',images['half']),
    ('Full FG + Accumulate',images['full']),('PT reference / 65536 spp',ref)]).save(OUT/'comparison.png')
panel([('Half FG + NRD / 64-frame mean',nrd_means['half']),('Half FG + Accumulate',images['half']),
    ('Full FG + NRD / 64-frame mean',nrd_means['full']),('Full FG + Accumulate',images['full'])]).save(OUT/'nrd-mean-comparison.png')
labels={'ddgi':'原始 DDGI + Accumulate','half':'半分辨率 FG + Accumulate','full':'全分辨率 FG + Accumulate'}
table=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.5f}</td><td>{v['temporal_rgb_variance']:.7g}</td><td>{timing[k]['gpu_frame_ms']:.4f}</td></tr>" for k,v in metrics.items())
conv=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse_change_32768_to_65536']:+.2%}</td><td>{v['flip_change_32768_to_65536']:+.2%}</td><td>{v['late_doubling_image_difference_mse']:.7g}</td></tr>" for k,v in convergence.items())
nrdtable=''.join(f"<tr><td>{labels[k]}</td><td>{previous['metrics'][k]['mse']:.7g}</td><td>{v['nrd_64_frame_mean_image_metrics']['mse']:.7g}</td><td>{metrics[k]['mse']:.7g}</td></tr>" for k,v in nrd_comparison.items())
text=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>关闭 NRD：DDGI 与 FG 静态收敛实验</title>
<style>body{{max-width:1100px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#ddd;background:#171a20}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:8px 16px}}table{{border-collapse:collapse}}a{{color:#8dc7ff}}</style>
<h1>关闭 NRD，使用 Accumulate 的三组对比</h1>
<p><strong>结论：</strong>当前 NRD 流程的滤波偏差是重要因素。改为长时间累积后，两种 FG 都明显优于原始 DDGI；半分辨率仍有重建损失，但与全分辨率的差距远小于使用 NRD 时。将之前 64 张 NRD 输出平均后，MSE 仍明显高于原始 FG 收敛结果，说明差异不只是瞬时噪点。此结论针对当前接入与参数，不代表 NRD 无法通过调整改善。</p>
<p>三组均先更新 probe 2560 帧，再重置 Accumulate 并累积 65536 帧。场景、相机、当前 Test Harness 点光源衰减、480×270 输出和未经降噪的 65536 spp PT reference 不变。Probe 始终更新，NRD 完全不在渲染图中。</p>
<img src="comparison.png"><table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>时间方差 ↓</th><th>GPU 帧耗时 ms</th></tr>{table}</table>
<p>主表是第 65537～65600 帧累积输出的逐帧指标均值；图像显示第 65536 帧。半分辨率在 240×135 固定代表像素上发射射线，保留原来的深度/法线引导上采样，再累积完整图像。全分辨率在 480×270 发射射线，直接累积原始 DDGI.color。Lambert 场景每个有效采样像素每帧最多一根漫反射 FG 射线。</p>
<h2>是否已稳定？</h2><table><tr><th>方案</th><th>32768→65536 MSE 变化</th><th>HDR-FLIP 变化</th><th>两阶段图像差异 MSE</th></tr>{conv}</table>
<p>三组翻倍累积后的 MSE/HDR-FLIP 变化均小于 3%；以末次翻倍的图像差异估计剩余采样影响，均小于相对 PT 误差的 5%。这不是无限采样证明；探针相关性会影响此估计。PT reference 自身的残余噪声估计 MSE 为 {refnoise:.7g}，也低于本次最小误差的 5%。所有阶段指标可见 JSON。</p>
<h2>与 NRD 对照</h2><table><tr><th>FG 分辨率</th><th>NRD 单帧 MSE 均值</th><th>64 张 NRD 输出平均后的 MSE</th><th>本次 Accumulate MSE</th></tr>{nrdtable}</table>
<img src="nrd-mean-comparison.png"><p>对 NRD 输出额外取 64 帧平均仅用于诊断平均画面的变化，不属于实时方案。NRD 单帧与长时间累积的差别同时包含残余噪声和滤波偏差；若 NRD 平均图仍与原始 FG 收敛图有系统性差异，说明不能仅用单帧噪点解释。64 帧具有时间相关性，不能将其当作严格无噪声的 NRD 期望。</p>
<p><strong>时间方差和耗时的解释：</strong>普通累积已经用了约 65536 帧历史，随后 64 帧的方差自然极小，不能据此认为它比 NRD 更适合实时运动。GPU 时间是每帧更新开销（RTX 5070 / D3D12，255 个区间，包含 GBuffer、probe 更新、FG/重建、Accumulate 和色调映射），不代表一帧就能获得展示的收敛画质。普通累积没有重投影，镜头或场景变化时需要清空历史。</p>
<p>MSE 使用线性 HDR 完整光照、可见表面 mask；HDR-FLIP 沿用相同曝光和 PPD 67；显示 +3 EV / ACES fitted / sRGB。原始 DDGI 也做相同累积，以去除其 probe 更新波动；所以该行不等同于之前未累积的实时 DDGI。</p>
<pre>build\\windows-vs2022\\bin\\Release\\Mogwai.exe --device-type d3d12 --headless --deferred --script tests/ddgi/accumulated_gather_comparison.py --width 480 --height 270 --logfile build/accumulated-gather-comparison.log
python tests/ddgi/score_accumulated_gather_comparison.py</pre>
<p>全分辨率交互入口：Run-AccumulatedGather.cmd。图工厂 scripts/DDGIAccumulated.py 支持 ddgi / half / full。原始捕获与计时：build/accumulated-gather-comparison。<a href="summary.json">结果 JSON</a> · <a href="metrics.csv">逐帧指标</a></p></html>'''
(OUT/'report.html').write_text(text,encoding='utf-8')
sources=['scripts/DDGIAccumulated.py','tests/ddgi/accumulated_gather_comparison.py','tests/ddgi/score_accumulated_gather_comparison.py']
(OUT/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},indent=2))
