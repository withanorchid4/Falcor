"""Validate GPU regressions and generate the temporal-reservoir experiment report."""
from pathlib import Path
import json, sys, hashlib
import numpy as np
R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / 'build/final-gather-python'))
import OpenEXR, flip_evaluator
from PIL import Image, ImageDraw, ImageFont
D = R / 'build/restir-temporal-comparison'
S = R / 'build/restir-temporal-smoke'
B = R / 'build/highres-1080p-split-rerun'
O = R / 'docs/2026-11-18_DDGI-ReSTIR-temporal'
O.mkdir(exist_ok=True)
def load(path):
    a = OpenEXR.File(str(path)).channels()['RGB'].pixels
    assert np.isfinite(a).all(), path
    return np.ascontiguousarray(a)
def read(tag): return load(D / (tag + '.Accumulate.output.0.exr'))
def smoke(tag, output): return load(S / (tag + '.' + output + '.0.exr'))
assert not (S / 'failure.txt').exists()
assert not (D / 'failure.txt').exists()
maxdiff = max(float(np.max(abs(smoke('off-'+str(i),c)-smoke('one-'+str(i),c))))
              for i in range(8) for c in ['DDGI.gatherDiffuse', 'Reconstruct.color'])
assert maxdiff < 1e-7
for tag in ['off','on','full','half','fixed','no-fg']:
    assert np.max(abs(smoke(tag+'-reset','Accumulate.output')-smoke(tag+'-reset','Reconstruct.color'))) < 1e-6
ref = load(B / 'reference-65536spp.exr')
base = load(B / 'half-65536.Accumulate.output.0.exr')
mask = np.load(B / 'surface-mask.npy')
params = json.loads((R / 'docs/2026-11-18_DDGI-1080p/summary.json').read_text())['flip_parameters']
def mse(a,b): return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
def flip(a): return float(flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0][mask].mean())
def display(a):
    x = np.maximum(a,0)*8
    x = np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x = np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
def panel(items,filename):
    w,h = items[0][1].size
    out = Image.new('RGB',(w*len(items),h+50),(23,26,31)); draw=ImageDraw.Draw(out)
    for i,(name,img) in enumerate(items):
        draw.text((i*w+12,9),name,font=font,fill='white');out.paste(img,(i*w,50))
    out.save(O / filename)
result = {'capture': json.loads((D / 'complete.json').read_text()),
          'smoke': {'M1_max_abs': maxdiff, 'camera_and_switch_resets': True}, 'metrics': {},
          'flip_parameters': params, 'scope': 'Temporal random-seed reservoirs; no spatial reuse or motion reprojection'}
labels = {'off':'Original half FG','temporal':'Temporal reservoir / M=8'}
for name in labels:
    a=read(name+'-16384'); p=read(name+'-8192')
    raw0=read(name+'-raw-0'); mean=None; m2=None; raw_mses=[]
    for i in range(16):
        v=read(name+'-raw-'+str(i)); raw_mses.append(mse(v,ref)); v=v[mask].astype(np.float64)
        if mean is None: mean=v.copy(); m2=np.zeros_like(mean)
        else: delta=v-mean;mean+=delta/(i+1);m2+=delta*(v-mean)
    timing=json.loads((D / (name+'-timing.json')).read_text())['events']
    prefix='/onFrameRender/RenderGraphExe::execute()'
    luma=np.array([.2126,.7152,.0722])
    m={'mse':mse(a,ref),'hdr_flip':flip(a), 'mse_vs_original_converged_fg':mse(a,base),
       'mse_8192':mse(p,ref),'tail_difference_mse':mse(a,p),
       'mean_luminance':float(np.mean(a[mask]@luma)),
       'raw_frame_mse_mean_16':float(np.mean(raw_mses)), 'raw_temporal_variance_16':float(np.mean(m2/16)),
       'raw_0_hdr_flip':flip(raw0), 'gpu_frame_ms':timing[prefix+'/gpu_time']['stats']['mean'],
       'half_gather_ms':timing[prefix+'/DDGI/HalfGather/gpu_time']['stats']['mean'],
       'checkpoint_mse':{str(n):mse(read(name+'-'+str(n)),ref) for n in [1,8,32,128,1024,8192,16384]}}
    result['metrics'][name]=m
    display(a).save(O/(name+'.png')); display(raw0).save(O/(name+'-raw.png'))
    print(name,json.dumps(m),flush=True)
result['mean_luminance_ratio']=result['metrics']['temporal']['mean_luminance']/result['metrics']['off']['mean_luminance']
panel([(labels[k]+' / Accumulate OFF',display(read(k+'-raw-0'))) for k in labels],'raw-comparison.png')
panel([(labels[k]+' / 32 frames',display(read(k+'-32'))) for k in labels],'32-comparison.png')
panel([(labels[k]+' / 16384 frames',display(read(k+'-16384'))) for k in labels]+[('PT / 65536 spp',display(ref))],'comparison.png')
rows=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.6f}</td><td>{v['raw_frame_mse_mean_16']:.7g}</td><td>{v['gpu_frame_ms']:.3f}</td><td>{v['half_gather_ms']:.3f}</td></tr>" for k,v in result['metrics'].items())
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI Final Gather 时间 reservoir 初版</title>
<style>body{{background:#171a1f;color:#ddd;font:17px/1.7 system-ui;margin:32px auto;max-width:1600px;padding:0 20px}}img{{width:100%}}a{{color:#8bd}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px}}code{{color:#bdf}}</style>
<h1>DDGI Final Gather：可选时间 reservoir 实验</h1>
<p>入口：DDGI → Final gather → Enabled → ReSTIR temporal (experimental)。默认关闭；Reservoir candidates 默认 8，范围 1–32。Accumulate 默认仍开，可独立关闭。直接光、镜面 FG、probe 更新和半分辨率重建沿用原实现；不启用 NRD。</p>
<p><strong>范围：</strong>这是时间重采样的第一步，不是完整 Lumen ReSTIR Gather 或 DDGI Resampling 论文复现。没有邻域空间复用、运动重投影。相机或场景变化会清空 reservoir。固定屏幕像素各自保存历史；半分辨率 jitter 的四种实际像素位置使用各自的历史。</p>
<p><strong>本次结果：</strong>未累积单帧 MSE（16 帧均值）降低约 71%，GPU 整图从 1.135 ms 增至 1.472 ms。加上 Accumulate 后，32 帧 MSE 约为原方案的 3.02 倍，16384 帧仍高约 4.1%。因此这版减少了单帧噪声，但没有改善累计效率，不建议替换当前默认 FG＋Accumulate。整体平均亮度基本一致；仍须区分有限样本残余误差与系统偏差。</p>
<h2>实现与 pass 组织</h2><p>Visibility → DDGI（ProbeUpdate → 全分辨率 PrimaryShading → 半分辨率 HalfGather）→ Reconstruct → Accumulate → Display。时间 reservoir 位于 HalfGather 的漫反射路径中；全分辨率时位于 PrimaryShading 内。没有增加独立空间滤波 pass。</p>
<p>每个实际像素保存 selectedSeed、M、W、lastFrame（16 字节，1080p 约 31.6 MiB；关闭不分配）。每次采样产生 1 条新 FG 路径，并重放最多 1 条历史路径的完整随机数序列，包括次级光源采样；重新求交和着色，避免直接使用过期光照。当前半分辨率最多追踪 2×960×540 条漫反射 FG 路径；还可能有着色中的阴影射线。因此本版主要验证采样正确性，并不承诺加速。</p>
<p>已有 FG 返回 C=f·cosθ·Li/pdf，令 t=max(luminance(C),10⁻⁶)。新样本权重 t，旧 reservoir 权重 t_old·W_old·min(M_old,M_max−1)。按权重随机选择一条路径，更新 W=Σw/(M·t_selected)，输出 C_selected·W。它在原始随机样本空间中重采样，不能再次乘 cosθ/pdf。完整随机流重放维持次级随机光照与被选择样本的一致性。M 限制的是有效候选数，不是每帧射线数。</p>
<h2>1080p Lambert Cornell 验证</h2><p>与原先报告相同场景、点光源和显示变换（+3EV/ACES/sRGB）；预热 2560 帧，固定左上采样，jitter 关闭。先旁路 Accumulate 采集 16 帧，再分别累积 16384 帧；PT 复用同场景 65536 spp 未降噪参考。原始 FG 收敛参考为此前的 65536 帧。这里的 reservoir 已预热；短时累积图不代表从空历史启动。16384 帧仅用于初版验证，不等同于之前完整 65536 帧收敛实验。</p>
<table><tr><th>方案</th><th>16384 帧 MSE</th><th>HDR-FLIP</th><th>未累积单帧 MSE（16 帧均值）</th><th>全图 GPU ms</th><th>HalfGather ms</th></tr>{rows}</table>
<p>长期平均亮度比（时间 reservoir / 原 FG）：{result['mean_luminance_ratio']:.6f}。指标与有限样本误差见 <a href="summary.json">原始结果</a>。单帧方差降低不代表同等时间累计误差一定降低：时间复用使帧间相关，而且本版每次会重追历史路径。</p>
<h2>Accumulate 关闭：单帧</h2><a href="raw-comparison.png"><img src="raw-comparison.png"></a>
<h2>Accumulate 32 帧</h2><a href="32-comparison.png"><img src="32-comparison.png"></a>
<h2>Accumulate 16384 帧与 PT</h2><a href="comparison.png"><img src="comparison.png"></a>
<p>运行验证：481×271 奇数尺寸、jitter 四相位、全/半分辨率、开关 ReSTIR/FG、镜头移动与累积重置均通过；M=1 与关闭重采样的最大绝对差 {maxdiff:.3g}（浮点舍入量级）。编译及实际 D3D12 shader 执行通过。当前实验只验证 Lambert Cornell；其他材质与动态场景尚未做画质评估。</p></html>'''
(O/'report.html').write_text(html,encoding='utf-8')
(O/'summary.json').write_text(json.dumps(result,indent=2))
paths=['Source/RenderPasses/RTXGIDDGI/'+n for n in ['RTXGIDDGI.h','RTXGIDDGI.cpp','RTXGIDDGI.rt.slang']]+['tests/ddgi/restir_temporal_smoke.py','tests/ddgi/restir_temporal_comparison.py','tests/ddgi/score_restir_temporal.py']
(O/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((R/p).read_bytes()).hexdigest() for p in paths},indent=2))
