"""Retain failed seeds and verify the failure exists before Accumulate."""
from pathlib import Path
import sys,json,numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/restir-pt-failure-replay';B=R/'build/restir-pt-convergence';O=R/'docs/2026-11-18_DDGI-ReSTIR-vs-PT'
sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR
from PIL import Image,ImageDraw,ImageFont
assert not (D/'failure.txt').exists()
info=json.loads((D/'complete.json').read_text());assert info['stage']=='complete'
# The original requested precision used a no-op base setter; actual accumulation
# remained Single. This test proves pre-accumulation failure independently of it.
info['requested_precision']=info['precision'];info['actual_precision']='Single';info['precision']='Single'
(D/'complete.json').write_text(json.dumps(info,indent=2))
mask=np.load(B/'surface-mask.npy');ref=OpenEXR.File(str(B/'reference-262144spp.exr')).channels()['RGB'].pixels
read=lambda n,ch:OpenEXR.File(str(D/('frame-'+str(n)+'.'+ch+'.0.exr'))).channels()['RGB'].pixels
records=[]
for n in [114688]+[x['frame'] for x in info['captures']]:
 raw=read(n,'Reconstruct.color');acc=read(n,'Accumulate.output')
 records.append({'frame':n,'raw_max':float(np.max(raw)),'accumulated_max':float(np.max(acc)),'accumulated_mse':float(np.mean((acc[mask].astype(float)-ref[mask])**2)),'raw_pixels_gt_1e6':int(np.sum(np.max(raw,axis=-1)>1e6))})
failed=[r for r in records if r['raw_max']>1e6];assert failed,'Did not reproduce pre-accumulation failure'
first=failed[0];previous=records[max(0,records.index(first)-1)]
summary={'capture':info,'records':records,'first_captured_raw_failure':first,'previous_capture':previous,'conclusion':'Reproduced in Reconstruct.color before Accumulate. Not caused solely by accumulation or EXR display.'}
(O/'failure-replay.json').write_text(json.dumps(summary,indent=2));print(json.dumps({'first':first,'previous':previous},indent=2),flush=True)
main=json.loads((O/'summary.json').read_text())
for name,d in main['metrics'].items():
 for n,v in d['checkpoints'].items():
  if v['numerically_unstable']:v['residual_squared_error_estimate']=None
main['failure_replay']=summary
main['conclusion']='FG and spatial reuse reached practical stability. Temporal+spatial reuse failed in 1 of 3 sequences; stable bias cannot be claimed.'
(O/'summary.json').write_text(json.dumps(main,indent=2,allow_nan=False))
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout='constrained')
colors={'fg':'#2678b5','spatial':'#239151','restir':'#d66b29'}
for name in colors:
 d=main['metrics'][name]['checkpoints'];ns=[1024,4096,16384,32768,65536,131072]
 axes[0].loglog(ns,[d[str(n)]['intertrial_variance'] for n in ns],'.-',label=name,color=colors[name])
 axes[1].semilogx(ns,[d[str(n)]['residual_squared_error_estimate'] if d[str(n)]['residual_squared_error_estimate'] is not None else np.nan for n in ns],'.-',label=name,color=colors[name])
axes[0].set_ylim(1e-10,1e-4);axes[0].set_title('Across-run variance (divergence exceeds axis)');axes[0].set_ylabel('Mean RGB variance')
axes[1].set_title('Residual estimate (undefined after divergence)');axes[1].set_ylabel('MSE - estimated random error')
for ax in axes:ax.grid(True,which='both',alpha=.2);ax.set_xlabel('Accumulated frames');ax.legend()
fig.savefig(O/'stability.png',dpi=180);plt.close(fig)
fig,ax=plt.subplots(figsize=(10,4.5),layout='constrained')
ax.semilogy([r['frame'] for r in records],[max(r['raw_max'],1e-10) for r in records],'.-',label='Before Accumulate: Reconstruct.color')
ax.semilogy([r['frame'] for r in records],[max(r['accumulated_max'],1e-10) for r in records],'.-',label='Accumulate.output')
ax.set_xlabel('Measured frames / failing seed range');ax.set_ylabel('Maximum linear RGB component');ax.grid(True,alpha=.2);ax.legend();ax.set_title('Deterministic replay: failure already exists before accumulation')
fig.savefig(O/'failure-replay.png',dpi=180);plt.close(fig)
def display(a):
 x=np.maximum(a.astype(float),0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return Image.fromarray(np.uint8(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255+.5))
panel=Image.new('RGB',(1280,808),(24,26,31));draw=ImageDraw.Draw(panel);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
for i,(n,ch,label) in enumerate([(previous['frame'],'Reconstruct.color','Raw before captured failure'),(first['frame'],'Reconstruct.color','Raw at captured failure'),(previous['frame'],'Accumulate.output','Accumulated before'),(first['frame'],'Accumulate.output','Accumulated at failure')]):
 x=(i%2)*640;y=(i//2)*404;draw.text((x+8,y+8),label+' / '+str(n),font=font,fill='white');panel.paste(display(read(n,ch)),(x,y+44))
panel.save(O/'failure-images.png')
section=f'''<h2>失稳复现：累积前已经异常</h2><p>按第 3 组相同随机序列重新运行，保持 probe 冻结，并同时保存 Reconstruct.color 与 Accumulate.output。每 256 帧采样一次：第 {first['frame']} 帧首次捕获到累积前亮度超过 1e6，原始图最大线性 RGB 达 {first['raw_max']:.6g}，影响 {first['raw_pixels_gt_1e6']} 个像素；此前第 {previous['frame']} 帧的原始最大值为 {previous['raw_max']:.6g}。准确首次失稳帧仍在这两个检查点之间。</p>
<p>这证明问题已存在于进入 Accumulate 之前，不能归因于最终显示或单纯的时间累加误差。当前更应排查 reservoir 权重、支持域校正和历史递推；本实验没有修改渲染器，也没有用亮度裁剪隐藏失败。完整时空复用不能报告为“完全收敛后的正常偏差”。异常发生后，跨序列残差平方估计不再具有可解释性，已标记为不适用。</p>
<img src="failure-replay.png"><img src="failure-images.png">
<p>原计划延长正常序列的长尾测试，在发现另一独立序列失稳后停止，避免只展示成功序列。中途提出的补偿精度设置经源码复核未通过基类 set_properties 生效，相关中断记录已注明，未用它作为精度验证结论；复现测试实际仍为 Single，其累积前输出足以独立定位失稳所在阶段。独立复现与原数据均保留。</p>'''
p=O/'report.html';html=p.read_text(encoding='utf-8').replace('<h2>131072 帧结果</h2>',section+'<h2>131072 帧结果</h2>')
html=html.replace('2.0363e+47','不适用（数值失稳）')
lead='<p><strong>结论：</strong>当前完整时空 ReSTIR 没有显示 MSE 收敛加速，并在长时运行中出现可复现的数值失稳。仅空间复用已达到本实验稳定标准，MSE 约降低 3.0%、HDR-FLIP 约降低 1.8%，代价为约 1.81 倍 GPU 时间；低采样时感知误差有改善，但 MSE 下降没有更快。默认 ReSTIR 保持关闭。</p>'
html=html.replace('<h2>实验条件</h2>',lead+'<h2>实验条件</h2>');p.write_text(html,encoding='utf-8')
