"""Score full-resolution linear HDR outputs against independently checked raw PT."""
from pathlib import Path
import sys,json,csv,hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/three-way-half-gather';OUT=ROOT/'docs/2026-11-18_DDGI-half-final-gather-comparison'
OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
assert '(Error)' not in (ROOT/'build/three-way-half-gather.log').read_text(errors='replace')
for mode in ['ddgi','half']:
    assert info[mode+'_stats']['finite']
    for key in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:
        assert info[mode+'_stats'][key]==0
def read(tag,channel):
    a=OpenEXR.File(str(DATA/(tag+'.'+channel+'.0.exr'))).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all(),tag
    return np.ascontiguousarray(a)
a=read('pt-a-32768','Accumulate.output');b=read('pt-b-32768','Accumulate.output')
ref=np.ascontiguousarray((a+b)*.5)
OpenEXR.File({}, {'RGB':ref}).write(str(DATA/'reference-65536spp.exr'))
mask=np.linalg.norm(read('pt-a-32768','Visibility.normW'),axis=-1)>.5
half=read('half-dimensions','DDGI.diffuseRadianceHitDist');assert half.shape[:2]==(135,240)
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
def mse(x,y):return float(np.mean((x[mask].astype(float)-y[mask])**2))
def score(x):
    error=flip_evaluator.evaluate(ref,x,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    return {'mse':mse(x,ref),'hdr_flip':float(error[mask].mean())}
summary={};rows=[];images={};timing={}
for mode,channel in [('ddgi','DDGI.color'),('half','Reconstruct.color')]:
    assert np.array_equal(mask,np.linalg.norm(read(mode+'-0','Visibility.normW'),axis=-1)>.5)
    images[mode]=[read(mode+'-'+str(i),channel) for i in range(64)]
    measurements=[score(x) for x in images[mode]]
    for i,r in enumerate(measurements):rows.append({'mode':mode,'frame':i,**r})
    summary[mode]={k:float(np.mean([r[k] for r in measurements])) for k in ['mse','hdr_flip']}
    summary[mode]['temporal_rgb_variance']=float(np.var(np.array(images[mode])[:,mask].astype(float),axis=0).mean())
    summary[mode]['first_last_32_mean_relative_change']=float(abs(np.mean(images[mode][:32])-np.mean(images[mode][32:]))/max(np.mean(images[mode]),1e-12))
    summary[mode]['warm256']=score(read(mode+'-warm-256',channel))
    summary[mode]['warm512']=score(read(mode+'-warm-512',channel))
    profile=json.loads((DATA/(mode+'-timing.json')).read_text())
    stages=['Visibility','DDGI','Display']+(['Guides','Denoiser','Reconstruct'] if mode=='half' else [])
    timing[mode]={'samples':profile['frame_count'],'passes':{}}
    for stage in stages:
        timing[mode]['passes'][stage]=profile['events']['/onFrameRender/RenderGraphExe::execute()/'+stage+'/gpu_time']['stats']['mean']
    timing[mode]['gpu_frame_ms']=profile['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['mean']
    timing[mode]['gpu_frame_std_ms']=profile['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['std_dev']
    timing[mode]['sum_without_display_ms']=sum(v for k,v in timing[mode]['passes'].items() if k!='Display')
independent_difference=mse(a,b)
convergence={'independent_32768spp_difference_mse':independent_difference,
    'estimated_65536spp_reference_noise_mse':independent_difference/4,
    'estimated_reference_noise_over_best_method_mse':independent_difference/4/min(x['mse'] for x in summary.values()),
    'checkpoints':{}}
for spp in [4096,8192,16384,32768]:
    x=read('pt-a-'+str(spp),'Accumulate.output');y=read('pt-b-'+str(spp),'Accumulate.output')
    convergence['checkpoints'][str(spp)]={'independent_difference_mse':mse(x,y),'estimated_combined_noise_mse':mse(x,y)/4}
assert convergence['estimated_reference_noise_over_best_method_mse']<.01,convergence
assert all(v['first_last_32_mean_relative_change']<.005 for v in summary.values()),summary
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
def display(x):
    x=np.maximum(x,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
def panel(items):
    result=Image.new('RGB',(480*len(items),308),(23,26,31));draw=ImageDraw.Draw(result)
    for i,(label,x) in enumerate(items):
        draw.text((i*480+10,10),label,font=font,fill='white');result.paste(display(x),(i*480,38))
    return result
panel([('DDGI / probe interpolation',images['ddgi'][-1]),('DDGI / half FG + NRD',images['half'][-1]),('PT / 65536 spp / no NRD',ref)]).save(OUT/'comparison.png')
gif=[panel([('DDGI / frame '+str(i),images['ddgi'][i]),('Half FG + NRD / frame '+str(i),images['half'][i])]) for i in range(64)]
gif[0].save(OUT/'stability.gif',save_all=True,append_images=gif[1:],duration=80,loop=0)
result={'metrics':summary,'timing':timing,'convergence':convergence,'flip_parameters':params,
    'capture':info,'hardware':'RTX 5070 / D3D12 / driver 621.01','metric_domain':'full lighting, linear HDR, visible surfaces',
    'time_variance_definition':'mean over visible surface pixels and RGB channels of population variance over 64 frames'}
(OUT/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
with (OUT/'metrics.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
labels={'ddgi':'原始 DDGI：直接查询 probe','half':'DDGI + 半分辨率 FG + NRD'}
table=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.5f}</td><td>{v['temporal_rgb_variance']:.7g}</td><td>{timing[k]['gpu_frame_ms']:.4f}</td></tr>" for k,v in summary.items())
detail=''.join(f"<tr><td>{labels[k]}</td><td>{t['passes']['DDGI']:.4f}</td><td>{t['passes'].get('Denoiser',0):.4f}</td><td>{t['passes'].get('Guides',0)+t['passes'].get('Reconstruct',0):.4f}</td><td>{t['passes']['Visibility']:.4f}</td></tr>" for k,t in timing.items())
text=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI 三组对比：半分辨率 final gather</title>
<style>body{{max-width:1480px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#ddd;background:#171a20}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:8px 16px}}table{{border-collapse:collapse}}a{{color:#8dc7ff}}</style>
<h1>DDGI / 半分辨率 final gather + NRD / PT reference</h1>
<p>相同 Lambert Cornell、点光源、相机与 480×270 输出。灯光使用 Test Harness 衰减：距离下限 1、范围半径 4。PT reference 未降噪，8 spp/帧；两组独立 32768 spp 累积的平均构成 65536 spp 参考。</p>
<p><strong>本次结论：</strong>此配置下原始 DDGI 的 MSE、HDR-FLIP 和时间方差均较低，耗时也较少。半分辨率 FG + NRD 没有带来整体指标改善；不能沿用旧灯光、全分辨率累积 FG 实验的结论。</p>
<img src="comparison.png"><table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>时间方差 ↓</th><th>GPU 帧耗时 ms ↓</th></tr>{table}</table>
<p>画质指标对稳定后的连续 64 张单帧输出逐帧计算，再平均指标；展示图也是单帧，没有额外 Accumulate。MSE 使用线性 HDR 完整光照，统计可见表面像素；HDR-FLIP 使用统一参考曝光范围和 PPD 67。时间方差是固定像素 RGB 在 64 帧中的总体方差，再对像素和通道平均。</p>
<h2>参考与稳定性检查</h2><p>PT 最多 31 surface bounces、NEE/MIS 开启、RR 关闭。两组独立 32768 spp 结果间 MSE 为 {independent_difference:.7g}；据此估计最终参考残余采样噪声 MSE 为 {independent_difference/4:.7g}，仅占较好方案误差的 {convergence['estimated_reference_noise_over_best_method_mse']:.2%}，达到本实验小于 1% 的收敛检查标准。它仍是有限采样、有限反弹参考。</p>
<p>两种 DDGI 均先更新 probe 2048 帧，再预热 512 帧；FG 的 NRD 在 probe 预热后重置。采集和计时期间持续更新 probe。连续样本前后各 32 帧平均亮度变化分别为 {summary['ddgi']['first_last_32_mean_relative_change']:.3%} / {summary['half']['first_last_32_mean_relative_change']:.3%}。下方为连续单帧动画。</p><img src="stability.gif">
<h2>GPU 耗时分项（ms）</h2><table><tr><th>方案</th><th>DDGI 含 probe 更新</th><th>NRD</th><th>导向准备 + 上采样合成</th><th>GBuffer</th></tr>{detail}</table>
<p>RTX 5070，D3D12；每种方案 255 个 GPU 时间戳区间。主表为整个 RenderGraph 的 GPU 时间，包含 GBuffer、probe 更新、屏幕着色、NRD/重建及色调映射，不含文件保存、CPU 调度和呈现等待。仅代表此场景与分辨率，不外推复杂场景。</p>
<p>半分辨率指 240×135，每个 2×2 像素块只在固定代表像素追踪一根漫反射 FG 射线，射线数约为全分辨率的四分之一。NRD 也在 240×135 运行；直接光和反射率仍为 480×270，使用深度/法线引导的 4×4 邻域重建间接光。纯 Lambert 镜面 lobe 为零。此采样/重建会损失细节；本实验只测固定镜头，不代表运动与细小几何的表现。</p>
<p>Probe 9×9×9，每 probe 256 rays，hysteresis 0.97；RELAX DiffuseSpecular 默认参数、maxIntensity=10000。显示统一 +3 EV / ACES fitted / sRGB；HDR-FLIP 曝光参数保存在 summary.json。新公式参考已重算，未复用旧灯光实验图。</p>
<h2>复现</h2><pre>build\\windows-vs2022\\bin\\Release\\Mogwai.exe --device-type d3d12 --headless --deferred --script tests/ddgi/three_way_half_gather.py --width 480 --height 270 --logfile build/three-way-half-gather.log
python tests/ddgi/score_three_way_half_gather.py</pre>
<p>交互入口：Run-HalfGather.cmd；统一启动器选择 DDGIHalf、DDGI 或 PathTracer（原始累积 PT）。原始 EXR、65536 spp reference 和时间戳保存在 build/three-way-half-gather。<a href="summary.json">结果 JSON</a> · <a href="metrics.csv">逐帧指标</a></p></html>'''
(OUT/'report.html').write_text(text,encoding='utf-8')
sources=['Source/Falcor/Rendering/Lights/LightHelpers.slang','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang',
    'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','Source/RenderPasses/RTXGIDDGI/DDGIReconstruct.cpp',
    'Source/RenderPasses/RTXGIDDGI/DDGIReconstruct.cs.slang','scripts/DDGIHalfGatherNRD.py','scripts/PTReference.py',
    'tests/ddgi/three_way_half_gather.py','tests/ddgi/score_three_way_half_gather.py']
(OUT/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},indent=2))
print(json.dumps({'metrics':summary,'timing':timing,'convergence':convergence,'report':str(OUT/'report.html')},indent=2))
