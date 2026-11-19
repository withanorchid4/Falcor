"""Score fresh 1080p DDGI/ReSTIR captures; keep the previous report untouched."""
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
DATA=ROOT/'build/highres-1080p-restir-20261119'
OUT=ROOT/'docs/2026-11-19_1080p全局光照与ReSTIR对比'
OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
MODES=['ddgi','half','full','spatial','restir']
labels={'ddgi':'Original DDGI','half':'Half FG','full':'Full FG',
    'spatial':'Half FG + ReSTIR spatial','restir':'Half FG + ReSTIR temporal/spatial',
    'pt':'PT reference / 65536 spp'}
zh={'ddgi':'原始 DDGI','half':'半分辨率 FG','full':'全分辨率 FG',
    'spatial':'半分辨率 ReSTIR：仅空间','restir':'半分辨率 ReSTIR：时空'}
def read(tag,channel='Accumulate.output'):
    a=OpenEXR.File(str(DATA/(tag+'.'+channel+'.0.exr'))).channels()['RGB'].pixels.astype(np.float32)
    assert a.shape==(1080,1920,3) and np.isfinite(a).all(),tag
    return np.ascontiguousarray(a)
a,b=read('pt-a-32768'),read('pt-b-32768')
ref=np.ascontiguousarray((a+b)*.5)
OpenEXR.File({}, {'RGB':ref}).write(str(DATA/'reference-65536spp.exr'))
mask=np.linalg.norm(read('mask','Visibility.normW'),axis=-1)>.5
np.save(DATA/'surface-mask.npy',mask)
def mse(x,y):return float(np.mean((x[mask].astype(np.float64)-y[mask])**2))
reference_noise=mse(a,b)/4
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
def score(x):
    err=flip_evaluator.evaluate(ref,x,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    return float(err[mask].mean()),err
def display(a):
    x=np.maximum(a,0)*8; x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
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
roi=(760,480,1260,980)
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
    'reference_noise_below_5percent':reference_noise/min(v['mse'] for v in metrics.values())<.05}
result={'metrics':metrics,'timing':timing,'convergence':convergence,'checks':checks,
    'reference_noise_mse_estimate':reference_noise,'flip_parameters':params,'capture':info,
    'scene':json.loads((DATA/'scene.json').read_text()),'metric_domain':'visible surface mask, linear HDR RGB',
    'variance_definition':'32 consecutive frames after 65536: raw and progressively accumulated population variance',
    'display':'ACES fitted +3EV then sRGB','heatmap':'fixed Magma 0..1','crop_xyxy':roi,
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
comparisons=''.join(f"<li>{zh[k]}相对普通半分辨率 FG：最终 MSE {(metrics[k]['mse']/metrics['half']['mse']-1):+.2%}，HDR-FLIP {(metrics[k]['hdr_flip']/metrics['half']['hdr_flip']-1):+.2%}，GPU 耗时 {timing[k]['gpu_frame_ms']/timing['half']['gpu_frame_ms']:.2f} 倍。</li>" for k in ['spatial','restir'])
curve_observation=f"同为 256 帧时，仅空间复用的 MSE 相对普通半分辨率 FG 为 {convergence['spatial']['checkpoint_mse']['256']/convergence['half']['checkpoint_mse']['256']-1:+.2%}，时空复用为 {convergence['restir']['checkpoint_mse']['256']/convergence['half']['checkpoint_mse']['256']-1:+.2%}。本次仅空间复用有小幅等帧数收益，时空复用在中前期反而较慢；按 GPU 预算比较，中前期普通半分辨率 FG 更划算。最终误差略低不等于收敛更快。普通半分辨率 FG 还经过空间重建平滑，而全分辨率 FG 没有，因此两者的噪声不能只按射线数量解释。"
options=''.join(f'<option value="{k}.png">{zh.get(k,"PT Reference")}</option>' for k in MODES+['pt'])
html=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>1080p 全局光照与 ReSTIR 对比</title>
<style>body{{max-width:1500px;margin:32px auto;padding:0 24px;background:#171a20;color:#ddd;font:16px/1.7 system-ui}}img{{max-width:100%}}a{{color:#8dc7ff}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px 12px}}select{{font:inherit}}pre{{white-space:pre-wrap}}</style>
<h1>1080p 全局光照与 ReSTIR 对比 · 2026-11-19</h1>
<p>在旧 1080p 实验基础上，重新渲染原始 DDGI、半分辨率 FG、全分辨率 FG 和 PT reference，加入半分辨率 ReSTIR 的仅空间、时空复用两组。所有图片及耗时均来自本次运行，没有复用旧结果。旧报告保留。</p>
<p>Lambert Cornell、顶灯点光源、Test Harness 衰减、黑色环境；1920×1080，半分辨率追踪 960×540。固定相机与中心 GBuffer 采样，无 NRD、RTXDI。每组 probe 预热 2560 帧，之后持续更新；清空 Accumulate，ReSTIR 冷启动，再累计 65536 帧。与旧 1080p 报告一致，采样偏移关闭，半分辨率从 2×2 的左上像素 (2x,2y) 出发。它不是此前冻结 probe、开启 jitter 的 640×360 实验。</p>
<ul>{comparisons}</ul>
<p>上述比较是有限帧结果，是否稳定见末尾检查。ReSTIR 不保证最终误差更小，也不能仅凭最终图判断收敛速度。</p>
<a href="comparison-1080p.png"><img src="comparison-1080p.png" alt="五组方案和新 PT 参考"></a>
<p>点击图片查看原尺寸六宫格（3840×3396）；每张单图原生 1920×1080，统一 +3EV / ACES fitted / sRGB，无各自曝光调整。</p>
<h2>误差与耗时</h2><table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>原始帧时间方差</th><th>累积帧时间方差</th><th>GPU 帧 ms</th></tr>{rows}</table>
<p>MSE 在可见表面 mask 内对线性 HDR RGB 计算；HDR-FLIP 使用 PPD 67、ACES 和同一参考图决定的曝光范围。PT 每帧 8 spp，两组独立随机种子的 32768 spp 图平均为 65536 spp，不使用降噪。参考剩余噪声估计 MSE={reference_noise:.7g}。时间方差取末尾连续 32 帧的总体方差：原始帧在 Accumulate 前，累积帧在其后；静态累积方差小不代表运动稳定，相关样本的窗口方差也不是无偏估计器方差。旧报告是 8 帧窗口，不能直接比较方差数值。</p>
<h2>收敛曲线</h2><img src="convergence.png">
<p>{curve_observation}</p>
<p>左图按累积帧数比较：三种半分辨率方案每有效粗像素每帧一个新候选；ReSTIR 另有复用、可见性查询与归一化开销。普通 FG 使用原 BRDF 采样，ReSTIR 初始候选为均匀半球，因此不是只改变复用开关的采样器消融。全分辨率 FG 每帧的新候选总数约为半分辨率的四倍；原始 DDGI 没有屏幕 FG 候选。右图按实测稳态 GPU graph 时间折算，不含预热、读取和截图，显示等 GPU 预算趋势。本次各方案只有一条随机序列，不能据曲线小差距断言统计显著加速。</p>
<h2>HDR-FLIP 热力图</h2><p>所有图比较同一张 PT，统一 Magma [0,1] 色标。暗紫黑表示误差小，红橙浅黄表示误差大，深蓝灰是 mask 外。热力图是感知差异，不是百分比相似度，也不表示变亮还是变暗。</p><a href="errors-hdr-flip.png"><img src="errors-hdr-flip.png"></a>
<h2>Pass 组织与计时</h2><pre>原始 DDGI：Visibility → DDGI [ProbeUpdate + PrimaryShading/probe 查询] → Accumulate → Display
普通全分辨率 FG：Visibility → DDGI [ProbeUpdate + PrimaryShading/逐像素 FG] → Accumulate → Display
普通半分辨率 FG：Visibility → DDGI [ProbeUpdate + PrimaryShading + HalfGather] → Reconstruct → Accumulate → Display
半分辨率 ReSTIR：Visibility → DDGI [ProbeUpdate + PrimaryShading + ReSTIRInitial → ReSTIRTemporal → ReSTIRSpatial ×2 → ReSTIRIntegrate] → Reconstruct → Accumulate → Display
PT：Visibility → PT [8 spp/frame, 31 bounces] → Accumulate → Display</pre>
<p>ReSTIR 的 Initial、Temporal、Spatial、Integrate 都是 DDGI pass 内部的 dispatch。仅空间组关闭历史复用，Temporal 阶段负责转发初始 reservoir；时空组使用粗像素历史映射、M 上限 20（包含当前候选）、空间 2 轮×4 邻居、半径 8、偏差校正和重连可见性。空间输出反馈关闭，年龄裁剪关闭。target 为回退后的 Li 亮度，不是 BRDF×cosθ×Li。全分辨率积分关闭；在 960×540 完成积分着色，再由全分辨率 Reconstruct 用深度／法线引导的 16 个粗像素重建，加直接光。probe 配置各组相同（9³、每 probe 256 rays）。</p>
<p>耗时包含持续 probe 更新、GBuffer、FG/复用/重建、Accumulate 和 Display，取 511 个稳态计时间隔均值；不含截图与 CPU 等待。以下内部 dispatch 已包含在 DDGI pass 中，存在嵌套项，不能重复相加。仅本机 RTX 5070 / D3D12。</p>
<table><tr><th>Graph pass / ms</th>{headers}</tr>{stage_rows}</table><br><table><tr><th>DDGI 内部阶段 / ms</th>{headers}</tr>{dispatch_rows}</table>
<h2>单图和细节</h2><select onchange="document.getElementById('single').src=this.value">{options}</select><img id="single" src="ddgi.png"><a href="detail-2x.png"><img src="detail-2x.png"></a>
<h2>收敛检查</h2><table><tr><th>方案</th><th>32768→65536 MSE 变化</th><th>HDR-FLIP 变化</th><th>末次图像差异 MSE / 对 PT 误差</th><th>检查</th></tr>{convrows}</table>
<p>沿用旧报告的实用阈值：末次翻倍 MSE 和 FLIP 变化均小于 3%，图像差异 / 对 PT 误差小于 5%。全部通过：{checks['all_stable_checks_pass']}；PT 噪声估计低于最小方案误差的 5%：{checks['reference_noise_below_5percent']}。这不能证明无限采样无偏，持续变化的 probe 场和时空相关性仍可能影响结果。</p>
<p><a href="summary.json">完整结果与参数</a> · <a href="metrics.csv">指标 CSV</a> · <a href="source-hashes.json">源代码哈希</a>。EXR 与计时原始数据：build/highres-1080p-restir-20261119；复现实验：tests/ddgi/highres_restir_comparison.py，评分：tests/ddgi/score_highres_restir_comparison.py。</p></html>'''
(OUT/'report.html').write_text(html,encoding='utf-8')
print(json.dumps({'checks':checks,'reference_noise':reference_noise,'report':str(OUT/'report.html')},ensure_ascii=False),flush=True)
