from pathlib import Path
import sys,json,numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/restir-pt-convergence';T=R/'build/restir-pt-long-tail';O=R/'docs/2026-11-18_DDGI-ReSTIR-vs-PT'
sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
assert not (T/'failure.txt').exists()
info=json.loads((T/'complete.json').read_text());assert info['stage']=='complete'
main=json.loads((O/'summary.json').read_text());params=main['flip_parameters'];mask=np.load(D/'surface-mask.npy')
ref=OpenEXR.File(str(D/'reference-262144spp.exr')).channels()['RGB'].pixels
read=lambda tag,ch='Accumulate.output':OpenEXR.File(str(T/(tag+'.'+ch+'.0.exr'))).channels()['RGB'].pixels
labels={'fg':'Ordinary FG','spatial':'Spatial ReSTIR','restir':'Temporal + spatial ReSTIR'}
summary={'capture':info,'metrics':{}}
rows='';tailrows='';varianceRows=''
for name in labels:
 run=info['runs'][name];n=run['frames'];x=read(name+'-'+str(n))
 err=flip_evaluator.evaluate(ref,x,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 values={'frames':n,'mse':float(np.mean((x[mask].astype(float)-ref[mask])**2)),'hdr_flip':float(err[mask].mean()),'practically_stable':run['practically_stable'],'windows':[]}
 for w in range(2):
  window={}
  for ch,label in [('Reconstruct.color','raw'),('Accumulate.output','accumulated')]:
   avg=None;m2=None
   for i in range(64):
    a=read(name+'-window'+str(w)+'-'+str(i),ch)[mask].astype(float)
    if avg is None:avg=a.copy();m2=np.zeros_like(a)
    else:
     delta=a-avg;avg+=delta/(i+1);m2+=delta*(a-avg)
   window[label+'_temporal_variance']=float((m2/63).mean())
  values['windows'].append(window)
  varianceRows+=f"<tr><td>{labels[name]}</td><td>{w+1}</td><td>{window['raw_temporal_variance']:.6g}</td><td>{window['accumulated_temporal_variance']:.6g}</td></tr>"
 summary['metrics'][name]=values
 rows+=f"<tr><td>{labels[name]}</td><td>{n}</td><td>{values['mse']:.6g}</td><td>{values['hdr_flip']:.6f}</td><td>{'通过' if run['practically_stable'] else '未通过'}</td></tr>"
 for ns,v in run['checkpoints'].items():
  tailrows+=f"<tr><td>{labels[name]}</td><td>{ns}</td><td>{v['mse']:.6g}</td><td>{v.get('relative_mse_change',float('nan')):.2%}</td><td>{v.get('tail_over_error',float('nan')):.2%}</td></tr>"
(O/'long-tail-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary['metrics'],indent=2),flush=True)
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,ax=plt.subplots(figsize=(11,5),layout='constrained')
colors={'fg':'#2678b5','spatial':'#239151','restir':'#d66b29'}
for name in labels:
 d=main['metrics'][name]['checkpoints'];ns=[2**i for i in range(18)]
 ax.loglog(ns,[d[str(n)]['mse_mean'] for n in ns],'-',color=colors[name],label=labels[name]+' / mean of 3 runs')
 d=info['runs'][name]['checkpoints'];ns=sorted(map(int,d))
 ax.loglog(ns,[d[str(n)]['mse'] for n in ns],'o--',color=colors[name],markersize=4,label=labels[name]+' / compensated, run 0')
ax.set_title('Independent PT reference | long-tail check uses compensated accumulation');ax.set_xlabel('Accumulated frames');ax.set_ylabel('Linear HDR MSE');ax.grid(True,which='both',alpha=.2);ax.legend(fontsize=8)
fig.savefig(O/'convergence-long-tail.png',dpi=180);plt.close(fig)
def display(a):
 x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return Image.fromarray(np.uint8(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255+.5))
images=[('PT / 262144 spp',ref)]+[(labels[name]+' / '+str(info['runs'][name]['frames'])+' frames',read(name+'-'+str(info['runs'][name]['frames']))) for name in labels]
panel=Image.new('RGB',(1280,808),(24,26,31));draw=ImageDraw.Draw(panel);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',21)
for i,(label,a) in enumerate(images):
 x=(i%2)*640;y=(i//2)*404;draw.text((x+8,y+8),label,font=font,fill='white');panel.paste(display(a),(x,y+44))
panel.save(O/'long-tail-comparison.png')
fg=summary['metrics']['fg'];re=summary['metrics']['restir'];sp=summary['metrics']['spatial']
section=f'''<h2>补偿求和长尾验证</h2><p>为避免百万帧普通单精度求和的舍入误差，这组统一使用 AccumulatePass 的 SingleCompensated。普通 FG 和空间复用补跑到 131072 帧；完整时空复用继续翻倍，最多 2097152 帧，直到连续两次 MSE 变化小于 2%、图像变化 MSE 小于对 PT 误差的 1%。这是第一组随机序列的延长验证，不是三序列平均，也不构成数学上的完全收敛证明。</p>
<table><tr><th>方案</th><th>累积帧</th><th>MSE vs PT</th><th>HDR-FLIP</th><th>长尾稳定标准</th></tr>{rows}</table>
<p>最后记录点：完整时空复用相对普通 FG 的 MSE 变化为 {re['mse']/fg['mse']-1:.2%}，HDR-FLIP 变化为 {re['hdr_flip']/fg['hdr_flip']-1:.2%}；空间复用的 MSE 变化为 {sp['mse']/fg['mse']-1:.2%}。只有通过稳定标准的结果才可作为本实验条件下的近稳态误差比较；仍包含有限采样和参考误差。</p>
<img src="convergence-long-tail.png"><table><tr><th>方案</th><th>帧数</th><th>MSE</th><th>翻倍相对变化</th><th>图像变化/误差</th></tr>{tailrows}</table>
<p>同采样序列下，131072 帧 Single 与 SingleCompensated 的图像差异已记录在 long-tail-summary.json，可检查数值精度对结论的影响。长尾后的两个时间窗口如下，仍不能用很小的累积时间方差代替正确性判断：</p><table><tr><th>方案</th><th>窗口</th><th>原始帧时间方差</th><th>累积图时间方差</th></tr>{varianceRows}</table><img src="long-tail-comparison.png">'''
path=O/'report.html';html=path.read_text(encoding='utf-8');html=html.replace('<h2>131072 帧结果</h2>',section+'<h2>131072 帧结果</h2>');path.write_text(html,encoding='utf-8')
