"""Temporal history audit against a shared independent PT reference."""
from pathlib import Path
import json,sys,re
import numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/restir-temporal-verified';O=R/'docs/2026-11-19_DDGI-ReSTIR-temporal-audit';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
info=json.loads((D/'complete.json').read_text());assert info['stage']=='complete' and not (D/'failure.txt').exists()
assert all(v['stats']['rejectedRaySamples']==0 for v in info['runs'].values())
base=R/'build/restir-nvidia-fix-comparison'
folders={'fg':base,'spatial':base,'legacy':R/'build/restir-nvidia-fix-age0','fixed':D}
labels={'fg':'Ordinary cosine FG','spatial':'Spatial only','legacy':'Temporal + spatial: old history','fixed':'Temporal + spatial: cell history'}
colors={'fg':'#2678b5','spatial':'#239151','legacy':'#d66b29','fixed':'#9b4bb2'}
def imagefile(path):
 a=OpenEXR.File(str(path)).channels()['RGB'].pixels
 assert np.isfinite(a).all(),path
 return a

def read(name,t,tag,ch='Accumulate.output'):
 prefix='restir' if name in ['legacy','fixed'] else name
 return imagefile(folders[name]/f'{prefix}-{t}-{tag}.{ch}.0.exr')
mask=np.linalg.norm(imagefile(base/'mask.Visibility.normW.0.exr'),axis=-1)>.5
ref=(imagefile(base/'pt-a-131072.Accumulate.output.0.exr')+imagefile(base/'pt-b-131072.Accumulate.output.0.exr'))*.5
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
_,_,flipparams=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
probe=read('fg',0,'probe')
for name in labels:
 for t in range(3):assert np.array_equal(probe,read(name,t,'probe'))
result={'capture':info,'reference_spp':262144,'identical_probes':True,'flip_parameters':flipparams,'metrics':{},'ablation':{}}
for folder in ['restir-temporal-audit','restir-temporal-cell-audit']:
 d=R/'build'/folder;j=json.loads((d/'complete.json').read_text());assert j['stage']=='complete'
 for key,run in j['runs'].items():
  a=imagefile(d/f'{key}-32768.Accumulate.output.0.exr');assert run['stats']['rejectedRaySamples']==0
  result['ablation'][key]={'mse':mse(a,ref),'stats':run['stats']}
means={}
for name in labels:
 m={};means[name]={}
 for n in info['checkpoints']:
  stack=np.stack([read(name,t,n) for t in range(3)]);mean=stack.mean(axis=0);means[name][n]=mean
  vals=[mse(a,ref) for a in stack];var=float(np.var(stack[:,mask].astype(np.float64),axis=0,ddof=1).mean())
  m[str(n)]={'mse':float(np.mean(vals)),'mse_trials':vals,'min':min(vals),'max':max(vals),'intertrial_variance':var,'mean_image_mse':mse(mean,ref)}
 final=m['131072'];flips=[];times=[]
 for t in range(3):
  flips.append(float(flip_evaluator.evaluate(ref,np.ascontiguousarray(read(name,t,131072)),'HDR',applyMagma=False,parameters=flipparams.copy())[0][:,:,0][mask].mean()))
  prefix='restir' if name in ['legacy','fixed'] else name
  prof=json.loads((folders[name]/f'{prefix}-{t}-timing.json').read_text());times.append(prof['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['mean'])
 changes=[m['65536']['mse']/m['32768']['mse']-1,final['mse']/m['65536']['mse']-1]
 tail=mse(means[name][131072],means[name][65536])/final['mean_image_mse'];random=final['intertrial_variance']/3/final['mean_image_mse']
 windows=[]
 for w in range(2):
  vals=[]
  for t in range(3):
   avg=None;mom=None
   for i in range(64):
    a=read(name,t,f'window{w}-{i}','Reconstruct.color')[mask].astype(np.float64)
    if avg is None:avg=a.copy();mom=np.zeros_like(a)
    else:delta=a-avg;avg+=delta/(i+1);mom+=delta*(a-avg)
   vals.append(float((mom/63).mean()))
  windows.append(float(np.mean(vals)))
 result['metrics'][name]={'checkpoints':m,'hdr_flip':float(np.mean(flips)),'gpu_ms':float(np.mean(times)),'gpu_trials':times,'mse_changes':changes,'tail_ratio':tail,'random_ratio':random,'stable':max(map(abs,changes))<.02 and tail<.01 and random<.05,'raw_temporal_variance':windows}
 print(name,final['mse'],result['metrics'][name]['hdr_flip'],result['metrics'][name]['gpu_ms'],result['metrics'][name]['stable'],flush=True)
(O/'summary.json').write_text(json.dumps(result,indent=2))
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,axs=plt.subplots(1,3,figsize=(17,5),layout='constrained')
ns=[2**i for i in range(18)]
for name in labels:
 d=result['metrics'][name];ys=[d['checkpoints'][str(n)]['mse'] for n in ns]
 for ax,timeaxis in [(axs[0],False),(axs[1],True)]:
  xs=np.array(ns)*(d['gpu_ms']/1000 if timeaxis else 1)
  ax.loglog(xs,ys,'.-',label=labels[name],color=colors[name]);ax.fill_between(xs,[d['checkpoints'][str(n)]['min'] for n in ns],[d['checkpoints'][str(n)]['max'] for n in ns],color=colors[name],alpha=.12)
 axs[2].loglog(ns,[d['checkpoints'][str(n)]['intertrial_variance'] for n in ns],'.-',label=labels[name],color=colors[name])
for i,ax in enumerate(axs):
 ax.grid(True,which='both',alpha=.2);ax.legend(fontsize=8);ax.set_xlabel('Estimated cumulative GPU seconds' if i==1 else 'Accumulated frames');ax.set_ylabel('RGB variance across runs' if i==2 else 'Linear HDR MSE vs PT')
 if i<2:ax.set_ylim(8e-7,1e-3)
axs[0].set_title('Equal fresh-candidate budget');axs[1].set_title('Equal estimated GPU budget');axs[2].set_title('Temporal convergence / 3 seed ranges')
fig.suptitle('640 x 360 | half gather, jitter ON | M = 20 | frozen shared probes | no NRD / no age limit')
fig.savefig(O/'convergence.png',dpi=180);fig.savefig(O/'convergence.svg');plt.close(fig)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
def display(a):
 x=np.maximum(a.astype(np.float64),0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return Image.fromarray(np.uint8(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255+.5))
for n in [16,256,131072]:
 out=Image.new('RGB',(1920,808),(24,26,31));draw=ImageDraw.Draw(out)
 for i,(label,a) in enumerate([('PT / 262144 spp',ref)]+[(labels[k],read(k,0,n)) for k in labels]):
  x=i%3*640;y=i//3*404;draw.text((x+10,y+8),label,font=font,fill='white');out.paste(display(a),(x,y+44))
 out.save(O/f'frames-{n}.png')
rows='';curve='';abl=''
for name,d in result['metrics'].items():
 rows+=f"<tr><td>{labels[name]}</td><td>{d['checkpoints']['131072']['mse']:.6g}</td><td>{d['hdr_flip']:.6f}</td><td>{d['gpu_ms']:.4f}</td><td>{d['mse_changes'][1]:.2%}</td><td>{'通过' if d['stable'] else '未通过'}</td></tr>"
for n in [16,256,4096,32768,131072]:curve+='<tr><td>'+str(n)+'</td>'+''.join(f"<td>{result['metrics'][k]['checkpoints'][str(n)]['mse']:.6g}</td>" for k in labels)+'</tr>'
for k,v in result['ablation'].items():abl+=f"<tr><td>{k}</td><td>{v['mse']:.6g}</td></tr>"
html=f"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>ReSTIR 时间历史映射审计</title><style>body{{background:#181b20;color:#ddd;font:17px/1.7 system-ui;max-width:1600px;margin:30px auto;padding:0 24px}}img{{max-width:100%}}a{{color:#9cf}}table{{border-collapse:collapse}}td,th{{padding:7px 12px;border:1px solid #555}}</style>
<h1>ReSTIR 时间历史映射审计 · 2026-11-19</h1>
<p>对照 NVIDIA 后，确认了两处流程差异：历史匹配策略，以及是否反馈空间 reservoir。隔离试验表明，本场景退化主要与半分辨率 jitter 下的历史选取有关；不能简单归因于 M 少乘一次、多除一次。</p>
<p><strong>修正后的三序列长测试通过实用稳定标准，131072 帧 MSE 为 {result['metrics']['fixed']['checkpoints']['131072']['mse']:.6g}，相对旧时间复用降低约 {1-result['metrics']['fixed']['checkpoints']['131072']['mse']/result['metrics']['legacy']['checkpoints']['131072']['mse']:.1%}。但前期收敛及相同 GPU 时间下仍落后于普通 FG，不能宣称已获得收敛提速。</strong></p><h2>修正内容</h2><p>旧版在上一帧移动采样格点附近搜索世界坐标最近的 reservoir。新版先把重投影屏幕位置映射到所属粗像素，优先使用该格；表面匹配失败才按随机起点搜索邻居。静止相机下，四相位 jitter 不再驱动粗像素之间的最近点争抢。保留原 M=20、亮度 target、Jacobian、归一化公式与可见性检查。样本年龄限制在匹配到历史后判断，不再因某历史过老而换用另一邻居（年龄上限默认仍关闭）。</p>
<p>“多个像素选中相同历史会增强相关性”是对退化机制的解释；本次未追踪完整样本谱系，未给出碰撞率统计。关闭 jitter、缩短历史和单独修改映射的隔离结果支持这一判断，但不构成严格无偏性证明。</p>
<h2>与 NVIDIA 对照</h2><ul><li>合并权重是 target × W × M × Jacobian；截断 M 后保持已归一化 W 不变。我们 M=20 包含当前新候选，历史上限因此为 19；官方 maxHistoryLength 表示历史本身的上限，数值语义不同。</li><li>选中来源分子与反向支持归一化保留上次修正；M=1 与不复用输出在五个检查点逐位一致。</li><li>NVIDIA 优先测试重投影位置，随后才搜索邻居；半分辨率的所属粗像素映射也参考了本地 Lumen 的屏幕像素除以 downsample factor 的做法。不是照搬 SDK 代码。</li><li>NVIDIA 的分离时间＋空间流程反馈空间阶段结果。我们加入可选空间反馈并测试；与映射修正叠加后，前期误差反而更高，因此默认仍反馈时间阶段结果。不能把“与 SDK 不同”直接等同于数学错误。</li><li>官方示例 target 是当前表面反射光亮度（含 BRDF 与余弦），我们仍是 Li 的亮度。正权重重要性函数的选择会影响效率；没有在本次同时更改 target。</li><li>官方会在 Jacobian 验证失败时丢弃历史，我们保留零贡献来源并做反向支持归一化。这仍是差异；本次没有把它判定为已证实的错误，也未宣称完全等同于 SDK。动态场景仍使用当前 TLAS，尚未验证上一帧几何变化。</li></ul>
<p>官方源文件：<a href="https://github.com/NVIDIA-RTX/RTXDI-Library/blob/main/Include/Rtxdi/GI/TemporalResampling.hlsli">TemporalResampling</a>、<a href="https://github.com/NVIDIA-RTX/RTXDI-Library/blob/main/Include/Rtxdi/GI/Reservoir.hlsli">Reservoir</a>、<a href="https://github.com/NVIDIA-RTX/RTXDI-Library/blob/main/Source/ReSTIRGI.cpp">GI buffer indices</a>、<a href="https://github.com/NVIDIA-RTX/RTXDI/blob/main/Samples/FullSample/Shaders/LightingPasses/RtxdiApplicationBridge/RAB_LightSampling.hlsli">sample target</a>。</p>
<h2>单序列隔离试验 · 32768 帧</h2><p>legacy：原映射；feedback：仅开启空间反馈；initial：无时间/空间复用；temporal：只开时间；static-origin：关闭 jitter；short-history：M=2；history-one：M=1；cell-only：只改所属粗像素映射；cell-feedback：映射＋空间反馈；cell-temporal：映射＋仅时间复用。static-origin 改变了采样位置及重建条件，属于诊断项，不作为完全相同条件的画质排名。</p><table><tr><th>方案</th><th>MSE vs PT</th></tr>{abl}</table>
<h2>三序列长测试</h2><p>输出 640×360、gather 320×180，Lambert Cornell。每组 probe 预热 8192 帧后冻结，逐位一致已验证；清空 reservoir 和 Accumulate 后测量。三个种子偏移 0、131072、262144，各累积 131072 帧。年龄限制、全分辨率积分、NRD 均关闭。复用之前的独立 262144 spp 未降噪 PT 参考及同条件普通 FG/空间复用/旧时间复用数据。误差只统计场景 mask 内的线性 HDR RGB；HDR-FLIP 全组使用相同曝光参数、ACES、67 PPD。表中的 GPU 耗时为冻结 probe 时整个渲染图耗时；时间轴按耗时×帧数估算。</p>
<img src="convergence.png"><table><tr><th>帧数</th><th>FG MSE</th><th>空间 MSE</th><th>旧时间 MSE</th><th>新时间 MSE</th></tr>{curve}</table>
<h2>131072 帧结果</h2><table><tr><th>方案</th><th>MSE</th><th>HDR-FLIP</th><th>GPU ms</th><th>末次翻倍 MSE 变化</th><th>实用稳定</th></tr>{rows}</table>
<p>实用稳定标准沿用上次：连续两次翻倍 MSE 变化均小于 2%，末次平均图变化小于对 PT 误差的 1%，平均图随机误差估计小于总误差的 5%。它不是无偏性证明。曲线阴影为三组结果的最小到最大值。原始两组 64 帧时间方差窗口与序列间方差见 summary.json。</p>
<h2>画面对比</h2><p>展示单序列，统一 +3 EV、ACES，未降噪。</p><h3>16 帧</h3><img src="frames-16.png"><h3>256 帧</h3><img src="frames-256.png"><h3>131072 帧</h3><img src="frames-131072.png">
<p>数据：build/restir-temporal-audit、restir-temporal-cell-audit、restir-temporal-verified。脚本：tests/ddgi/restir_temporal_audit.py、restir_temporal_cell_audit.py、restir_temporal_verified.py、score_restir_temporal_audit.py。<a href="summary.json">机器可读结果</a>。ReSTIR 总开关保持默认关闭。</p></html>"""
(O/'report.html').write_text(html,encoding='utf-8')
