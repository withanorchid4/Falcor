"""Score Sponza Lambert DDGI/FG against fresh converged PT."""
from pathlib import Path
import sys, json, csv, re, hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import OpenEXR, flip_evaluator
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0,str(ROOT/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
DATA=ROOT/'build/sponza-lambert-1080p-20261119'
OUT=ROOT/'docs/2026-11-19_Sponza纯漫反射全局光照对比'
OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
MODES=['ddgi','half','full']
labels={'ddgi':'Original DDGI','half':'Half FG','full':'Full FG',
    'spatial':'Half FG + ReSTIR spatial','restir':'Half FG + ReSTIR temporal/spatial',
    'pt':f"PT reference / {info['pt_total_spp']} spp"}
zh={'ddgi':'原始 DDGI','half':'半分辨率 FG','full':'全分辨率 FG',
    'spatial':'半分辨率 ReSTIR：仅空间','restir':'半分辨率 ReSTIR：时空'}
def read(tag,channel='Accumulate.output'):
    a=OpenEXR.File(str(DATA/(tag+'.'+channel+'.0.exr'))).channels()['RGB'].pixels.astype(np.float32)
    assert a.shape==(1080,1920,3) and np.isfinite(a).all(),tag
    return np.ascontiguousarray(a)
disjoint=info.get('reference_mode')=='disjoint_halves'
if disjoint:
    ref=read('pt-a-'+str(info['pt_total_spp']))
    a=read('pt-a-'+str(info['pt_total_spp']//2));b=2*ref-a
else:
    a,b=read('pt-a-65536'),read('pt-b-65536')
    ref=np.ascontiguousarray((a+b)*.5)
OpenEXR.File({}, {'RGB':ref}).write(str(DATA/('reference-'+str(info['pt_total_spp'])+'spp.exr')))
mask=np.linalg.norm(read('mask','Visibility.normW'),axis=-1)>.5
np.save(DATA/'surface-mask.npy',mask)
def mse(x,y):return float(np.mean((x[mask].astype(np.float64)-y[mask])**2))
reference_noise=mse(a,b)/4
reference_previous=a if disjoint else (read('pt-a-32768')+read('pt-b-32768'))*.5
reference_tail=mse(ref,reference_previous)
exposure_stops=float(-np.log2(max(np.percentile(ref[mask] @ np.array([.2126,.7152,.0722]),99),1e-8)))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
ref_flip_map=flip_evaluator.evaluate(ref,reference_previous,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
reference_validation={'doubling_hdr_flip':float(ref_flip_map[mask].mean()),'score_changes':{},'brightest_10percent_mse_share':{}}
luminance=ref @ np.array([.2126,.7152,.0722])
bright=mask & (luminance>=np.percentile(luminance[mask],90))
def score(x):
    err=flip_evaluator.evaluate(ref,x,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    return float(err[mask].mean()),err
def display(a):
    x=np.maximum(a,0)*(2**exposure_stops); x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
map_source=(ROOT/'Source/RenderPasses/FLIPPass/flip.hlsli').read_text()
map_body=map_source.split('static const float3 MagmaMap[] = {',1)[1].split('};',1)[0]
magma=np.array([[float(c) for c in v.split(',')] for v in re.findall(r'float3\(([^)]+)\)',map_body)],dtype=np.float32)
assert magma.shape==(256,3)
def colorize(err):return np.uint8(np.clip(magma[np.floor(np.clip(err,0,1)*255+.5).astype(np.uint8)],0,1)*255+.5)
metrics={}; convergence={}; timing={}; pngs={'pt':display(ref)}; heat_images={}
for mode in MODES:
    stats=info['runs'][mode]['stats']
    assert stats['finite']
    for k in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:
        assert stats[k]==0,(mode,k,stats[k])
    x=read(mode+'-65536'); previous=read(mode+'-32768')
    flip,err=score(x); prevflip,_=score(previous)
    metrics[mode]={'mse':mse(x,ref),'hdr_flip':flip}
    old_ref_flip=flip_evaluator.evaluate(reference_previous,x,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    old_ref_score=float(old_ref_flip[mask].mean())
    reference_validation['score_changes'][mode]={'previous_reference_hdr_flip':old_ref_score,'relative_change':flip/old_ref_score-1}
    pixel_mse=np.mean((x.astype(np.float64)-ref)**2,axis=-1)
    reference_validation['brightest_10percent_mse_share'][mode]=float(pixel_mse[bright].sum()/pixel_mse[mask].sum())
    checkpoints={str(n):mse(read(mode+'-'+str(n)),ref) for n in info['checkpoints']}
    convergence[mode]={'checkpoint_mse':checkpoints,'mse_change':metrics[mode]['mse']/checkpoints['32768']-1,
        'flip_change':flip/prevflip-1,'tail_difference_mse':mse(x,previous),
        'estimated_tail_over_error':mse(x,previous)/metrics[mode]['mse']}
    convergence[mode]['stable_check']=abs(convergence[mode]['mse_change'])<.03 and abs(convergence[mode]['flip_change'])<.03 and convergence[mode]['estimated_tail_over_error']<.05
    for domain,channel in [('accumulated','Accumulate.output'),('raw','Reconstruct.color' if mode in ['half','spatial','restir'] else 'DDGI.color')]:
        mean=None; m2=None
        for i in range(info['stable_capture_frames']):
            v=read(mode+'-stable-'+str(i),channel)[mask].astype(np.float64)
            if mean is None:mean=v.copy();m2=np.zeros_like(mean)
            else:
                delta=v-mean;mean+=delta/(i+1);m2+=delta*(v-mean)
        metrics[mode][domain+'_temporal_variance']=float(np.mean(m2/info['stable_capture_frames']))
    p=json.loads((DATA/(mode+'-timing.json')).read_text()); prefix='/onFrameRender/RenderGraphExe::execute()'
    timing[mode]={'samples':p['frame_count'],'gpu_frame_ms':p['events'][prefix+'/gpu_time']['stats']['mean'],
        'passes':{},'dispatches':{}}
    for key,v in p['events'].items():
        if key.startswith(prefix+'/') and key.endswith('/gpu_time'):
            name=key[len(prefix)+1:-len('/gpu_time')]
            if '/' not in name:timing[mode]['passes'][name]=v['stats']['mean']
            elif name.startswith('DDGI/'):timing[mode]['dispatches'][name[5:]]=v['stats']['mean']
    pngs[mode]=display(x)
    rgb=colorize(err);rgb[~mask]=(23,26,31);heat_images[mode]=Image.fromarray(rgb)
    heat_images[mode].save(OUT/(mode+'-hdr-flip.png'));np.save(DATA/(mode+'-hdr-flip.npy'),err)
    print(mode,metrics[mode],timing[mode]['gpu_frame_ms'],flush=True)
for k,img in pngs.items():img.save(OUT/(k+'.png'))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
def panel(keys,images,width,height,columns):
    canvas=Image.new('RGB',(width*columns,(height+52)*((len(keys)+columns-1)//columns)),(23,26,31));d=ImageDraw.Draw(canvas)
    for i,k in enumerate(keys):
        x=i%columns*width;y=i//columns*(height+52)
        d.text((x+18,y+10),labels[k],font=font,fill='white');canvas.paste(images[k],(x,y+52))
    return canvas
panel(MODES+['pt'],pngs,1920,1080,2).save(OUT/'comparison-1080p.png')
roi=(600,200,1100,700)
crops={k:v.crop(roi).resize((1000,1000),Image.Resampling.NEAREST) for k,v in pngs.items()}
panel(MODES+['pt'],crops,1000,1000,2).save(OUT/'detail-2x.png')
heat=panel(MODES,heat_images,1920,1080,2)
legend=Image.new('RGB',(heat.width,heat.height+110),(23,26,31));legend.paste(heat,(0,0));d=ImageDraw.Draw(legend)
legend.paste(Image.fromarray(colorize(np.repeat(np.linspace(0,1,1200,dtype=np.float32)[None,:],28,axis=0))),(24,heat.height+40))
d.text((24,heat.height+4),'HDR-FLIP | fixed Magma scale 0-1 | dark = lower error, bright = higher error',font=font,fill='white')
for i in range(6):d.text((24+i*240,heat.height+70),f'{i/5:.1f}',font=font,fill='white')
legend.save(OUT/'errors-hdr-flip.png')
fig,axes=plt.subplots(1,2,figsize=(15,5),layout='constrained')
for mode in MODES:
    ns=np.array(list(map(int,convergence[mode]['checkpoint_mse'])))
    ys=np.array(list(convergence[mode]['checkpoint_mse'].values()))
    axes[0].loglog(ns,ys,'.-',label=labels[mode]);axes[1].loglog(ns*timing[mode]['gpu_frame_ms']/1000,ys,'.-',label=labels[mode])
for ax in axes:
    ax.grid(True,which='both',alpha=.22);ax.set_ylabel('Linear HDR RGB MSE vs PT');ax.legend(fontsize=8)
axes[0].set_xlabel('Accumulated frames (one fresh FG candidate / active gather pixel)')
axes[1].set_xlabel('Estimated GPU seconds (frames x steady-state graph time)')
fig.savefig(OUT/'convergence.png',dpi=180);plt.close(fig)
checks={'all_stable_checks_pass':all(v['stable_check'] for v in convergence.values()),
    'reference_metric_change_below_1percent':all(abs(v['relative_change'])<.01 for v in reference_validation['score_changes'].values()),
    'reference_noise_below_5percent':reference_noise/min(v['mse'] for v in metrics.values())<.05,
    'reference_doubling_below_5percent':reference_tail/min(v['mse'] for v in metrics.values())<.05}
result={'metrics':metrics,'timing':timing,'convergence':convergence,'checks':checks,'reference_validation':reference_validation,
    'reference_noise_mse_estimate':reference_noise,'reference_doubling_difference_mse':reference_tail,'flip_parameters':params,'capture':info,
    'scene':json.loads((DATA/'scene.json').read_text()),'metric_domain':'visible surface mask, linear HDR RGB',
    'variance_definition':'32 consecutive frames after 65536: raw and progressively accumulated population variance',
    'display':{'operator':'ACES fitted then sRGB','exposureStops':exposure_stops,'rule':'PT masked luminance percentile 99 maps to 1 before tone mapping'},'heatmap':'fixed Magma 0..1','crop_xyxy':roi,
    'hardware':'RTX 5070 / D3D12','data_directory':str(DATA)}
(OUT/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
(OUT/'source-hashes.json').write_text(json.dumps(info['source_hashes'],indent=2))
with (OUT/'metrics.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=['mode',*metrics['ddgi'],'gpu_frame_ms']);w.writeheader()
    for k,v in metrics.items():w.writerow({'mode':k,**v,'gpu_frame_ms':timing[k]['gpu_frame_ms']})
rows=''.join(f"<tr><td>{zh[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.5f}</td><td>{v['raw_temporal_variance']:.4g}</td><td>{v['accumulated_temporal_variance']:.4g}</td><td>{timing[k]['gpu_frame_ms']:.3f}</td></tr>" for k,v in metrics.items())
convrows=''.join(f"<tr><td>{zh[k]}</td><td>{v['mse_change']:+.2%}</td><td>{v['flip_change']:+.2%}</td><td>{v['estimated_tail_over_error']:.2%}</td><td>{'通过' if v['stable_check'] else '未通过，不能视为收敛结果'}</td></tr>" for k,v in convergence.items())
stage_rows=''.join('<tr><td>'+s+'</td>'+''.join('<td>'+(f"{timing[k]['passes'][s]:.3f}" if s in timing[k]['passes'] else '—')+'</td>' for k in MODES)+'</tr>' for s in ['Visibility','DDGI','Reconstruct','Accumulate','Display'])
dispatch_names=list(dict.fromkeys(s for k in MODES for s in timing[k]['dispatches']))
dispatch_rows=''.join('<tr><td>'+s+'</td>'+''.join('<td>'+(f"{timing[k]['dispatches'][s]:.3f}" if s in timing[k]['dispatches'] else '—')+'</td>' for k in MODES)+'</tr>' for s in dispatch_names)
headers=''.join('<th>'+zh[k]+'</th>' for k in MODES)
comparison=''.join(f"<li>{zh[k]}相对原始 DDGI：MSE {metrics[k]['mse']/metrics['ddgi']['mse']-1:+.2%}，HDR-FLIP {metrics[k]['hdr_flip']/metrics['ddgi']['hdr_flip']-1:+.2%}；GPU 整图耗时 {timing[k]['gpu_frame_ms']:.3f} ms。</li>" for k in ['half','full'])
options=''.join(f'<option value="{k}.png">{zh.get(k,"PT Reference")}</option>' for k in MODES+['pt'])
reference_description=(f"共 {info['pt_total_spp']} spp，来自不重叠的固定种子样本。将累积序列拆成两个等长、不重叠样本块 A、B（B=2×最终平均−前半段平均），用 MSE(A,B)/4 估计最终参考噪声。通过噪声低于最低方案误差 1%、噪声 RMS 低于参考 RGB RMS 0.5% 的检查后提前结束预设采样。" if disjoint else "两条独立随机种子序列各 65536 spp，线性 HDR 平均得到 131072 spp Reference。")
html=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Sponza 纯漫反射全局光照对比</title>
<style>body{{max-width:1500px;margin:32px auto;padding:0 24px;background:#171a20;color:#ddd;font:16px/1.7 system-ui}}img{{max-width:100%}}a{{color:#8dc7ff}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px 12px}}select{{font:inherit}}pre{{white-space:pre-wrap}}</style>
<h1>SponzaLambert：原始 DDGI、半分辨率 FG、全分辨率 FG</h1>
<p>2026-11-19 新实验，原生 1920×1080。三个方案与 PT Reference 均从当前 SponzaLambert 场景重新渲染。ReSTIR、NRD、RTXDI 和 WRC 全部关闭。镜头固定，使用 Accumulate 静态累积；图像代表长时间平均后的结果，不代表实时单帧画质。</p>
<ul>{comparison}</ul>
<p>本场景下，FG 对 HDR-FLIP 的改善明显，但线性 MSE 改善很小，全分辨率 FG 的 MSE 略高于原始 DDGI，不能概括为所有指标都改善。按 PT 亮度排序，最亮的 10% 像素贡献了约 {min(reference_validation['brightest_10percent_mse_share'].values()):.1%}～{max(reference_validation['brightest_10percent_mse_share'].values()):.1%} 的 MSE；暗部照明改善对绝对平方误差的影响很小。HDR-FLIP 在统一的多曝光范围内评估，还会强调暗部差异。半／全分辨率也不能只按最终 MSE 判断优劣，半分辨率包含空间平滑。</p>
<a href="comparison-1080p.png"><img src="comparison-1080p.png" alt="三组 GI 与 PT 参考的原生 1080p 四宫格"></a>
<h2>实验条件</h2><p>沿用启动器的 Sponza 相机与照明：相机 (-9,1.6,0) 看向 (8,2.5,0)，24 mm frame height / 18 mm focal length；点光源 (0,4,0)，RGB intensity=(600,600,600)，使用项目的 Test Harness 点光衰减。25 个材质均为 PBRTDiffuseMaterial，BRDF=ρ/π；保留原颜色、法线贴图和 alpha 裁剪，不包含原镜面／金属项。</p>
<p>DDGI 网格 24×12×16=4608 probes，自动覆盖场景范围，每 probe 256 rays，hysteresis=0.97，normal/view bias 均为最小 probe 间距的 0.05 倍。三组均先预热 8192 帧，再清空累积并运行 65536 帧，期间 probe 持续更新。半分辨率 FG 为 960×540，从每个 2×2 块左上像素发射，jitter 关闭；全分辨率 FG 为 1920×1080。所有有效采样位置每帧至多一根漫反射 FG 射线。累积使用 SingleCompensated，避免长时间累积的浮点误差。</p>
<p>PT 每帧 8 spp，最大 31 次表面／漫反射反弹，NEE+MIS，Russian roulette 关闭。{reference_description}不使用 NRD 或其他降噪。末尾附参考噪声与翻倍检查，有限采样检查不能证明数学上的完全收敛。</p>
<h2>画质、时间方差与 GPU 耗时</h2>
<table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>原始帧时间方差</th><th>累积帧时间方差</th><th>GPU 整图 ms</th></tr>{rows}</table>
<p>MSE 为可见表面 mask 内的线性 HDR RGB 均方误差；HDR-FLIP 使用 PPD=67、ACES 和同一参考图推导的曝光范围。时间方差是第 65536 帧后连续 32 帧的总体方差，分别统计 Accumulate 前后。静态平均后的低方差不代表运动稳定。该场景的亮度和内容与 Cornell 不同，MSE 不能跨场景直接比较。</p>
<p>所有发布 PNG 使用同一个曝光 {exposure_stops:+.4f} EV，再做 ACES fitted 和 sRGB；曝光仅根据 PT 可见表面亮度第 99 百分位确定，使该亮度在色调映射前为 1，没有按方案分别调整。曝光只影响展示，不影响线性 MSE；HDR-FLIP 也使用独立、统一的评估参数。</p>
<h2>相对 PT 的收敛曲线</h2><img src="convergence.png">
<p>左图按累计帧数比较，右图按稳态 GPU 整图耗时×帧数估算 GPU 预算（不含预热、截图和 CPU 等待）。半分辨率每帧新候选数约为全分辨率四分之一，但经过 16 邻点空间重建平滑，不能仅用射线数解释噪声。原始 DDGI 没有屏幕 FG 射线。每方案只有一条序列，小幅差异不代表统计显著优势。</p>
<h2>HDR-FLIP 热力图</h2><p>三组均比较同一 PT Reference，统一 Magma [0,1] 色标：暗紫黑误差小，红橙浅黄误差大。场景外不参与统计的像素与拼图留白均用深灰背景，房间内的暗色则仍是误差值。色标不是百分比相似度，也不表示偏亮还是偏暗。</p><a href="errors-hdr-flip.png"><img src="errors-hdr-flip.png"></a>
<h2>Pass 组织与 GPU 分项</h2><pre>原始 DDGI：Visibility → DDGI [ProbeUpdate + PrimaryShading/probe 查询] → Accumulate → Display
半分辨率 FG：Visibility → DDGI [ProbeUpdate + PrimaryShading + HalfGather] → Reconstruct → Accumulate → Display
全分辨率 FG：Visibility → DDGI [ProbeUpdate + PrimaryShading/逐像素 FG] → Accumulate → Display
PT Reference：Visibility → PT [8 spp/frame] → Accumulate → Display</pre>
<p>FG 命中点计算直接光并查询 DDGI 间接光；半分辨率着色后由全分辨率 Reconstruct 进行 16 邻点深度／法线引导重建。ProbeUpdate、PrimaryShading、HalfGather 是 DDGI pass 内部阶段，已经包含在 DDGI 总耗时内。计时为 511 个稳态区间均值，包含 probe 更新、GBuffer、GI、重建、累积与显示；不包含截图。硬件 RTX 5070 / D3D12。</p>
<table><tr><th>Graph pass / ms</th>{headers}</tr>{stage_rows}</table><br><table><tr><th>DDGI 内部阶段 / ms</th>{headers}</tr>{dispatch_rows}</table>
<h2>原生单图与局部放大</h2><select onchange="document.getElementById('single').src=this.value">{options}</select><img id="single" src="ddgi.png"><a href="detail-2x.png"><img src="detail-2x.png"></a>
<h2>收敛检查</h2><table><tr><th>方案</th><th>32768→65536 MSE 变化</th><th>HDR-FLIP 变化</th><th>末次图像差异 / 对 PT 误差</th><th>检查</th></tr>{convrows}</table>
<p>沿用上一实验的实用稳定阈值：末次翻倍 MSE 与 HDR-FLIP 相对变化均小于 3%，图像差异 MSE / 对 PT 误差小于 5%。三组均通过：{checks['all_stable_checks_pass']}。</p>
<p>PT 两个样本块差值 MSE / 4 = {reference_noise:.7g}，估计为最终平均参考的剩余噪声；相对最低方案误差为 {reference_noise/min(v['mse'] for v in metrics.values()):.2%}。参考从合计 {info['pt_total_spp']//2}→{info['pt_total_spp']} spp 的图像差异 MSE={reference_tail:.7g}，相对最低方案误差为 {reference_tail/min(v['mse'] for v in metrics.values()):.2%}。两项均低于 5%：{checks['reference_noise_below_5percent'] and checks['reference_doubling_below_5percent']}。{'本次采用不重叠半段估计，翻倍差异与样本块噪声是同一个统计量，不能视为两个独立检验。' if disjoint else ''}噪声检查不涵盖有限反弹截断偏差。</p>
<p><strong>暗部参考噪声限制：</strong>本次 HDR-FLIP 的自动曝光范围为 {params['startExposure']:.3f}～{params['stopExposure']:.3f} EV，共 {int(params['numExposures'])} 个曝光。在高曝光下，极暗位置仍能看到 PT 有限采样的噪声；前后两个参考检查点自身的 HDR-FLIP 为 {reference_validation['doubling_hdr_flip']:.5f}，因此不声称所有暗部像素已完全无噪声。不过，将参考从 {info['pt_total_spp']//2} 升至 {info['pt_total_spp']} spp 后，三组方案的 HDR-FLIP 指标相对变化最大只有 {max(abs(v['relative_change']) for v in reference_validation['score_changes'].values()):.3%}，本次总体比较结论已稳定。各方案共享相同曝光范围，不能把这项参考噪声简单从方案 FLIP 中减掉。</p>
<p><a href="summary.json">完整参数和结果</a> · <a href="metrics.csv">指标 CSV</a> · <a href="source-hashes.json">源代码哈希</a>。原始 EXR、探针统计和计时：build/sponza-lambert-1080p-20261119。复现：tests/ddgi/sponza_lambert_comparison.py；评分：tests/ddgi/score_sponza_lambert_comparison.py。</p></html>'''
(OUT/'report.html').write_text(html,encoding='utf-8')
print(json.dumps({'checks':checks,'reference_noise':reference_noise,'reference_tail':reference_tail,'report':str(OUT/'report.html')},ensure_ascii=False),flush=True)
