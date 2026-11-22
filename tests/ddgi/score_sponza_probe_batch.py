"""Score batch-update captures against the existing converged, undenoised PT."""
from pathlib import Path
import sys,json,hashlib
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-probe-batch-20261120';O=R/'docs/2026-11-20_Sponza探针分批更新对比';O.mkdir(exist_ok=True)
sys.path[:0]=[str(R/'build/final-gather-python'),str(R/'build/convergence-python')]
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
def exr(path):
 a=OpenEXR.File(str(path)).channels()['RGB'].pixels
 assert np.isfinite(a).all();return np.ascontiguousarray(a,dtype=np.float32)
def read(tag):return exr(D/(tag+'.Accumulate.output.0.exr'))
refpath=R/'build/sponza-worldcache-ddgi-official-probes-20261119/reference-131072spp.exr';ref=exr(refpath)
mask=np.linalg.norm(exr(D/'full-1.Visibility.normW.0.exr'),axis=-1)>.5
assert ref.shape==(1080,1920,3)
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
base=read('full-stable1024');metrics={};curves={};times={};imgs={'pt':ref};errors={}
for name in ['full','batch1024']:
 t=json.loads((D/(name+'-timing.json')).read_text());prefix='/onFrameRender/RenderGraphExe::execute()'
 times[name]={k[len(prefix)+1:-9]:v['stats']['mean'] for k,v in t['events'].items() if k.startswith(prefix+'/') and k.endswith('/gpu_time')}
 times[name]['graph_ms']=t['events'][prefix+'/gpu_time']['stats']['mean']
 a=read(name+'-stable1024');prev=read(name+'-stable512');err=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 metrics[name]={'mse':mse(a,ref),'hdr_flip':float(err[mask].mean()),'mse_to_full':mse(a,base),'average_doubling_tail_mse':mse(a,prev),'average_doubling_relative_mse_change':mse(a,ref)/mse(prev,ref)-1}
 imgs[name]=a;errors[name]=err
 curves[name]={str(n):{'mse_to_pt':mse(read(name+'-'+str(n)),ref),'mse_to_full_settled':mse(read(name+'-'+str(n)),base)} for n in info['checkpoints']}
 print(name,metrics[name],times[name],flush=True)
lum=ref@np.array([.2126,.7152,.0722]);exposure=-np.log2(max(np.percentile(lum[mask],99),1e-8))
def display(a):
 x=np.maximum(a*2**exposure,0);x=np.clip((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*np.power(x,1/2.4)-.055)
 return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))
for n,a in imgs.items():display(a).save(O/(n+'.png'))
for n,e in errors.items():
 a=np.uint8(plt.get_cmap('magma')(np.clip(e,0,1))[:,:,:3]*255);a[~mask]=(23,26,31);Image.fromarray(a).save(O/(n+'-flip.png'))
fig,axes=plt.subplots(1,3,figsize=(16,4.6))
for name,label in [('full','Full update'),('batch1024','Budget 1024')]:
 x=np.array(info['checkpoints']);c=curves[name]
 axes[0].loglog(x,[c[str(n)]['mse_to_pt'] for n in x],'-o',label=label)
 axes[1].loglog(x,[c[str(n)]['mse_to_full_settled'] for n in x],'-o',label=label)
 axes[2].loglog(x*times[name]['graph_ms']/1000,[c[str(n)]['mse_to_full_settled'] for n in x],'-o',label=label)
for ax,title in zip(axes,['Error against PT','Convergence to settled full-update DDGI','Convergence per estimated GPU time']):
 ax.set_title(title);ax.set_ylabel('Linear HDR RGB MSE');ax.grid(True,alpha=.25);ax.legend()
axes[0].set_xlabel('Frames from empty probes');axes[1].set_xlabel('Frames from empty probes');axes[2].set_xlabel('Estimated graph GPU seconds')
fig.tight_layout();fig.savefig(O/'convergence.png',dpi=160);plt.close(fig)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
out=Image.new('RGB',(1920,1184),(23,26,31));draw=ImageDraw.Draw(out)
for i,(n,label) in enumerate([('full','Full update'),('batch1024','Budget 1024'),('pt','PT / 131072 spp')]):
 x=i%2*960;y=i//2*592;draw.text((x+10,y+8),label,font=font);out.paste(display(imgs[n]).resize((960,540)),(x,y+52))
out.save(O/'comparison.png')
result={'metrics':metrics,'timing':times,'convergence':curves,'capture':info,'reference':{'path':str(refpath),'sha256':hashlib.sha256(refpath.read_bytes()).hexdigest(),'spp':131072,'reused':True},'flip_parameters':params,'display_exposure_ev':float(exposure),'mask_pixels':int(mask.sum())}
(O/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
speed=times['full']['graph_ms']/times['batch1024']['graph_ms']
threshold_frames={name:next(n for n in info['checkpoints'] if all(curves[name][str(k)]['mse_to_full_settled']<1e-5 for k in info['checkpoints'] if k>=n)) for name in ['full','batch1024']}
result['convergence_threshold']={'metric':'instantaneous MSE to settled full DDGI < 1e-5 at this and all later checkpoints','frames':threshold_frames}
(O/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
conclusion='<p><strong>本次结果：分批模式整图 GPU 加速 %.2f 倍；稳定后的 MSE 与 HDR-FLIP 接近全量，未改善 DDGI 本身相对 PT 的偏差。</strong>以瞬时结果相对稳定全量 DDGI 的 MSE 小于 1e-5 且后续检查点不再超出为判据，全量首次满足于 %d 帧，分批为 %d 帧。此阈值仅用于本实验比较，不是通用收敛标准。</p>'%(speed,threshold_frames['full'],threshold_frames['batch1024'])
rows=''.join('<tr><td>'+label+'</td><td>'+str(info['runs'][n]['stats']['activeProbes'])+'</td><td>%.6g</td><td>%.6f</td><td>%.3f</td><td>%.3f</td></tr>'%(metrics[n]['mse'],metrics[n]['hdr_flip'],times[n].get('DDGI/ProbeUpdate',float('nan')),times[n]['graph_ms']) for n,label in [('full','全量更新'),('batch1024','每帧最多 1024')])
html="""<!doctype html><meta charset="utf-8"><title>Sponza 探针分批更新对比</title><style>body{background:#171a1f;color:#eee;font:17px/1.6 sans-serif;margin:30px auto;max-width:1600px}img{max-width:100%}td,th{padding:10px;border:1px solid #555}table{border-collapse:collapse}a{color:#9cf}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}</style><h1>Sponza 探针分批更新对比</h1>
<p>1920×1080，SponzaLambert，固定相机，点光源开启、方向光关闭。原生 DDGI 直接插值 probe；FG、WRC、ReSTIR、NRD、RTXDI 均关闭。仅改变探针更新调度，探针 22³，每个活跃探针 256 条射线，历史权重 0.97。</p>
<p>全量每帧更新 10648 个；预算模式每轮 10×1024＋408，11 帧覆盖一轮，平均 968 个/帧。非活跃探针在被选中时只发 32 条分类/重定位射线。两组均从空历史启动；8192 帧后用 Accumulate 累积 1024 帧作最终画质图。曲线使用未作画面累积的瞬时结果，防止启动期暗帧污染对收敛速度的判断。初始化历史权重按完整更新轮数，而非呈现帧数计算。</p>
<p>参考复用同一场景/相机/灯光的 131072 spp 未降噪 PT。MSE 在可见表面 mask 内计算线性 HDR RGB；HDR-FLIP 使用共同曝光范围、ACES、PPD 67。展示图统一曝光。GPU 耗时为稳定期 550 帧均值，包含完整 11 帧轮换；曲线第三图以帧数乘稳定期 GPU 均值估算，非实际墙钟时间。</p>
<table><tr><th>方案</th><th>活跃探针</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>ProbeUpdate ms</th><th>渲染图 ms</th></tr>"""+rows+'</table>'+conclusion+'<p>完整数据与配置：<a href="summary.json">summary.json</a>。该实验只衡量静态收敛；动态光照响应、相机运动与 WRC 质量不在本轮测试范围。</p><h2>稳定结果</h2><img src="comparison.png"><p><a href="full.png">全量原图</a> · <a href="batch1024.png">分批原图</a> · <a href="pt.png">PT 原图</a></p><h2>收敛曲线</h2><img src="convergence.png"><h2>HDR-FLIP 热力图</h2><p>统一 Magma [0,1]：暗为误差小，亮为误差大；深灰背景为 mask 外。</p><div class="grid"><div>全量<img src="full-flip.png"></div><div>预算 1024<img src="batch1024-flip.png"></div></div><h2>Pass 组织</h2><p>GBufferRT → DDGI〔选取批次 → 紧凑 TraceRays → SDK 辐照度/距离混合 → Relocation → Classification → 全屏直接光与 probe 插值〕→ Accumulate → ToneMapper。SDK 计算阶段保留全网格 dispatch，并在共享内存操作前按批次跳过；追踪 dispatch 仅覆盖本批探针。WRC 路径也应用同一批次，但本轮基准关闭 WRC。</p>'
(O/'report.html').write_text(html,encoding='utf-8')
