"""Score fresh four-way Sponza captures and produce a self-contained Chinese report."""
from pathlib import Path
import sys,json,re,hashlib
import numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-worldcache-ddgi-1080p-20261119'
O=R/'docs/2026-11-19_Sponza世界缓存与DDGI四组对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
SEQ=info['pt_sequence_spp'];TOTAL=2*SEQ
MODES=['worldcache','ddgi','half'];ALL=MODES+['pt']
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
   if '/' not in name:timing[mode]['passes'][name]=v['stats']['mean']
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
roi=(600,200,1100,700);crops={k:v.crop(roi).resize((1000,1000),Image.Resampling.NEAREST) for k,v in pictures.items()}
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
extension_note=('首轮合计 32768 spp 时，WorldCache 的 HDR-FLIP 随参考翻倍变化约 1.98%，超过预设 1% 阈值，因此继续追加 PT。新增样本沿用原种子序列后续区间，与旧样本等权合并；三组 GI 未重跑。' if info.get('pt_extensions') else '')
if len(info.get('pt_extensions',[]))>1: extension_note += ' 合计 65536 spp 时该变化为 1.001%，仍略超阈值，因此继续补到 131072 spp。'
options=''.join(f'<option value="{k}.png">{zh[k]}</option>' for k in ALL)
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Sponza 世界缓存与 DDGI 四组对比</title>
<style>body{{max-width:1500px;margin:32px auto;padding:0 24px;background:#171a20;color:#ddd;font:16px/1.7 system-ui}}img{{max-width:100%}}a{{color:#8dc7ff}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px 12px}}select{{font:inherit}}pre{{white-space:pre-wrap}}.note{{color:#ffd293}}</style>
<h1>SponzaLambert：WorldCache、DDGI 与 PT Reference</h1>
<p>2026-11-19 · 四组全部重新运行 · 原生 1920×1080。三种 GI 均使用 Accumulate；PT 使用未经降噪的参考累积。ReSTIR、NRD、RTXDI 全部关闭。WorldCache 为当前 Falcor 实验性适配，不是完整 UE Lumen 的性能或质量结果。</p>
<table><tr><th>方案</th><th>线性 HDR RGB MSE ↓</th><th>HDR-FLIP ↓</th><th>GPU 整图 ms ↓</th></tr>{rows}</table>
<ul>{comparisons}</ul><p>{wccompare}</p>
<p class="note">这是当前参数下的方案对比，没有强制匹配 GPU 时间或缓存射线预算；单场景、单条 GI 随机序列不能代表算法普遍优劣。PT 的毫秒数是 8 spp 的单帧成本，不是取得整张 {TOTAL} spp Reference 的总成本。</p>
<a href="comparison-1080p.png"><img src="comparison-1080p.png" alt="四组原生1080p画面对比"></a>
<h2>统一实验条件</h2>
<p>SponzaLambert 保留颜色、法线贴图和 alpha 裁剪，所有材质替换为 PBRTDiffuseMaterial（ρ/π），没有镜面项。相机 (-9,1.6,0) 看向 (8,2.5,0)，frame height 24 mm / focal length 18 mm；点光源 (0,4,0)，RGB intensity=(600,600,600)，方向光关闭。各路径使用当前项目相同的解析点光源衰减。</p>
<p>三种 GI 各预热 8192 帧，之后清空 Accumulate，累积 65536 帧。缓存／探针持续更新，不冻结。累积精度 SingleCompensated，静态测试关闭自动重置；截图输出在累积开始前注册。两条 FG 均为 960×540，每个 2×2 块左上像素每帧发射一根漫反射射线，jitter 关闭，再用同一套深度／法线引导重建。FG 射线预算相同，缓存更新预算不同。</p>
<p>DDGI：24×12×16=4608 probes，每 probe 256 rays，autoBounds，hysteresis=0.97，normal/view bias 均为最小探针间距的 0.05 倍，启用 relocation/classification。WorldCache：2²⁰ 表容量，cell density=20，最小 cell 宽度 0.025；每 8×8 像素随机选一条缓存更新路径，3 个更新顶点＋末端缓存查询，历史长度 16、64 帧未使用淘汰，亮度截断关闭；没有 DDGI 探针。该适配尚未实现 UE 的查询滤波、跨层历史迁移和俄罗斯轮盘。</p>
<p>PT：8 spp/帧，31 次最大表面／漫反射反弹，NEE+MIS，RR 关闭，不降噪。两条独立种子序列各 {SEQ} spp，线性平均得到 {TOTAL} spp Reference。它是有限采样、有限路径长度的参考，下方给出实用收敛检查。</p>
<h2>指标与显示</h2>
<p>MSE 在共同可见表面 mask 内，对未经曝光和色调映射的 HDR RGB 计算平均平方误差；HDR-FLIP 使用 PPD=67、ACES 和同一 PT 推导的曝光范围。MSE 可能由少量高亮像素主导；按 PT 亮度排序，最亮 10% 像素的误差占比分别为：{', '.join(zh[k]+' '+format(metrics[k]['brightest_10percent_mse_share'],'.2%') for k in MODES)}。</p>
<p>所有 PNG 共用 {exposure:+.4f} EV（将 PT 可见表面亮度第 99 百分位映射到色调映射前的 1），再使用 ACES fitted 和 sRGB。没有单独提亮任何方案；展示曝光不影响 MSE。</p>
<h2>HDR-FLIP 热力图</h2><p>统一 Magma [0,1] 色标。暗紫黑表示误差小，红橙浅黄表示误差大；不是百分比相似度，也不区分偏亮／偏暗。mask 外及拼图留白使用深灰背景。</p><a href="errors-hdr-flip.png"><img src="errors-hdr-flip.png"></a>
<h2>收敛检查</h2><p>{extension_note}</p><img src="convergence.png"><p>右图以稳态整图 GPU 耗时×累积帧数估算预算，不含预热和截图。缓存预算不同，不能将相同帧数等同于相同总射线数。</p>
<table><tr><th>方案</th><th>32768→65536 MSE 变化</th><th>HDR-FLIP 变化</th><th>前后图像差异 MSE / 对 PT 误差</th><th>检查</th></tr>{convrows}</table>
<p>GI 阈值：以上三项绝对比例均低于 1%。PT 两条独立序列差异 MSE/4={noise:.7g}，估计参考平均中的残余噪声，占最低方案误差 {noise/min_error:.3%}；噪声 RMS/参考 RGB RMS={np.sqrt(noise/energy):.3%}。PT 合计 {TOTAL//2}→{TOTAL} spp 的图像差异 MSE={tail:.7g}，自身 HDR-FLIP={ref_flip:.5f}。参考翻倍后，各方案 MSE 和 HDR-FLIP 相对变化最大分别为 {max(abs(v['reference_doubling_mse_change']) for v in metrics.values()):.3%}、{max(abs(v['reference_doubling_flip_change']) for v in metrics.values()):.3%}。</p>
<p>PT 检查要求：噪声及翻倍差异均低于最低方案误差 1%，相对 RGB RMS 噪声低于 0.5%，各方案指标随参考翻倍变化小于 1%。检查结果：{json.dumps(checks,ensure_ascii=False)}。这些是实用稳定性检查，不证明所有像素数学上完全收敛；尤其极暗处在高曝光下仍可能存在参考噪声，不能直接从方案 HDR-FLIP 中减去参考 FLIP。</p>
<h2>Pass 组织与耗时</h2><pre>WorldCache + Half FG:
 Visibility → WorldCache [CachePaths → CacheResolve → PrimaryShading → HalfGather]
            → Reconstruct → Accumulate → Display
Original DDGI:
 Visibility → DDGI [ProbeUpdate → PrimaryShading / probe interpolation]
            → Accumulate → Display
DDGI + Half FG:
 Visibility → DDGI [ProbeUpdate → PrimaryShading → HalfGather]
            → Reconstruct → Accumulate → Display
PT Reference:
 Visibility → PT [8 spp/frame] → Accumulate → Display</pre>
<p>WorldCache 更新独立于 FG，命中点读取缓存的总漫反射出射亮度；DDGI FG 命中点计算直接光并查询探针间接光。重建和屏幕累积共用原实现。计时包含 GBuffer、缓存／探针更新、着色、重建、累积、ToneMapper，不包含截图和统计回读。RTX 5070 / D3D12，每组 {timing['ddgi']['samples']} 个稳态计时间隔均值。</p>
<table><tr><th>Graph pass / ms</th>{headers}</tr>{stage_rows}</table><br><table><tr><th>GI 内部阶段 / ms</th>{headers}</tr>{inner_rows}</table>
<p>内部阶段是上级 pass 的分项，不能再和 pass 总时间相加。表中计时包含当前缓存查询诊断计数器，未为某一方案另开关闭诊断的特殊计时版本。PT 计时固定末次随机种子，测量稳定的 8 spp/帧工作负载；参考图生成阶段则逐帧使用不同种子。</p>
<h2>原生单图与局部放大</h2><select onchange="document.getElementById('single').src=this.value">{options}</select><img id="single" src="worldcache.png"><a href="details.png"><img src="details.png"></a>
<p><a href="summary.json">完整参数、收敛检查和指标 JSON</a> · <a href="reference-check-32768.json">32768 spp 检查</a> · <a href="reference-check-65536.json">65536 spp 检查</a> · <a href="reference-check-{TOTAL}.json">最终参考检查</a>。原始 EXR 与逐阶段计时：build/sponza-worldcache-ddgi-1080p-20261119。复现脚本：tests/ddgi/sponza_worldcache_comparison.py；评分脚本：tests/ddgi/score_sponza_worldcache_comparison.py。旧报告未覆盖。</p></html>'''
(O/'report.html').write_text(page,encoding='utf-8')
print(json.dumps({'checks':checks,'reference':reference,'report':str(O/'report.html')},ensure_ascii=False),flush=True)
