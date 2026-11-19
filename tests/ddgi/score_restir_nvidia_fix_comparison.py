"""Score individual trials against independent PT; separate trial variance from residual error."""
from pathlib import Path
import sys,json,re
import numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/restir-nvidia-fix-comparison';O=R/'docs/2026-11-18_DDGI-ReSTIR-NVIDIA-fix';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
assert not (D/'failure.txt').exists()
info=json.loads((D/'complete.json').read_text());assert info['stage']=='complete'
assert all(x['stats']['rejectedRaySamples']==0 for x in info['runs'].values())
ageInfo=json.loads((R/'build/restir-nvidia-fix-age0/complete.json').read_text())
assert ageInfo['stage']=='complete' and all(x['stats']['rejectedRaySamples']==0 for x in ageInfo['runs'].values())
info['age0_capture']=ageInfo
def read(tag,ch='Accumulate.output'):
 directory=D
 if tag.startswith('age0-'):directory=R/'build/restir-nvidia-fix-age0';tag='restir-'+tag[5:]
 a=OpenEXR.File(str(directory/(tag+'.'+ch+'.0.exr'))).channels()['RGB'].pixels
 assert a.shape==(360,640,3) and np.isfinite(a).all(),tag
 return np.ascontiguousarray(a)
mask=np.linalg.norm(read('mask','Visibility.normW'),axis=-1)>.5
np.save(D/'surface-mask.npy',mask)
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
a,b=read('pt-a-131072'),read('pt-b-131072');ref=np.ascontiguousarray((a+b)*.5)
OpenEXR.File({}, {'RGB':ref}).write(str(D/'reference-262144spp.exr'))
noise=mse(a,b)/4
refhalf=(read('pt-a-65536')+read('pt-b-65536'))*.5
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
def flip(a):return flip_evaluator.evaluate(ref,np.ascontiguousarray(a),'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
baseprobe=read('fg-0-probe')
for t in range(3):
 for name in ['fg','spatial','restir','age0']:assert np.array_equal(baseprobe,read(name+'-'+str(t)+'-probe'))
result={'capture':info,'reference':{'spp':262144,'independent_sequences':2,'estimated_noise_mse':noise,'half_to_full_mse':mse(refhalf,ref)},'flip_parameters':params,'identical_probes_verified':True,'metrics':{}}
means={};colors={'fg':'#2678b5','spatial':'#239151','restir':'#d66b29','age0':'#a457b5'};labels={'fg':'Ordinary cosine FG','spatial':'Corrected spatial ReSTIR','restir':'Temporal + spatial (max age 32)','age0':'Temporal + spatial (no age limit)'}
flipNs=[1,4,16,64,256,1024,4096,16384,32768,65536,131072]
for name in labels:
 metrics={};means[name]={}
 for n in info['checkpoints']:
  images=np.stack([read(name+'-'+str(t)+'-'+str(n)) for t in range(3)])
  mean=images.mean(axis=0);means[name][n]=mean
  values=[mse(x,ref) for x in images];variance=float(np.var(images[:,mask].astype(np.float64),axis=0,ddof=1).mean())
  v={'mse_mean':float(np.mean(values)),'mse_min':min(values),'mse_max':max(values),'mse_trials':values,'intertrial_variance':variance,'mean_image_mse':mse(mean,ref),'residual_squared_error_estimate':mse(mean,ref)-variance/3-noise}
  if n in flipNs:
   fs=[float(flip(x)[mask].mean()) for x in images];v['hdr_flip_mean']=float(np.mean(fs));v['hdr_flip_trials']=fs
  v['max_components']=[float(np.max(x)) for x in images];v['numerically_unstable']=max(v['max_components'])>1e6
  assert not v['numerically_unstable'], (name,n)
  metrics[str(n)]=v
 timings=[];windows=[]
 for t in range(3):
  key=name+'-'+str(t);timingDir=R/'build/restir-nvidia-fix-age0' if name=='age0' else D;timingKey='restir-'+str(t) if name=='age0' else key;profile=json.loads((timingDir/(timingKey+'-timing.json')).read_text());events=profile['events'];prefix='/onFrameRender/RenderGraphExe::execute()'
  timings.append({'gpu_ms':events[prefix+'/gpu_time']['stats']['mean'],'frames':profile['frame_count'],'stages':{k:val['stats']['mean'] for k,val in events.items() if k.startswith(prefix+'/DDGI/') and k.endswith('/gpu_time')}})
  trial=[]
  for w in range(2):
   record={}
   if w==0:
    old=read(key+'-131072').astype(np.float64);raw=read(key+'-window0-0','Reconstruct.color').astype(np.float64)
    predicted=(old*131072+raw)/131073
    assert mse(read(key+'-window0-0'),predicted)/max(float(np.mean(predicted[mask]**2)),1e-20)<1e-10, 'Accumulation reset or invalid readback'
   for ch,label in [('Reconstruct.color','raw'),('Accumulate.output','accumulated')]:
    average=None;m2=None
    for i in range(64):
     x=read(key+'-window'+str(w)+'-'+str(i),ch)[mask].astype(np.float64)
     if average is None:average=x.copy();m2=np.zeros_like(x)
     else:
      delta=x-average;average+=delta/(i+1);m2+=delta*(x-average)
    record[label+'_rgb_temporal_variance']=float((m2/63).mean())
   trial.append(record)
  windows.append(trial)
 final=metrics['131072'];previous=metrics['65536'];earlier=metrics['32768']
 tail=mse(means[name][131072],means[name][65536]);tail0=mse(means[name][65536],means[name][32768])
 stability={'relative_mse_change_last_doubling':final['mse_mean']/previous['mse_mean']-1,'relative_mse_change_previous_doubling':previous['mse_mean']/earlier['mse_mean']-1,'mean_image_tail_mse':tail,'mean_image_previous_tail_mse':tail0,'tail_over_pt_error':tail/final['mean_image_mse'],'intertrial_variance_over_mean_error':final['intertrial_variance']/3/final['mean_image_mse']}
 stability['practically_stable']=not final['numerically_unstable'] and abs(stability['relative_mse_change_last_doubling'])<.02 and abs(stability['relative_mse_change_previous_doubling'])<.02 and stability['tail_over_pt_error']<.01 and stability['intertrial_variance_over_mean_error']<.05
 result['metrics'][name]={'checkpoints':metrics,'timings':timings,'gpu_ms_mean':float(np.mean([x['gpu_ms'] for x in timings])),'temporal_windows':windows,'stability':stability}
 print(name,'final',final,'stability',stability,flush=True)
(O/'summary.json').write_text(json.dumps(result,indent=2))
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
fig,axes=plt.subplots(1,3,figsize=(17,5.2),layout='constrained')
for ax,metric,timeaxis,title in zip(axes,['mse_mean','hdr_flip_mean','mse_mean'],[False,False,True],['MSE vs independent PT','HDR-FLIP vs independent PT','MSE at matched estimated GPU time']):
 for name in labels:
  data=result['metrics'][name];ns=flipNs if metric=='hdr_flip_mean' else [2**i for i in range(18)]
  x=np.array(ns,dtype=float)*(data['gpu_ms_mean']/1000 if timeaxis else 1)
  ys=[data['checkpoints'][str(n)][metric] for n in ns]
  ax.loglog(x,ys,'.-',color=colors[name],label=labels[name])
  if metric=='mse_mean':ax.fill_between(x,[data['checkpoints'][str(n)]['mse_min'] for n in ns],[data['checkpoints'][str(n)]['mse_max'] for n in ns],color=colors[name],alpha=.12)
 if metric=='mse_mean':
  ax.set_ylim(5e-7,1e-3)
 ax.set_title(title);ax.set_xlabel('Estimated cumulative GPU seconds' if timeaxis else 'Frames / fresh candidates per coarse pixel');ax.set_ylabel('HDR-FLIP' if metric=='hdr_flip_mean' else 'Linear HDR MSE');ax.grid(True,which='both',alpha=.2);ax.legend(fontsize=8)
fig.suptitle('640 x 360 | half gather | frozen shared probes | 3 independent seed ranges | full-resolution integration OFF')
fig.savefig(O/'convergence.png',dpi=180);fig.savefig(O/'convergence.svg');plt.close(fig)
fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout='constrained')
ns=[1024,4096,16384,32768,65536,131072]
for name in labels:
 d=result['metrics'][name]['checkpoints']
 axes[0].loglog(ns,[d[str(n)]['intertrial_variance'] for n in ns],'.-',label=labels[name],color=colors[name])
 axes[1].semilogx(ns,[d[str(n)]['residual_squared_error_estimate'] for n in ns],'.-',label=labels[name],color=colors[name])
for ax in axes:ax.grid(True,which='both',alpha=.2);ax.set_xlabel('Accumulated frames');ax.legend(fontsize=8)
axes[0].set_title('Variance across 3 independent runs');axes[0].set_ylabel('Mean RGB variance')
axes[1].set_title('Residual squared error estimate vs PT');axes[1].set_ylabel('Mean-image MSE - variance / 3 - PT noise')
fig.savefig(O/'stability.png',dpi=180);plt.close(fig)
def display(a):
 x=np.maximum(a.astype(np.float64),0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return Image.fromarray(np.uint8(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255+.5))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
def panel(images,title,file):
 out=Image.new('RGB',(1920,808),(24,26,31));draw=ImageDraw.Draw(out)
 for i,(name,img) in enumerate(images):
  x=(i%3)*640;y=(i//3)*404;draw.text((x+10,y+8),name,font=font,fill='white');out.paste(img,(x,y+44))
 out.save(O/file)
for n in [1,16,256,131072]:
 panel([('PT reference / 262144 spp',display(ref))]+[(labels[name],display(read(name+'-0-'+str(n)))) for name in labels],'', 'frames-'+str(n)+'.png')
body=(R/'Source/RenderPasses/FLIPPass/flip.hlsli').read_text().split('static const float3 MagmaMap[] = {',1)[1].split('};',1)[0]
magma=np.array([[float(c) for c in v.split(',')] for v in re.findall(r'float3\(([^)]+)\)',body)])
heat=[]
for name in labels:
 err=flip(means[name][131072]);img=Image.fromarray(np.uint8(magma[np.clip((err*255).astype(int),0,255)]*255))
 img.save(O/(name+'-flip.png'));heat.append((labels[name],img))
heat.insert(0,('PT reference / heatmaps fixed 0-1',display(ref)));panel(heat,'','heatmaps.png')
print('Artifacts ready',flush=True)

rows='';stableRows='';windowRows='';curveRows='';thresholdRows=''
for threshold in [2e-6,1.2e-6]:
 for name in labels:
  d=result['metrics'][name]
  crossing=next((n for n in info['checkpoints'] if d['checkpoints'][str(n)]['mse_mean']<=threshold),None)
  budget='未达到' if crossing is None else f"{crossing} 帧 / {crossing*d['gpu_ms_mean']/1000:.4f} s"
  thresholdRows+=f'<tr><td>{threshold:.2g}</td><td>{labels[name]}</td><td>{budget}</td></tr>'
for name in labels:
 data=result['metrics'][name];v=data['checkpoints']['131072'];st=data['stability']
 rows+=f"<tr><td>{labels[name]}</td><td>{v['mse_mean']:.6g}</td><td>{v['hdr_flip_mean']:.6f}</td><td>{v['intertrial_variance']:.4g}</td><td>{v['residual_squared_error_estimate']:.6g}</td><td>{data['gpu_ms_mean']:.4f}</td></tr>"
 stableRows+=f"<tr><td>{labels[name]}</td><td>{st['relative_mse_change_previous_doubling']:.2%}</td><td>{st['relative_mse_change_last_doubling']:.2%}</td><td>{st['tail_over_pt_error']:.2%}</td><td>{st['intertrial_variance_over_mean_error']:.2%}</td><td>{'通过' if st['practically_stable'] else '未通过，不能标为完全收敛'}</td></tr>"
 for w in range(2):
  raw=np.mean([t[w]['raw_rgb_temporal_variance'] for t in data['temporal_windows']]);accv=np.mean([t[w]['accumulated_rgb_temporal_variance'] for t in data['temporal_windows']])
  windowRows+=f"<tr><td>{labels[name]}</td><td>{w+1}</td><td>{raw:.6g}</td><td>{accv:.6g}</td></tr>"
for n in flipNs:
 vals=[result['metrics'][name]['checkpoints'][str(n)] for name in labels]
 curveRows+='<tr><td>'+str(n)+'</td>'+''.join(f"<td>{v['mse_mean']:.5g}</td><td>{v['hdr_flip_mean']:.5f}</td>" for v in vals)+'</tr>'
fgFinal=result['metrics']['fg']['checkpoints']['131072']['mse_mean']
age0Final=result['metrics']['age0']['checkpoints']['131072']['mse_mean']
age32Final=result['metrics']['restir']['checkpoints']['131072']['mse_mean']
conclusion=f'<p><strong>旧失稳序列的数值爆发已修复，但没有证据表明当前时空 ReSTIR 比普通 FG 收敛更快。</strong>131072 帧时，关闭年龄限制的时空复用平均 MSE 比普通 FG 高 {age0Final/fgFinal-1:.1%}；开启 32 帧年龄上限时高 {age32Final/fgFinal-1:.1%}。最终保留年龄限制为可选参数，默认设为 0（关闭）；ReSTIR 总开关仍默认关闭。数值稳定不等于无偏，实用收敛判定见后表。</p>'
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>修正版 ReSTIR 与普通 FG：对照独立 PT</title>
<style>body{{background:#181b20;color:#ddd;font:17px/1.7 system-ui;max-width:1600px;margin:30px auto;padding:0 24px}}img{{max-width:100%}}a{{color:#9cf}}table{{border-collapse:collapse;font-size:15px}}td,th{{padding:7px 12px;border:1px solid #555}}code{{color:#acd}}</style>
<h1>修正版 ReSTIR 与普通 FG：对照独立 PT</h1>{conclusion}
<p>本报告比较普通 cosine FG、只开启空间复用的修正版 ReSTIR、时空复用均开启的修正版 ReSTIR。参考是独立的未降噪 PT，不再使用普通 FG 自身的长序列。</p>
<p>额外加入“关闭年龄限制”的时空复用对照，用于区分本次归一化/可见性修正与样本寿命限制的影响。其余参数、随机序列与采样预算完全相同。</p><h2>实验条件</h2><p>640×360 输出、320×180 gather；Lambert Cornell、相同点光源和相机。每组先进行 8192 帧 probe 更新，再冻结，相同 probe 输出逐像素一致已验证。测量从空 reservoir、空 Accumulate 历史开始。jitter 开启；全分辨率积分关闭，使用同一 16 tap 重建；无 NRD。ReSTIR 使用来源可见性校正，空间 2 pass × 4 邻居、半径 8，时间 M 上限 20，样本年龄上限 32 帧。每有效粗像素每帧一个新候选：普通 FG 为 cosine，ReSTIR 为 uniform，因此曲线比较的是实际方案，不是只隔离复用一项。</p>
<p>三个随机序列使用互不重叠的 frame seed 范围，每组累积 131072 帧。曲线是三个独立结果的误差平均，阴影为最小值到最大值，不是置信区间。GPU 时间轴按各方案稳定阶段测得的全图 GPU 帧耗时 × 帧数估算；不含公共 probe 预热、编译、读回和落盘。包含重连可见性射线和重建等开销，probe 测量期间冻结。</p>
<p>普通 FG 回归：第一个随机序列的 1、16、256、4096、131072 帧输出，与修正前对应 EXR 逐位一致；本次修正没有改变普通 FG 输出。</p><h2>PT 参考可靠性</h2><p>8 spp/frame，31 次表面/漫反射反弹，不使用 RR、ReSTIR 或降噪。明确启用固定 seed 接口并逐帧改变 seed，两条互不重叠的随机序列各 131072 spp，平均后得到 262144 spp 参考。两序列差分估计参考噪声 MSE 为 {noise:.6g}；参考从 131072 spp 到 262144 spp 的图像变化 MSE 为 {result['reference']['half_to_full_mse']:.6g}。这是有限反弹、有限采样参考，不是解析真值。</p>
<p>MSE 在 GBuffer 可见场景像素上对线性 HDR RGB 求平均；HDR-FLIP 使用全组一致的自动选取曝光范围、ACES、67 PPD，随后在同一场景 mask 内平均。背景不计入指标。显示图统一 +3 EV，不影响线性指标。</p>
<h2>修正与失稳回归</h2><p>参考：<a href="https://github.com/NVIDIA-RTX/RTXDI-Library/blob/main/Include/Rtxdi/GI/TemporalResampling.hlsli">NVIDIA TemporalResampling</a>、<a href="https://github.com/NVIDIA-RTX/RTXDI-Library/blob/main/Include/Rtxdi/GI/SpatialResampling.hlsli">SpatialResampling</a>。保留本项目的亮度 target、DDGI 命中点光照、Jacobian 范围拒绝与半分辨率重建，未宣称与 SDK 完全等价。</p><p>按 NVIDIA RTXDI GI 的来源归一化原则，记录最终选中来源，并在反向支持测试失败时令归一化分子为零；正向与反向可见性使用同一函数和保存的几何法线。归一化为 <code>W = weightSum × p_selectedSource / (p_current × Σ M_i p_i)</code>，不能在选中来源的支持为零时直接约掉分子。独立实现这些原则，并非直接集成 RTXDI SDK。增加非有限权重检查与独立样本年龄上限，本次比较上限为 32 帧。</p><p>先重放旧版失稳的 seed offset 262144：关闭年龄上限，运行 262144 帧；102 张原始/累积检查图全部有限，非有限值拒绝计数为零。旧版第 118272 帧原始峰值约 1.52×10¹²，修正后为 1.03。说明该回归通过，不代表证明所有场景无偏或所有随机序列稳定。详见 <a href="replay-validation.json">重放验证</a>。</p><h2>收敛曲线</h2><img src="convergence.png"><table><tr><th>累积帧</th><th>FG MSE</th><th>FG FLIP</th><th>空间 MSE</th><th>空间 FLIP</th><th>时空 MSE</th><th>时空 FLIP</th><th>无年龄限制 MSE</th><th>无年龄限制 FLIP</th></tr>{curveRows}</table>
<h2>达到相同误差的预算</h2><p>列出平均 MSE 首次达到阈值的已测检查点，不在检查点之间插值；早期偶然越过阈值不等价于长期稳定。</p><table><tr><th>MSE 阈值</th><th>方案</th><th>检查点 / 估计累计 GPU 时间</th></tr>{thresholdRows}</table><h2>131072 帧结果</h2><table><tr><th>方案</th><th>平均 MSE vs PT</th><th>平均 HDR-FLIP</th><th>独立序列间方差</th><th>系统残差平方估计</th><th>GPU ms/frame</th></tr>{rows}</table>
<p>“系统残差平方估计” = 三序列平均图对 PT 的 MSE − 序列间方差/3 − PT 参考噪声估计。它用来区分随机噪声与长期偏离 PT 的残差；只有三个序列，仍是诊断估计，不能作为严格无偏性的证明。残差包含 DDGI 本身近似、半分辨率重建和复用误差等。</p>
<img src="stability.png">
<h2>是否达到实用稳定状态</h2><p>采用预先写入评分脚本的标准：连续两次翻倍后的平均 MSE 变化均小于 2%；最后一次翻倍平均图变化 MSE 小于对 PT 误差的 1%；平均图的序列间随机误差估计小于其对 PT 误差的 5%。未通过则明确不称为完全收敛。方差稳定或累积画面不闪，不等于图像正确。</p>
<table><tr><th>方案</th><th>32k→64k MSE 变化</th><th>64k→128k MSE 变化</th><th>末次图像变化/误差</th><th>平均图随机误差/总误差</th><th>判定</th></tr>{stableRows}</table>
<h2>后期时间方差</h2><p>在 131072 帧之后，采集两个各 64 连续帧的窗口，中间再等待 4096 帧；同时保存重建后的未累积图和 Accumulate 输出。下表为每像素 RGB 时间方差的场景平均，再对三个随机序列取平均。时间复用会造成相关性，短窗口可能低估长期变化，所以不单凭该表判断收敛。</p><table><tr><th>方案</th><th>窗口</th><th>未累积图时间方差</th><th>累积图时间方差</th></tr>{windowRows}</table>
<h2>画面对比</h2><p>以下为第一个随机序列，保留单次运行的实际噪声；不是三次运行图像的平均。</p><h3>1 帧</h3><img src="frames-1.png"><h3>16 帧</h3><img src="frames-16.png"><h3>256 帧</h3><img src="frames-256.png"><h3>131072 帧</h3><img src="frames-131072.png">
<h2>长期误差位置</h2><p>三序列平均图相对 PT 的 HDR-FLIP；Magma 色标固定 0–1，暗紫误差小、黄白误差大。不同方案没有分别拉伸色标。</p><img src="heatmaps.png">
<p>脚本：tests/ddgi/restir_nvidia_fix_comparison.py、score_restir_nvidia_fix_comparison.py。原始 EXR、场景参数、运行记录、源码哈希和 profiler 输出位于 build/restir-nvidia-fix-comparison；PT 参考复用自 build/restir-pt-convergence（材质、灯光与 PT 实现未改）；机器可读结果见 <a href="summary.json">summary.json</a>。本次未改变渲染器默认设置，ReSTIR 仍默认关闭。</p></html>'''
(O/'report.html').write_text(html,encoding='utf-8')
