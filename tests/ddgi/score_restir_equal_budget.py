"""Cold-start convergence: mean error across trials, never averaged trial images."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
D=R/'build/restir-equal-budget';B=R/'build/highres-1080p-split-rerun';O=R/'docs/2026-11-18_DDGI-ReSTIR-equal-budget';O.mkdir(exist_ok=True)
assert not (D/'failure.txt').exists()
info=json.loads((D/'complete.json').read_text());assert info['stage']=='complete'
def load(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels;assert np.isfinite(a).all(),p;return np.ascontiguousarray(a)
def read(tag,ch='Accumulate.output'):return load(D/(tag+'.'+ch+'.0.exr'))
ref=load(B/'reference-65536spp.exr');mask=np.load(B/'surface-mask.npy')
params=json.loads((R/'docs/2026-11-18_DDGI-1080p/summary.json').read_text())['flip_parameters']
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
checkpoints=info['checkpoints'];flip_points=[1,4,16,64,256,1024,4096]
phases=[[(i&7)>>2,i&1] for i in range(8)]
counts=[int(mask[y::2,x::2].sum()) for x,y in phases]
budgets={str(n):sum(counts[i%8] for i in range(n)) for n in checkpoints}
validation={}
a=read('fg-probe-8192');b=read('restir-probe-8192')
validation['probe_pair_max_abs']=float(np.max(abs(a-b)));assert validation['probe_pair_max_abs']==0
validation['probe_4096_to_8192_relative_rms']=float(np.sqrt(mse(read('fg-probe-4096'),a)/np.mean(a[mask].astype(np.float64)**2)))
assert validation['probe_4096_to_8192_relative_rms']<.005
for trial in range(3):
 d=read('restir-'+str(trial)+'-1','DDGI.restirDebug');valid=d[:,:,0]>0
 expected=np.zeros_like(mask);expected[0::2,0::2]=mask[0::2,0::2]
 assert np.array_equal(valid,expected)
 assert np.all(d[:,:,0][valid]==1), 'Warm history leaked into cold-start frame'
 assert np.all(d[:,:,2][valid]==1), 'Unexpected fallback rays'
 validation['trial_'+str(trial)]={'first_temporal_M':1,'new_surface_rays_first_frame':int(valid.sum())}
 for n in checkpoints:
  d=read('restir-'+str(trial)+'-'+str(n),'DDGI.restirDebug');valid=d[:,:,0]>0
  assert np.all(d[:,:,2][valid]==1), 'Integration fallback violates matched ray budget'
result={'capture':info,'validation':validation,'surface_ray_counts_by_phase':counts,'new_fg_ray_budgets':budgets,
 'flip_parameters':params,'metrics':{},'notes':'Shadow/visibility rays are extra cost, excluded from the matched fresh-FG-sample budget. No averaging of images across trials.'}
for name in ['fg','restir']:
 trials=[]
 for trial in range(3):
  metrics={}
  for n in checkpoints:
   a=read(name+'-'+str(trial)+'-'+str(n));v={'mse':mse(a,ref)}
   if n in flip_points:v['hdr_flip']=float(flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0][mask].mean())
   metrics[str(n)]=v
  timing=json.loads((D/(name+'-'+str(trial)+'-timing.json')).read_text())['events'];prefix='/onFrameRender/RenderGraphExe::execute()'
  trials.append({'checkpoints':metrics,'gpu_ms':timing[prefix+'/gpu_time']['stats']['mean']})
  print(name,trial,'done',flush=True)
 aggregate={}
 for n in checkpoints:
  v={}
  for metric in ['mse','hdr_flip']:
   values=[t['checkpoints'][str(n)][metric] for t in trials if metric in t['checkpoints'][str(n)]]
   if values:v[metric]={'mean':float(np.mean(values)),'min':float(np.min(values)),'max':float(np.max(values)),'runs':values}
  aggregate[str(n)]=v
 result['metrics'][name]={'trials':trials,'aggregate':aggregate,'gpu_ms_mean':float(np.mean([t['gpu_ms'] for t in trials]))}
result['mse_ratio_restir_over_fg']={str(n):result['metrics']['restir']['aggregate'][str(n)]['mse']['mean']/result['metrics']['fg']['aggregate'][str(n)]['mse']['mean'] for n in checkpoints}
(O/'summary.json').write_text(json.dumps(result,indent=2));print('Metrics complete',flush=True)
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11})
fig,axes=plt.subplots(1,2,figsize=(14,5.6),layout='constrained')
colors={'fg':'#2378b5','restir':'#dc752a'};labels={'fg':'Original half FG','restir':'ReSTIR + original reconstruction'}
for ax,metric,title in zip(axes,['mse','hdr_flip'],['Linear HDR MSE vs undenoised PT','HDR-FLIP vs undenoised PT']):
 ns=checkpoints if metric=='mse' else flip_points
 x=np.array([budgets[str(n)]/1e6 for n in ns])
 for name in labels:
  values=[result['metrics'][name]['aggregate'][str(n)][metric] for n in ns]
  y=np.array([v['mean'] for v in values]);lo=[v['min'] for v in values];hi=[v['max'] for v in values]
  ax.plot(x,y,'o-',color=colors[name],label=labels[name],markersize=4)
  ax.fill_between(x,lo,hi,color=colors[name],alpha=.18)
 ax.set_xscale('log');ax.set_yscale('log');ax.set_xlabel('New FG rays over entire image (millions)');ax.set_ylabel(metric.upper() if metric=='mse' else 'HDR-FLIP')
 ax.set_title(title);ax.grid(True,which='both',alpha=.22);ax.legend(fontsize=9)
 top=ax.secondary_xaxis('top')
 frame_ticks=[1,4,16,64,256,1024,4096]
 top.set_xticks([budgets[str(n)]/1e6 for n in frame_ticks]);top.set_xticklabels([str(n) for n in frame_ticks])
 top.set_xlabel('Measured frames since both histories were empty')
fig.suptitle('1080p cold start | frozen identical probes | full-resolution integration OFF' + chr(10) + 'Lines: mean error of 3 trials; bands: trial min-max (not confidence intervals)',fontsize=12)
fig.savefig(O/'convergence.png',dpi=180);fig.savefig(O/'convergence.svg');plt.close(fig)
def display(a):
 x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return Image.fromarray(np.uint8(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255+.5))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
for n in [1,4,16,64,256]:
 panel=Image.new('RGB',(3840,1130),(23,26,31));draw=ImageDraw.Draw(panel)
 for i,name in enumerate(labels):draw.text((i*1920+12,9),labels[name]+' / '+str(n)+' cold-start frames',font=font,fill='white');panel.paste(display(read(name+'-0-'+str(n))),(i*1920,50))
 panel.save(O/('frames-'+str(n)+'.png'))
rows=''
for n in flip_points:
 f=result['metrics']['fg']['aggregate'][str(n)];r=result['metrics']['restir']['aggregate'][str(n)]
 rows+=f"<tr><td>{n}</td><td>{budgets[str(n)]/1e6:.3f}</td><td>{f['mse']['mean']:.6g}</td><td>{r['mse']['mean']:.6g}</td><td>{result['mse_ratio_restir_over_fg'][str(n)]:.3f}</td><td>{f['hdr_flip']['mean']:.5f}</td><td>{r['hdr_flip']['mean']:.5f}</td></tr>"
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>ReSTIR 相同采样预算冷启动收敛</title>
<style>body{{background:#171a1f;color:#ddd;font:17px/1.7 system-ui;max-width:1600px;margin:32px auto;padding:0 20px}}img{{width:100%}}a{{color:#8bd}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:7px}}</style>
<h1>原 FG 与 ReSTIR：相同采样预算的冷启动收敛</h1>
<p>本次只比较半分辨率着色＋原来的 16 邻域重建，<strong>全分辨率积分关闭</strong>，NRD 关闭。统计三个独立随机帧号区间的误差均值；没有把三次图像平均成一张图以增加采样预算。阴影带是三次结果的最小值至最大值，不是统计置信区间。</p>
<p><strong>结果：</strong>在相同的新 FG 样本预算下，这版 ReSTIR 确有很低预算的收益：1–8 帧的 MSE 低约 3–13%，但到 16 帧 MSE 已高约 13%，64 帧约为原 FG 的 2.91 倍。HDR-FLIP 的收益维持到已测的 16 帧（低约 11%），64 帧则更差。因此不能仅凭最终收敛结果否认短时收益，但本次也没有证明它能持续加快收敛；结论仅针对当前 Falcor 适配实现和该场景。</p>
<h2>收敛曲线</h2><a href="convergence.png"><img src="convergence.png"></a><p><a href="convergence.svg">矢量图 SVG</a> · <a href="summary.json">完整指标、验证记录与每次结果</a></p>
<table><tr><th>测量帧</th><th>新增 FG 射线 / 百万</th><th>原 FG MSE</th><th>ReSTIR MSE</th><th>MSE 比值 ReSTIR/FG</th><th>原 FG HDR-FLIP</th><th>ReSTIR HDR-FLIP</th></tr>{rows}</table>
<h2>公平性条件</h2><p>同一 1920×1080 Lambert Cornell、相机和灯光。预热期间关闭 FG、ReSTIR 和 Accumulate，只更新 probe 8192 帧；随后冻结 probe。4096→8192 帧的直接 probe 输出相对 RMS 变化为 {validation['probe_4096_to_8192_relative_rms']:.3%}，两方案冻结时的输出逐像素完全相同。探针是带有限滞后的随机估计，稳定不等于严格无噪声；冻结确保整个比较使用同一个固定 GI 场。</p>
<p>测量第一帧之前开启 FG、按方案开启 ReSTIR，并重置 Accumulate；reservoir 第一次分配时历史无效。首帧所有有效采样位置的时间 M=1，确认没有继承预热样本。空间阶段可以复用本帧邻居样本，这些已计入整幅图的射线预算。测量期间 probe 更新次数始终为 8192，reservoir 只初始化一次。</p>
<p>每帧每个有效半分辨率表面位置发射一条新 FG 路径。按实际表面 mask 和八帧相位计数，而非把所有 960×540 位置（包括背景）都算作射线；首帧 {counts[0]:,} 条。两方案位置及预算相同。已检查 ReSTIR 各 checkpoint 的自身 reservoir 着色均接受一个有效样本，没有额外 fallback FG 路径。Lambert 场景无镜面 FG。额外的复用可见性／直接照明阴影射线不计作新 FG 候选，但计入 GPU 成本，因此这是相同采样预算，不是相同总 TraceRay 次数或相同耗时。</p>
<p>三次测量的随机帧号分别从 8192、12288、16384 开始，各测 4096 帧；跳过区间中关闭 FG 和 probe 更新，不产生可用的采样历史。原 FG 仍使用 Lambert 余弦半球采样，当前 ReSTIR 使用均匀半球初始采样；这是现有两条完整路径的比较，并非只改变重采样模块的严格消融实验。ReSTIR 为时间 M 上限 20、空间两轮×4 邻居、半径 8 粗像素。</p>
<h2>参考与成本</h2><p>MSE 在可见表面 mask 内对线性 HDR RGB 计算；HDR-FLIP 固定使用之前的 PPD/曝光参数。参考为同场景未降噪 PT 65536 spp。误差包括有限样本方差以及 DDGI、复用和重建近似；不能把低误差平台自动解释为已经收敛到正确积分。</p>
<p>冻结 probe 后的整图 GPU 帧耗时（三次均值，不含预热、编译、截图）：原 FG {result['metrics']['fg']['gpu_ms_mean']:.3f} ms，ReSTIR {result['metrics']['restir']['gpu_ms_mean']:.3f} ms。这里 probe 不再更新，因此不能直接和先前开启 probe 更新的耗时比较。</p>
<h2>相同预算画面（固定展示第 1 次试验）</h2><p>统一 +3EV/ACES/sRGB 显示。<a href="frames-1.png">1 帧</a> · <a href="frames-4.png">4 帧</a> · <a href="frames-16.png">16 帧</a> · <a href="frames-64.png">64 帧</a> · <a href="frames-256.png">256 帧</a></p><a href="frames-4.png"><img src="frames-4.png"></a><a href="frames-64.png"><img src="frames-64.png"></a></html>'''
(O/'report.html').write_text(html,encoding='utf-8')
paths=['tests/ddgi/restir_equal_budget.py','tests/ddgi/score_restir_equal_budget.py','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','Source/RenderPasses/RTXGIDDGI/ReSTIRGather.slang']
(O/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((R/p).read_bytes()).hexdigest() for p in paths},indent=2))
print(json.dumps(result['mse_ratio_restir_over_fg'],indent=2))
