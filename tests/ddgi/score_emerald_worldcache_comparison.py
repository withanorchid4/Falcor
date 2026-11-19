"""Score fresh four-way EmeraldSquare captures and produce a self-contained Chinese report."""
from pathlib import Path
import sys,json,re,hashlib
import numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/emerald-worldcache-ddgi-1080p-20261119'
O=R/'docs/2026-11-19_翡翠广场全局光照四组对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
SEQ=info['pt_sequence_spp'];TOTAL=2*SEQ
MODES=['ddgi','half','worldcache'];ALL=MODES+['pt']
labels={'worldcache':'WorldCache + Half FG','ddgi':'Original DDGI','half':'DDGI + Half FG','pt':f'PT Reference / {TOTAL} spp'}
zh={'worldcache':'WorldCache＋半分辨率 FG','ddgi':'原生 DDGI（像素插值 probe）','half':'DDGI＋半分辨率 FG','pt':'PT Reference'}
def read(tag,ch='Accumulate.output'):
 a=OpenEXR.File(str(D/(tag+'.'+ch+'.0.exr'))).channels()['RGB'].pixels
 assert a.shape==(1080,1920,3) and np.isfinite(a).all(),tag
 return np.ascontiguousarray(a,dtype=np.float32)
mask=np.linalg.norm(read('mask','Visibility.normW'),axis=-1)>.5
np.save(D/'surface-mask.npy',mask)
def mse(x,y):return float(np.mean((x[mask].astype(np.float64)-y[mask])**2))
a,b=read('pt-a-'+str(SEQ)),read('pt-b-'+str(SEQ));ref=np.ascontiguousarray((a+b)*.5)
previous=np.ascontiguousarray((read('pt-a-'+str(SEQ//2))+read('pt-b-'+str(SEQ//2)))*.5)
noise=mse(a,b)/4;tail=mse(ref,previous);energy=float(np.mean(ref[mask].astype(np.float64)**2))
OpenEXR.File({}, {'RGB':ref}).write(str(D/f'reference-{TOTAL}spp.exr'))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
def flip(reference,test):
 err=flip_evaluator.evaluate(reference,test,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 return float(err[mask].mean()),err
ref_flip,_=flip(ref,previous)
lum=ref@np.array([.2126,.7152,.0722]);exposure=float(-np.log2(max(np.percentile(lum[mask],99),1e-8)))
def display(a):
 x=np.maximum(a,0)*2**exposure;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(x*255+.5))
src=(R/'Source/RenderPasses/FLIPPass/flip.hlsli').read_text();body=src.split('static const float3 MagmaMap[] = {',1)[1].split('};',1)[0]
magma=np.array([[float(c) for c in v.split(',')] for v in re.findall(r'float3\(([^)]+)\)',body)],dtype=np.float32)
def colorize(a):return np.uint8(np.clip(magma[np.floor(np.clip(a,0,1)*255+.5).astype(np.uint8)],0,1)*255+.5)
metrics={};convergence={};timing={};pictures={'pt':display(ref)};heatmaps={}
for mode in ALL:
 p=json.loads((D/(mode+'-timing.json')).read_text());prefix='/onFrameRender/RenderGraphExe::execute()'
 timing[mode]={'samples':p['frame_count'],'graph_ms':p['events'][prefix+'/gpu_time']['stats']['mean'],'passes':{},'stages':{}}
 for k,v in p['events'].items():
  if k.startswith(prefix+'/') and k.endswith('/gpu_time'):
   name=k[len(prefix)+1:-len('/gpu_time')]
   if name and '/' not in name:timing[mode]['passes'][name]=v['stats']['mean']
   elif name.startswith(('DDGI/','WorldCache/')) and not name.endswith('/raytraceScene'):timing[mode]['stages'][name]=v['stats']['mean']
for mode in MODES:
 s=info['runs'][mode]['stats'];assert s['finite'] and s['rejectedRaySamples']==0
 x=read(mode+'-65536');prior=read(mode+'-32768')
 f,err=flip(ref,x);pf,_=flip(ref,prior);oldref,_=flip(previous,x)
 m=mse(x,ref);oldm=mse(x,previous)
 bright=mask&(lum>=np.percentile(lum[mask],90));pixel_error=np.mean((x.astype(np.float64)-ref)**2,axis=-1)
 metrics[mode]={'mse':m,'hdr_flip':f,'reference_doubling_mse_change':m/oldm-1,'reference_doubling_flip_change':f/oldref-1,
  'brightest_10percent_mse_share':float(pixel_error[bright].sum()/pixel_error[mask].sum())}
 curve={str(n):mse(read(mode+'-'+str(n)),ref) for n in info['checkpoints']}
 convergence[mode]={'checkpoint_mse':curve,'mse_change':m/curve['32768']-1,'flip_change':f/pf-1,'tail_mse':mse(x,prior),'tail_over_error':mse(x,prior)/m}
 c=convergence[mode];c['passed']=abs(c['mse_change'])<.01 and abs(c['flip_change'])<.01 and c['tail_over_error']<.01
 pictures[mode]=display(x);rgb=colorize(err);rgb[~mask]=(23,26,31);heatmaps[mode]=Image.fromarray(rgb)
 heatmaps[mode].save(O/(mode+'-hdr-flip.png'));np.save(D/(mode+'-hdr-flip.npy'),err)
 print(mode,metrics[mode],convergence[mode],timing[mode]['graph_ms'],flush=True)
min_error=min(v['mse'] for v in metrics.values())
checks={'gi_converged':all(c['passed'] for c in convergence.values()),'pt_noise_below_1percent_method_error':noise/min_error<.01,
 'pt_relative_rgb_rms_below_0_5percent':np.sqrt(noise/energy)<.005,'pt_doubling_below_1percent_method_error':tail/min_error<.01,
 'pt_reference_scores_stable':all(abs(v['reference_doubling_flip_change'])<.01 and abs(v['reference_doubling_mse_change'])<.01 for v in metrics.values())}
checks={k:bool(v) for k,v in checks.items()}
reference={'spp':TOTAL,'two_sequences_spp':SEQ,'sequence_frame_seed_ranges':[[1,SEQ//8],[100001,100000+SEQ//8]],'noise_mse_estimate':noise,'doubling_mse':tail,'doubling_hdr_flip':ref_flip,'relative_rgb_rms_noise':float(np.sqrt(noise/energy)),'noise_over_min_error':noise/min_error,'flip_parameters':params}
result={'metrics':metrics,'timing':timing,'convergence':convergence,'checks':checks,'reference':reference,'capture':info,
 'scene':json.loads((D/'scene.json').read_text()),'display_exposure_ev':exposure,'metric_domain':'visible surface mask; linear HDR RGB for MSE; HDR-FLIP PPD 67 ACES shared exposure range',
 'data_directory':str(D),'hardware':'RTX 5070 / D3D12','driver':'621.01'}
runtime=R/'build/emerald-coverage/scene-runtime.json'
if runtime.exists():result['scene']['runtime']=json.loads(runtime.read_text())
result['analysis_source_hash']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
for history in D.glob('reference-check-*.json'):(O/history.name).write_bytes(history.read_bytes())
(O/f'reference-check-{TOTAL}.json').write_text(json.dumps({'reference':reference,'checks':checks,'metrics':metrics},indent=2))
(O/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
for k,img in pictures.items():img.save(O/(k+'.png'))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
def panel(keys,images,w,h,columns=2):
 out=Image.new('RGB',(w*columns,(h+52)*((len(keys)+columns-1)//columns)),(23,26,31));draw=ImageDraw.Draw(out)
 for i,k in enumerate(keys):
  x=i%columns*w;y=i//columns*(h+52);draw.text((x+18,y+10),labels[k],font=font,fill='white');out.paste(images[k],(x,y+52))
 return out
panel(ALL,pictures,1920,1080).save(O/'comparison-1080p.png')
heat=panel(MODES,heatmaps,1920,1080);legend=Image.new('RGB',(heat.width,heat.height+110),(23,26,31));legend.paste(heat,(0,0));draw=ImageDraw.Draw(legend)
legend.paste(Image.fromarray(colorize(np.repeat(np.linspace(0,1,1200,dtype=np.float32)[None,:],28,axis=0))),(24,heat.height+40))
draw.text((24,heat.height+4),'HDR-FLIP | fixed Magma 0-1 | dark = lower error, bright = higher error',font=font,fill='white')
for i in range(6):draw.text((24+i*240,heat.height+70),f'{i/5:.1f}',font=font,fill='white')
legend.save(O/'errors-hdr-flip.png')
roi=(400,540,900,1040);crops={k:v.crop(roi).resize((1000,1000),Image.Resampling.NEAREST) for k,v in pictures.items()}
panel(ALL,crops,1000,1000).save(O/'details.png')
fig,axes=plt.subplots(1,2,figsize=(15,5),layout='constrained')
for mode in MODES:
 ns=np.array(list(map(int,convergence[mode]['checkpoint_mse'])));ys=np.array(list(convergence[mode]['checkpoint_mse'].values()))
 axes[0].loglog(ns,ys,'.-',label=labels[mode]);axes[1].loglog(ns*timing[mode]['graph_ms']/1000,ys,'.-',label=labels[mode])
for ax in axes:ax.grid(True,which='both',alpha=.22);ax.set_ylabel('Linear HDR RGB MSE vs PT');ax.legend(fontsize=8)
axes[0].set_xlabel('Accumulated frames');axes[1].set_xlabel('Estimated GPU seconds (excluding warmup)');fig.savefig(O/'convergence.png',dpi=180);plt.close(fig)
rows=''.join(f'<tr><td>{zh[k]}</td><td>{metrics[k]["mse"]:.7g}</td><td>{metrics[k]["hdr_flip"]:.5f}</td><td>{timing[k]["graph_ms"]:.3f}</td></tr>' for k in MODES)
rows+=f'<tr><td>PT Reference（{TOTAL} spp 总累积）</td><td>—</td><td>—</td><td>{timing["pt"]["graph_ms"]:.3f}（8 spp/帧）</td></tr>'
convrows=''.join(f'<tr><td>{zh[k]}</td><td>{c["mse_change"]:+.3%}</td><td>{c["flip_change"]:+.3%}</td><td>{c["tail_over_error"]:.3%}</td><td>{"通过" if c["passed"] else "未通过"}</td></tr>' for k,c in convergence.items())
headers=''.join('<th>'+zh[k]+'</th>' for k in ALL)
passes=['Visibility','WorldCache','DDGI','PT','Reconstruct','Accumulate','Display']
stage_rows=''.join('<tr><td>'+s+'</td>'+''.join('<td>'+(f'{timing[k]["passes"][s]:.3f}' if s in timing[k]['passes'] else '—')+'</td>' for k in ALL)+'</tr>' for s in passes)
inner=list(dict.fromkeys(s for k in MODES for s in timing[k]['stages']))
inner_rows=''.join('<tr><td>'+s+'</td>'+''.join('<td>'+(f'{timing[k]["stages"][s]:.3f}' if s in timing[k]['stages'] else '—')+'</td>' for k in ALL)+'</tr>' for s in inner)
comparisons=''.join(f'<li>{zh[k]} 相对原生 DDGI：MSE {metrics[k]["mse"]/metrics["ddgi"]["mse"]-1:+.2%}；HDR-FLIP {metrics[k]["hdr_flip"]/metrics["ddgi"]["hdr_flip"]-1:+.2%}；GPU 耗时 {timing[k]["graph_ms"]/timing["ddgi"]["graph_ms"]-1:+.2%}。</li>' for k in ['worldcache','half'])
wccompare=f'WorldCache＋半分辨率 FG 相对 DDGI＋半分辨率 FG：MSE {metrics["worldcache"]["mse"]/metrics["half"]["mse"]-1:+.2%}，HDR-FLIP {metrics["worldcache"]["hdr_flip"]/metrics["half"]["hdr_flip"]-1:+.2%}，GPU 耗时 {timing["worldcache"]["graph_ms"]/timing["half"]["graph_ms"]-1:+.2%}。'

coverage=json.loads((R/'build/emerald-coverage/coverage.json').read_text())
import shutil
for name in ('coverage.png','coarse-preview.png','dense-preview.png','coarse-stats.json','dense-stats.json','scene-runtime.json','asset-manifest.json','environment.json'):
    src=R/'build/emerald-coverage'/name
    if src.exists():shutil.copy2(src,O/name)
(O/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf8')
history_links=' · '.join(f'<a href="{p.name}">{p.stem}</a>' for p in sorted(O.glob('reference-check-*.json')))
options=''.join(f'<option value="{k}.png">{zh[k]}</option>' for k in ALL)
pt_ok=all(v for k,v in checks.items() if k!='gi_converged')
status=('PT 参考通过收敛检查；' if pt_ok else 'PT 参考尚未通过收敛检查；') + ('三组 GI 稳定性检查通过' if checks['gi_converged'] else 'GI 在 65536 帧预算下未通过全部稳定性检查，指标包含残余噪声')
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>翡翠广场全局光照四组对比</title>
<style>body{{max-width:1500px;margin:32px auto;padding:0 24px;background:#171a20;color:#ddd;font:16px/1.7 system-ui}}img{{max-width:100%}}a{{color:#8dc7ff}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px 12px}}select{{font:inherit}}pre{{white-space:pre-wrap}}.note{{color:#ffd293}}</style>
<h1>EmeraldSquareLambert：翡翠广场全局光照四组对比</h1>
<p class="note"><strong>后续诊断补充（2026-11-19）：此轮结果混入了主命中材质处理不一致。</strong>PT 默认跟随 GBuffer 开启 AdjustShadingNormal，而 DDGI/FG 在重建主命中材质时没有传递该标志。关闭 GI、只保留太阳光的对照中，关闭 PT 该修正后，它与 DDGI 的地面输出 MSE 为 0；开启后，测试区域 9088 个法线相关黑点中有 8655 个恢复亮度。因此本报告仍是旧版本实现的实测数据，但不能将这些误差全部归因于 GI 缓存或探针质量。另有双灯均匀单样本选择造成的运动时高方差。待统一材质处理和直接光采样后，应重测公平对比。</p>
<p>1920×1080 · 原生 DDGI、DDGI＋半分辨率 FG、WorldCache＋半分辨率 FG、未降噪 PT Reference。全部使用 Accumulate。ReSTIR、NRD、RTXDI 关闭。实用收敛检查：<b>{status}</b>。</p>
<table><tr><th>方案</th><th>线性 HDR RGB MSE ↓</th><th>HDR-FLIP ↓</th><th>GPU 整图 ms ↓</th></tr>{rows}</table>
<p>表中三种 GI 均为 8192 帧预热后再累积 65536 帧；相同累积帧数不代表三组都到达了完全收敛后的偏差。</p><ul>{comparisons}</ul><p>{wccompare}</p>
<p class="note">这是当前 Falcor 适配和参数的对比，不是完整 UE Lumen 或理想密度 DDGI 的算法排名。未匹配总射线预算或 GPU 时间。WorldCache 不使用 DDGI 探针。</p>
<a href="comparison-1080p.png"><img src="comparison-1080p.png"></a>
<h2>探针覆盖检查</h2>
<p>场景约 997 万实例化三角形，AABB 约 230×113×230 米。读取固定相机的全分辨率 GBuffer 世界位置及法线，排除天空后，现有体积对可见表面的覆盖率为 {coverage['visible_inside_fraction']:.2%}。可见点 Y 范围约 −0.2～42.85 米，93.26% 位于 20 米以下。</p>
<p>启动默认网格是 32×16×32，间距 7.74×8×7.74 米；本次实验提高到 32×32×32=32768 probes，范围仍为 (−120,−6,−120)～(120,114,120)，间距 7.74×3.87×7.74 米。仅调整实验脚本，不改变启动默认配置。每 probe 256 rays，hysteresis=0.97，relocation/classification 开启，normal/view/min-frontface 世界距离为 0.1/0.3/0.3 米。两条 DDGI 路径采用同一配置。</p>
<p class="note">包围盒包含所有可见点不等于插值质量充分：水平探针仍稀疏，细小植被、窄遮挡、建筑内部可能存在泄漏或过暗。本次保持全城覆盖，不用裁切体积换取默认相机的局部高密度。分类可能将空中或封闭区域探针置为 inactive；数量与预热后状态见 summary.json。</p>
<img src="coverage.png"><p>下图为原始粗网格的探针位置检查；绿色为 active、红色为 inactive。球体半径是最小网格间距的 8%，加密前后球体大小不同。探针显示仅用于检查，正式图像和耗时均关闭。</p><img src="coarse-preview.png"><p>本次 32³ 网格：</p><img src="dense-preview.png">
<h2>统一实验条件</h2>
<p>使用官方白天版相机、太阳光、点光源及 HDR 天空，冻结场景动画。全部表面替换为 PBRTDiffuseMaterial（ρ/π），保留颜色、法线和透明裁剪；无镜面、透射或表面自发光。资源来自 <a href="https://developer.nvidia.com/orca/nvidia-emerald-square">NVIDIA ORCA Emerald Square</a>，Nicholas Hull、Kate Anderson、Nir Benty，CC BY-NC-SA 3.0。</p>
<p>三种 GI 各预热 8192 帧，再清空 Accumulate，累积 65536 帧；缓存持续更新。累积精度 SingleCompensated。两条 FG 均为 960×540，在每个 2×2 块左上角发射一条漫反射射线，jitter 关闭，使用相同深度／法线引导重建。WorldCache 表容量 2²⁰、density=20、最小 cell 宽度 0.025、每 8×8 像素一条缓存更新路径、3 次更新顶点及末端缓存查询、历史 16、64 帧未用淘汰、亮度截断关闭。</p>
<p>PT 为 8 spp/帧、31 次最大表面及漫反射反弹、NEE+MIS、RR 关闭、不降噪。两条独立序列各 {SEQ} spp，等权线性平均得到 {TOTAL} spp 参考。初始参考不足时追加连续且不重复的样本。</p>
<h2>指标与显示</h2>
<p>MSE 在共同可见表面 mask 内对未曝光、未色调映射 HDR RGB 求均方误差；HDR-FLIP 使用 PPD=67、ACES，以及由同一 PT 推导的曝光范围。天空不参与评分。不同场景亮度尺度不同，不能直接拿这里的 MSE 数值和 Sponza/Cornell 排名。</p>
<p>最亮 10% 表面对各方案总平方误差的贡献：{', '.join(zh[k]+' '+format(metrics[k]['brightest_10percent_mse_share'],'.2%') for k in MODES)}。所有 PNG 共用 {exposure:+.4f} EV（由 PT 可见表面亮度第 99 百分位决定）、ACES fitted 和 sRGB；展示曝光不影响 MSE。</p>
<h2>HDR-FLIP 热力图</h2><p>统一 Magma [0,1]，暗紫黑误差低、红橙浅黄误差高；不是百分比差异，也不区分偏亮／偏暗。mask 外及留白为深灰。</p><a href="errors-hdr-flip.png"><img src="errors-hdr-flip.png"></a>
<h2>收敛检查</h2><p class="note">本场景的官方 HDR 天空包含极高亮区域：RGB 最大值 146432，亮度中位数约 0.189、最大值约 128757；亮度超过 100 的像素仅占经纬纹理约 0.00465%（非立体角比例）。当前两条 FG 在首跳使用材质采样，miss 后读取天空，没有对此跳做环境 NEE/MIS；PT 使用 NEE+MIS。这是 FG 高方差的合理来源，尚未通过拆分光照的消融实验定量归因。没有降低 HDR 亮度、裁剪火花或启用降噪来改变本次对比。若某组未通过下面的检查，其指标代表给定累积帧数下的结果，不能称为完全收敛后的偏差。</p><img src="convergence.png">
<table><tr><th>方案</th><th>32768→65536 MSE 变化</th><th>HDR-FLIP 变化</th><th>前后图像差异 MSE / 对 PT 误差</th><th>检查</th></tr>{convrows}</table>
<p>GI 要求上述三项绝对比例低于 1%。PT 独立序列差异 MSE/4={noise:.7g}，估计参考残余噪声，占最小方案误差 {noise/min_error:.3%}；噪声 RMS/参考 RGB RMS={np.sqrt(noise/energy):.3%}。参考翻倍图像差异 MSE={tail:.7g}，HDR-FLIP={ref_flip:.5f}。</p>
<p>PT 阈值：噪声及翻倍差异低于最小方案误差的 1%，相对 RGB RMS 噪声低于 0.5%，各方案 MSE/HDR-FLIP 随参考翻倍变化低于 1%。这是有限采样实用检查，不证明每个像素完全收敛。检查结果：{json.dumps(checks,ensure_ascii=False)}。</p>
<h2>Pass 组织和 GPU 耗时</h2><pre>原生 DDGI：Visibility → DDGI [ProbeUpdate → PrimaryShading / probe interpolation] → Accumulate → Display
DDGI + Half FG：Visibility → DDGI [ProbeUpdate → PrimaryShading → HalfGather] → Reconstruct → Accumulate → Display
WorldCache + Half FG：Visibility → WorldCache [CachePaths → CacheResolve → PrimaryShading → HalfGather] → Reconstruct → Accumulate → Display
PT Reference：Visibility → PT [8 spp/frame] → Accumulate → Display</pre>
<p>RTX 5070 / D3D12。每组计时 {timing['ddgi']['samples']} 帧，包含探针／缓存更新、GBuffer、着色、重建、累积及 ToneMapper；不含截图和统计回读。内部子阶段已计入父 pass，不能重复相加。PT 计时固定末次随机种子，生成参考图时则逐帧更换种子；PT 单帧耗时不是生成整张参考图的总成本；收敛曲线 GPU 时间轴为稳态整图时间×帧数，不含预热。</p>
<table><tr><th>Pass / ms</th>{headers}</tr>{stage_rows}</table><br><table><tr><th>GI 内部阶段 / ms</th>{headers}</tr>{inner_rows}</table>
<h2>原生单图与细节</h2><p>局部放大取原图 (400,540)～(900,1040)，观察自行车架、近处地面与阴影。</p><select onchange="document.getElementById('single').src=this.value">{options}</select><img id="single" src="worldcache.png"><a href="details.png"><img src="details.png"></a>
<p>PT 递增检查：{history_links}</p><p><a href="summary.json">完整结果和配置</a> · <a href="coverage.json">覆盖统计</a>。原始数据：build/emerald-worldcache-ddgi-1080p-20261119；运行／评分脚本：tests/ddgi/emerald_worldcache_comparison.py、score_emerald_worldcache_comparison.py。未覆盖旧实验。</p></html>'''
(O/'report.html').write_text(page,encoding='utf8')
print(json.dumps({'checks':checks,'reference':reference,'report':str(O/'report.html')},ensure_ascii=False),flush=True)
