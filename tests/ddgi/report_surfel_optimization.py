from pathlib import Path
import sys,json
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'build/final-gather-python'));sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw
O=R/'docs/2026-11-22_Surfel查询优化对比';O.mkdir(exist_ok=True)
def read(p):return OpenEXR.File(str(p)).channels()['RGB'].pixels
def pic(a):
 x=np.maximum(a*2**-2.32679,0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1);x=np.where(x<=.0031308,x*12.92,1.055*x**(1/2.4)-.055);return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))
ref=read(R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr');summary={};arrays={}
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
prefix='/onFrameRender/RenderGraphExe::execute()'
for name in ['baseline','optimized']:
 D=R/('build/surfel-opt-'+name);assert (D/'complete.json').exists() and not (D/'failure.txt').exists()
 a=read(D/'surfel-8192.Accumulate.output.0.exr');assert np.isfinite(a).all();arrays[name]=a
 norm=read(D/'surfel-8192.Visibility.normW.0.exr');mask=np.linalg.norm(norm,axis=-1)>.5
 t=json.loads((D/'surfel-timing.json').read_text())['events']
 flip=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 atomic=json.loads((D/'atomic.json').read_text());marks={}
 for mark in [True,False]:
  vals=[x['timing']['events'][prefix+'/Surfel/Surfel Evaluation Pass/gpu_time']['stats']['mean'] for x in atomic if x['mark']==mark];marks[str(mark)]=vals
 summary[name]={'mse':float(np.mean((a[mask].astype('float64')-ref[mask])**2)),'hdr_flip':float(flip[mask].mean()),'graph_ms':t[prefix+'/gpu_time']['stats']['mean'],'query_ms':t[prefix+'/Surfel/Surfel Evaluation Pass/gpu_time']['stats']['mean'],'pack_ms':t.get(prefix+'/Surfel/Pack Query Data/gpu_time',{}).get('stats',{}).get('mean',0),'atomic_frozen_query_ms':marks,'config':json.loads((D/'complete.json').read_text())}
 pic(a).save(O/(name+'.png'))
summary['lean_global_ablation']=json.loads((R/'build/surfel-lean-global.json').read_text())
summary['difference']={'mse':float(np.mean((arrays['baseline'][mask].astype('float64')-arrays['optimized'][mask])**2))}
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
panel=Image.new('RGB',(1920,580),(23,26,31));d=ImageDraw.Draw(panel)
for j,n in enumerate(['baseline','optimized']):panel.paste(pic(arrays[n]).resize((960,540)),(j*960,40));d.text((j*960+12,10),n,fill='white')
panel.save(O/'comparison.png')
atomic_rows=''.join(f"<tr><td>{n}</td><td>{np.mean(s['atomic_frozen_query_ms']['True']):.4f}</td><td>{np.mean(s['atomic_frozen_query_ms']['False']):.4f}</td><td>{np.mean(s['atomic_frozen_query_ms']['True'])-np.mean(s['atomic_frozen_query_ms']['False']):.4f}</td></tr>" for n,s in summary.items() if n in ['baseline','optimized'])
rows=''.join(f"<tr><td>{n}</td><td>{s['mse']:.8g}</td><td>{s['hdr_flip']:.5f}</td><td>{s['graph_ms']:.3f}</td><td>{s['query_ms']:.3f}</td><td>{s['pack_ms']:.3f}</td></tr>" for n,s in summary.items() if n in ['baseline','optimized'])
lean=summary['lean_global_ablation']
notes=f"<p>消融：仅精简普通显示路径（移走调试字段读取/计算），保留大结构全局读取、不使用组共享，查询 {lean['query_ms']:.3f} ms、整图 {lean['graph_ms']:.3f} ms。因此本次主要收益来自普通显示路径精简；组共享与紧凑缓冲相对该消融没有表现出独立收益，可能受到候选分布、缓存和组同步成本影响，尚未实测各硬件计数器。</p>"
html='''<!doctype html><meta charset="utf-8"><title>Surfel 查询优化对比</title><style>body{background:#171a1f;color:#eee;font:17px/1.7 sans-serif;max-width:1600px;margin:30px auto}img{max-width:100%}td,th{padding:8px;border:1px solid #555}a{color:#9cf}</style><h1>Surfel 查询优化对比</h1><p>SponzaLambert，1920×1080，RTX 5070，D3D12，方向光强度50，点光关闭。缓存预热2048帧，之后 Accumulate 8192帧，参考未经降噪的65536 spp PT。优化前后使用相同积分公式与全分辨率查询，保留可见性原子标记。baseline 使用原移植版本的完整查询 shader；optimized 增加48字节紧凑缓冲和128候选组共享缓存。不同格子的线程组与超出共享容量的候选继续从全局读取，不截断列表。</p><table><tr><th>方案</th><th>MSE</th><th>HDR-FLIP</th><th>整图ms</th><th>查询ms</th><th>数据整理ms</th></tr>'''+rows+'</table>'+notes+'<h2>原子标记消融</h2><table><tr><th>方案</th><th>开启ms</th><th>关闭ms</th><th>差值ms</th></tr>'+atomic_rows+'</table><img src="comparison.png"><p><a href="baseline.png">优化前1080p</a> · <a href="optimized.png">优化后1080p</a></p><p>原子标记实验在同一份冻结缓存上交替开关标记，每次预热32帧、计时128帧，各测3次。冻结期间停止生成、积分与回收，防止关闭标记改变缓存分布。该消融只用于测开销，正式路径仍开启标记。详情见 <a href="summary.json">完整数据</a>。</p>'
(O/'report.html').write_text(html,encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
