"""Score captured linear HDR images and build a standalone HTML comparison."""
from pathlib import Path
import sys,json,csv,hashlib,html,shutil
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np, OpenEXR, flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/final-gather-comparison'
OUT=ROOT/'docs/2026-11-17_DDGI-final-gather-Lambert'
OUT.mkdir(exist_ok=True)
record=json.loads((DATA/'complete.json').read_text())
for key in ['probe_stats','native_stats']:
    assert record[key]['finite']
    for counter in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:
        assert record[key][counter]==0, (key,counter,record[key][counter])
params=json.loads((ROOT/'docs/2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox/lambert-control/manifest.json').read_text())['flip']['parameters']
def read(tag,channel):
    p=DATA/(tag+'.'+channel+'.0.exr')
    a=OpenEXR.File(str(p)).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all(),p
    return np.ascontiguousarray(a)
# Validate every output, not just the figures selected below.
for p in DATA.glob('*.exr'):
    for channel in OpenEXR.File(str(p)).channels().values():assert np.isfinite(channel.pixels).all(),p
ref=read('reference','Accumulate.output')
direct=read('direct','DDGI.color')
indref=ref-direct
assert indref.min()>=0
mask=np.linalg.norm(read('reference','Visibility.normW'),axis=-1)>.5
assert np.array_equal(mask,np.linalg.norm(read('baseline','Visibility.normW'),axis=-1)>.5)
def score(a,b,m=mask):
    assert a.min()>=0 and b.min()>=0
    e=flip_evaluator.evaluate(a,b,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    return {'mse':float(np.mean((a[m].astype(float)-b[m])**2)),
        'hdr_flip':float(e[m].mean()),'mean_radiance':float(b[m].mean())},e
baseline=read('baseline','DDGI.indirect')
rows=[]
metric,be=score(indref,baseline);rows.append(dict(mode='DDGI',spp=1,**metric))
images=[baseline]
for spp in [1,16,64,256,1024]:
    a=read('gather-'+str(spp),'Accumulate.output')-direct
    assert a.min()>=-1e-6
    a=np.maximum(a,0)
    metric,e=score(indref,a);rows.append(dict(mode='Final gather',spp=spp,**metric))
    if spp==1024: converged=a;ge=e
    # Same-frame split outputs must sum exactly, independent of accumulation.
    raw=read('gather-'+str(spp),'DDGI.indirect')
    split=read('gather-'+str(spp),'DDGI.gatherDiffuse')+read('gather-'+str(spp),'DDGI.gatherSpecular')
    assert np.max(np.abs(raw-split))<1e-6
assert read('lambert-specular-only','DDGI.indirect').max()==0
native_spec=read('native-two-lobes','DDGI.gatherSpecular')
assert native_spec.max()>1e-4
noise,_=score(indref,read('reference-independent','Accumulate.output')-direct)
# Camera moves: accumulated output must reset to the current noisy frame.
motion=[];motion_frames=[]
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
def display(a):
    x=np.maximum(a,0)*8
    x=np.clip((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
def panel(items):
    canvas=Image.new('RGB',(480*len(items),308),(23,26,31));d=ImageDraw.Draw(canvas)
    for i,(title,a) in enumerate(items):
        d.text((i*480+12,10),title,font=font,fill='white');canvas.paste(display(a),(i*480,38))
    return canvas
for i in range(8):
    m=np.linalg.norm(read('motion-reference-'+str(i),'Visibility.normW'),axis=-1)>.5
    r=read('motion-reference-'+str(i),'Accumulate.output')
    b=read('motion-baseline-'+str(i),'DDGI.color')
    bi=read('motion-baseline-'+str(i),'DDGI.indirect')
    direct_i=b-bi
    ri=np.maximum(r-direct_i,0)
    a=read('motion-gather-'+str(i),'DDGI.color')
    ai=read('motion-gather-'+str(i),'DDGI.indirect')
    reset_error=float(np.max(np.abs(a-read('motion-gather-'+str(i),'Accumulate.output'))))
    assert reset_error<1e-6,reset_error
    bm,_=score(ri,bi,m);gm,_=score(ri,ai,m)
    motion.append({'frame':i,'baseline':bm,'gather':gm,'accumulation_reset_max_error':reset_error})
    motion_frames.append(panel([('DDGI / moving camera',bi),('Final gather / 1 spp',ai),('PT / 512 spp',ri)]))
motion_frames[0].save(OUT/'motion.gif',save_all=True,append_images=motion_frames[1:]+motion_frames[-2:0:-1],duration=160,loop=0)
panel([('DDGI / probe interpolation',baseline),('Final gather / 1024 spp',converged),('PT / 32768 spp',indref)]).save(OUT/'comparison.png')
panel([('Final gather / 1 spp',read('gather-1','DDGI.indirect')),('Final gather / 64 spp',np.maximum(read('gather-64','Accumulate.output')-direct,0)),('Final gather / 1024 spp',converged)]).save(OUT/'convergence.png')
# Fixed [0,1] monochrome FLIP heatmaps, brighter means larger error.
canvas=Image.new('RGB',(960,308),(23,26,31));d=ImageDraw.Draw(canvas)
for i,(label,e) in enumerate([('DDGI / HDR-FLIP [0,1]',be),('Final gather / HDR-FLIP [0,1]',ge)]):
    d.text((i*480+12,10),label,font=font,fill='white')
    gray=np.uint8(np.clip(e,0,1)*255);gray[~mask]=0
    canvas.paste(Image.fromarray(gray).convert('RGB'),(i*480,38))
canvas.save(OUT/'errors.png')
timings={}
for name,passname in [('baseline','DDGI'),('gather','DDGI'),('pt-1spp','PT')]:
    t=json.loads((DATA/(name+'-timing.json')).read_text())
    key='/onFrameRender/RenderGraphExe::execute()/'+passname+'/gpu_time'
    timings[name]={'samples':t['frame_count'],**t['events'][key]['stats']}
extra_checks={}
regressions=sorted((ROOT/'build/ddgi-environment-validation').glob('*/results.json'),key=lambda p:p.stat().st_mtime)
latest_regression=regressions[-1] if regressions else ROOT/'build/missing-environment-validation.json'
for label,path in [('gather_unit_sky',ROOT/'build/final-gather-environment/results.json'),('original_environment_regression',latest_regression)]:
    if path.exists():
        extra_checks[label]=json.loads(path.read_text())
        assert extra_checks[label]['passed']
summary={'additional_validation':extra_checks,'static_indirect':rows,'reference_independent_error':noise,'timing_ms':timings,'motion':motion,
    'flip_parameters':params,'native_specular_max':float(native_spec.max()),
    'reference_indirect_mean':float(indref[mask].mean()),'capture':record,
    'mse_improvement':1-rows[-1]['mse']/rows[0]['mse'],
    'checks':{'all_exr_finite':True,'lambert_specular_zero':True,'lobe_sum':True,'motion_accumulation_resets':True}}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
with (OUT/'metrics.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
rows_html=''.join(f"<tr><td>{x['mode']}</td><td>{x['spp']}</td><td>{x['mse']:.8f}</td><td>{x['hdr_flip']:.4f}</td></tr>" for x in rows)
text=fr"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI Final Gather 对比</title>
<style>body{{max-width:1480px;margin:36px auto;padding:0 24px;font:16px/1.7 system-ui;color:#ddd;background:#171a20}}img{{max-width:100%}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px 20px}}a{{color:#8dc7ff}}code{{color:#aee}}</style>
<h1>DDGI + Surface Final Gather：Lambert 对照</h1>
<p>已实现从 GBuffer/VBuffer 可见表面分别采样漫反射与镜面反射、追踪二次命中点并查询 DDGI。静态 1024 spp 相对原始 DDGI 的间接光 MSE 降低 {summary['mse_improvement']:.1%}，但单帧噪声明显增加。尚未实现运动补偿降噪或 reservoir 重采样。</p>
<h2>静态间接光对比</h2><img src="comparison.png"><p>同一显示变换：+3 EV、ACES fitted、sRGB。图像包含表面反射率，无曝光拟合。</p>
<table><tr><th>方法</th><th>累积 spp</th><th>线性 RGB MSE</th><th>Mean HDR-FLIP</th></tr>{rows_html}</table>
<img src="convergence.png"><img src="errors.png">
<h2>测试条件与可信范围</h2><p>480×270；官方 Cornell 几何；白色顶灯点光源强度 1、位置 (0,1.9,0)，关闭太阳与环境。white/red/green 替换为 PBRTDiffuseMaterial。相机 (0.1,1,4) 朝向 (0.1,1,0)。探针 9×9×9、256 rays/probe、2048 帧预热，随后冻结用于静态和相机运动图像。偏移、范围见 scene.json。PT 为 32768 spp、最多 19 surface bounces，关闭 RR，开启 NEE/MIS；独立 32768 spp 序列测得参考间 MSE {noise['mse']:.8f}、HDR-FLIP {noise['hdr_flip']:.4f}，参考并非无噪声真值。</p>
<p>PT 全色减去同机位确定性的点光源直接照明，得到间接光参考；减法后非负。候选为 DDGI.indirect 或累积全色减相同直接光。固定表面 mask，所有 EXR 均检查有限值。HDR-FLIP 沿用前一份报告曝光区间 {params['startExposure']:.3f} 至 {params['stopExposure']:.3f} EV、PPD 67；分辨率和预热预算不同，不直接把绝对数值与旧报告比较。</p>
<h2>相机运动</h2><img src="motion.gif"><p>8 个机位，每帧向右移动 0.04 m，目标同步平移。PT 每机位 512 spp。探针场冻结，场景与光源不变。原始 DDGI 较稳定；final gather 显示未降噪 1 spp。已验证所有移动帧的 Accumulate 输出等于当前原始帧，没有使用旧机位的累积。这个短序列展示噪声和重置行为，不是具有重投影、遮挡剔除的时域降噪评测。</p>
<h2>GPU 耗时</h2><table><tr><th>Pass</th><th>平均 ms</th><th>说明</th></tr>
<tr><td>DDGI</td><td>{timings['baseline']['mean']:.4f}</td><td>探针更新＋屏幕查询</td></tr>
<tr><td>DDGI + gather</td><td>{timings['gather']['mean']:.4f}</td><td>探针更新＋一次漫反射表面追踪；Lambert 无镜面 lobe</td></tr>
<tr><td>PT 1 spp</td><td>{timings['pt-1spp']['mean']:.4f}</td><td>完整 PT pass；非 32768 spp 参考的总成本</td></tr></table>
<p>NVIDIA GeForce RTX 5070、D3D12；各 127 个有效 GPU 时间戳，两个候选均开启相同诊断输出；计时重新开启探针更新，排除 GBuffer、累积、显示、读回和文件写入。简单小场景中 PT 1 spp 更快；不据此推断复杂场景性能，也不能将 1024 帧收敛质量当成一帧质量。</p>
<h2>实现与边界</h2><p>新增 finalGather/gatherDiffuse/gatherSpecular 三个开关，以及独立的 gatherDiffuse/gatherSpecular 输出。默认原始 DDGI 不开启 final gather。两类独立 lobe 的样本加和，不除以二；使用 Falcor 材质采样权重 f·cos/pdf。y 点返回自发光＋直接光（漫反射/镜面）＋Lambert DDGI 间接漫反射；没有 y 之后的镜面递归、透射、屏幕空间追踪、radiance-probe miss fallback、NRD 或 ReSTIR GI。</p>
<p>实验模式绕过外部 RTXDI：x 点只对解析光源做 NEE，环境和发光三角形通过 gather miss/hit 计入，避免无 MIS 时重复计数。因此小发光面/小亮天空的方差可能很大；关闭某个 gather lobe 也会去掉该 lobe 的环境/发光面响应。y 点环境漫反射由 DDGI 提供，环境镜面用现有直接光采样。当前 prototype 的 indirect 输出因此包含 BSDF 采样到的直接环境/发光面；本次无环境、无自发光场景没有这个分类歧义。</p>
<p>纯 Lambert 镜面输出严格为 0；StandardMaterial 测试镜面输出非零（最大 {summary['native_specular_max']:.4f}）。这是通道与材质路由验证，不是镜面画质定量评测。</p>
<p>补充环境光验证结果见 summary.json 的 additional_validation；只收录本地已有且通过的专项运行，包括单位白色天空的 Lambert 能量检查及原有 DDGI/RTXDI/WRC 环境回归。</p>
<h2>复现与启动</h2><p>项目根目录运行 <code>Run-FinalGather.cmd</code>，在 Mogwai 中加载场景；DDGI 面板切换 Surface final gather / Gather diffuse / Gather specular。静态累积可在 Accumulate 面板关闭或重置；更改模式和移动相机会自动重置，但探针持续收敛不会每帧重置累积。</p>
<pre>build\windows-vs2022\bin\Release\Mogwai.exe --device-type d3d12 --headless --deferred --script tests/ddgi/final_gather_compare.py --width 480 --height 270
python tests/ddgi/score_final_gather.py</pre>
<p>评分依赖：<code>python -m pip install --target build/final-gather-python OpenEXR flip-evaluator</code>，另需 numpy、Pillow。原始 EXR/日志/计时位于 build/final-gather-comparison。测试脚本会生成并使用独立点光源配置，不修改默认场景配置。</p>
<h2>参考材料</h2><ul><li><a href="https://advances.realtimerendering.com/s2025/index.html">Assassin’s Creed Shadows SIGGRAPH 2025</a>：屏幕表面射线＋二次命中点探针缓存，漫反射和镜面分开处理。</li><li><a href="https://github.com/EmbarkStudios/kajiya/blob/main/docs/gi-overview.md">kajiya GI overview</a>：final gather、缓存与降噪分工；本实现未移植其自定义缓存。</li><li><a href="https://arxiv.org/abs/2108.05263">DDGI Resampling</a>：以探针终止后续漫反射路径；本实现没有论文的 reservoir 重采样，不能称为完整复现。</li></ul>
<p><a href="summary.json">结构化结果</a> · <a href="metrics.csv">静态指标 CSV</a> · <a href="scene.json">场景参数</a></p></html>"""
(OUT/'report.html').write_text(text,encoding='utf-8')
shutil.copy2(DATA/'scene.json',OUT/'scene.json')
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang',ROOT/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp',ROOT/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h',ROOT/'tests/ddgi/final_gather_compare.py',ROOT/'tests/ddgi/final_gather_lambert.pyscene',ROOT/'scripts/RTXGIDDGIFinalGather.py']}
(OUT/'source-hashes.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'static':rows,'reference_noise':noise,'timings':timings,'output':str(OUT)},indent=2))
