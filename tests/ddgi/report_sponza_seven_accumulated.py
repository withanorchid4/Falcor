"""Two seven-curve plots and three fixed-scale HDR-FLIP maps."""
from pathlib import Path
import sys,json,hashlib,re
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-seven-accumulated-20261120'
O=R/'docs/2026-11-20_Sponza七组累积收敛与射线预算对比';O.mkdir(exist_ok=True)
sys.path[:0]=[str(R/'build/final-gather-python'),str(R/'build/convergence-python')]
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
cfg=json.loads((D/'metric-settings.json').read_text())
labels={'ddgi_full':'DDGI / full update','ddgi_ac':'DDGI / AC nominal 204,800 rays','ddgi_id':'DDGI / idTech 326,144 rays','fg_full':'DDGI + half FG / full update','fg_ac':'DDGI + half FG / AC nominal 204,800 rays','fg_id':'DDGI + half FG / idTech 326,144 rays','worldcache':'WorldCache + half FG'}
zh={'ddgi_full':'原生 DDGI · 全量','ddgi_ac':'原生 DDGI · 刺客信条影名义预算','ddgi_id':'原生 DDGI · idTech 8 预算','fg_full':'DDGI＋半分辨率 FG · 全量','fg_ac':'DDGI＋半分辨率 FG · 刺客信条影名义预算','fg_id':'DDGI＋半分辨率 FG · idTech 8 预算','worldcache':'WorldCache＋半分辨率 FG'}
colors=['#1764ab','#e68a17','#26974b','#1764ab','#e68a17','#26974b','#a03b9d']
for metric,title,ylabel in [('mse','Accumulated image MSE against PT','Linear HDR RGB MSE (lower is better)'),('hdr_flip','Accumulated image HDR-FLIP against PT','Mean HDR-FLIP (lower is better)')]:
 fig,ax=plt.subplots(figsize=(12,7.4))
 for j,(name,label) in enumerate(labels.items()):
  points=info['runs'][name]['checkpoints'];x=list(map(int,points));y=[points[str(n)][metric] for n in x]
  ax.plot(x,y,color=colors[j],ls='--' if name.startswith('fg_') else '-',marker='o',ms=3,lw=1.8,label=label)
 ax.set_xscale('log',base=2)
 if metric=='mse':ax.set_yscale('log')
 else:ax.set_ylim(0,1)
 ax.set_title(title);ax.set_xlabel('Accumulated frames from empty cache (log2 scale)');ax.set_ylabel(ylabel)
 ax.grid(True,which='both',alpha=.22);ax.legend(loc='upper center',bbox_to_anchor=(.5,-.16),ncol=2,fontsize=9,frameon=False)
 fig.subplots_adjust(bottom=.29);fig.savefig(O/(metric+'-convergence.png'),dpi=160);plt.close(fig)
def exr(p):return OpenEXR.File(str(p)).channels()['RGB'].pixels
refpath=R/'build/sponza-worldcache-ddgi-official-probes-20261119/reference-131072spp.exr';ref=exr(refpath)
mask=np.linalg.norm(exr(D/'ddgi_full-1.Visibility.normW.0.exr'),axis=-1)>.5
def display(a):
 x=np.maximum(a*2**cfg['display_exposure_ev'],0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))
display(ref).save(O/'pt.png')
finals={};cross={}
for name in labels:
 run=info['runs'][name];n=run['final_frame'];a=exr(D/(name+'-'+str(n)+'.Accumulate.output.0.exr'));finals[name]=a
 if name in ['ddgi_full','fg_full','worldcache']:
  display(a).save(O/(name+'.png'))
  err=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=cfg['flip_parameters'].copy())[0][:,:,0]
  rgb=plt.get_cmap('magma')(np.clip(err,0,1))[:,:,:3];rgb[~mask]=np.array([23,26,31])/255
  Image.fromarray(np.uint8(rgb*255+.5)).save(O/(name+'-flip-1080p.png'))
  fig,ax=plt.subplots(figsize=(12,7));ax.imshow(rgb);ax.axis('off');ax.set_title(labels[name]+f' / accumulated {n:,} frames')
  sm=plt.cm.ScalarMappable(norm=plt.Normalize(0,1),cmap='magma');fig.colorbar(sm,ax=ax,orientation='horizontal',fraction=.045,pad=.035,label='HDR-FLIP error: 0 = low, 1 = high (fixed scale)')
  fig.tight_layout();fig.savefig(O/(name+'-heatmap.png'),dpi=160);plt.close(fig)
for name in ['ddgi_ac','ddgi_id','fg_ac','fg_id']:
 base=finals['fg_full' if name.startswith('fg_') else 'ddgi_full'];a=finals[name]
 cross[name]={'mse_to_full_update':float(np.mean((a[mask].astype(np.float64)-base[mask])**2))}
cross_rows=''.join(f'<tr><td>{zh[n]}</td><td>{r["mse_to_full_update"]:.6g}</td></tr>' for n,r in cross.items())
rows=''
for name in labels:
 run=info['runs'][name];n=run['final_frame'];m=run['checkpoints'][str(n)];t=json.loads((D/(name+'-timing.json')).read_text())['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['mean']
 rows+=f'<tr><td>{zh[name]}</td><td>{run["budget"] or "独立缓存"}</td><td>{n}</td><td>{m["mse"]:.7g}</td><td>{m["hdr_flip"]:.5f}</td><td>{t:.3f}</td><td>{"通过" if run["stable"] else "未通过"}</td></tr>'
stable_rows=''
for name in labels:
 run=info['runs'][name];n=run['final_frame'];m=run['checkpoints'][str(n)]
 stable_rows+=f'<tr><td>{zh[name]}</td><td>{m["tail_relative_rgb_rms"]:.3%}</td><td>{m["display_mean_abs_levels"]:.4f}</td><td>{m["display_p99_abs_levels"]:.4f}</td><td>{m["relative_pt_mse_change"]:+.3%}</td><td>{m["relative_pt_flip_change"]:+.3%}</td></tr>'
acurl="https://advances.realtimerendering.com/s2025/content/Advances%202025%20-%20Raytracing%20the%20world%20of%20Assassin%27s%20Creed%20Shadows.pdf"
idpath='C:/Users/luozilong01/Desktop/GI演讲资料/GI演讲资料/IdTech8/SOUSA_SIGGRAPH_2025_Final.pdf'
summary={'capture':info,'metric_settings':cfg,'reference':{'path':str(refpath),'sha256':hashlib.sha256(refpath.read_bytes()).hexdigest(),'spp':131072},'stable_cross_budget_differences':cross,'budget_sources':{'ac':{'url':acurl,'slides':[37,39,132],'probes':512,'directions_per_probe':400,'nominal_ray_budget':204800,'interpretation':'User selected full-retrace nominal budget, not 16% GBuffer refresh fraction'},'idtech8':{'path':idpath,'pdf_page':16,'probes':16**3+10**3,'rays_per_probe':64,'ray_budget':326144}}}
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
html=f'''<!doctype html><meta charset="utf-8"><title>Sponza 七组累积收敛与射线预算对比</title><style>body{{max-width:1500px;margin:32px auto;padding:0 20px;background:#171a1f;color:#eee;font:17px/1.7 sans-serif}}img{{max-width:100%}}td,th{{padding:9px;border:1px solid #555}}table{{border-collapse:collapse}}a{{color:#9cf}}</style>
<h1>Sponza 七组累积收敛与射线预算对比</h1>
<p>两张曲线图各有七条曲线，全部取 Accumulate 后的最终颜色：原生 DDGI 三档、DDGI＋半分辨率 FG 三档，以及迁移版 WorldCache＋半分辨率 FG。横轴从空缓存和空画面历史开始计帧，不预热后偷换起点；每个检查点都是第 1 帧至该帧的连续平均。纵轴分别为相对同一张 PT 的 MSE 与 HDR-FLIP。没有展示未累积的单帧噪声曲线。</p>
<p>冷启动期间缓存自身也在变化，因此误差曲线不保证单调下降，早期偶然较低的误差不代表最终质量更好。曲线在每组实际通过稳定检查的帧数结束，不将不同最终帧数的数据伪装成相同采样预算。</p>
<p>实线为原生 DDGI，虚线为 DDGI＋半分辨率 FG，同色对应同一预算；紫色为 WorldCache。三条 FG 的 MSE 曲线几乎重合，并非漏画。七组最终均在 65536 帧通过连续两次稳定检查。</p>
<h2>预算与统一条件</h2>
<p>SponzaLambert，1920×1080，固定相机 (-9,1.6,0) 看向 (8,2.5,0)，点光源 RGB 600，方向光关闭。官方布局 22³=10648 probes，中心 (-0.4,5.4,-0.25)，间距 (1.02,0.5,0.45)。每 probe 256 rays，hysteresis 0.97，开启 relocation/classification。主命中法线修正开启。两条 FG 均为 960×540、每个粗像素一根漫反射射线、固定左上采样、同一深度/法线引导重建；ReSTIR、NRD、RTXDI、WRC 屏幕/世界共享关闭。Accumulate 为 SingleCompensated，关闭自动重置。</p>
<table><tr><th>档位</th><th>来源乘积</th><th>本地更新 probe/帧</th><th>本地名义 probe rays/帧</th></tr><tr><td>全量</td><td>10648×256</td><td>10648</td><td>2725888</td></tr><tr><td>刺客信条影 PC 名义预算</td><td>512×20×20</td><td>800</td><td>204800</td></tr><tr><td>idTech 8 高档预算</td><td>(16³＋10³)×64</td><td>1274</td><td>326144</td></tr></table>
<p>来源：<a href="{acurl}">刺客信条影 SIGGRAPH 2025 演讲</a>第 37、39、132 页；<a href="file:///{idpath}">idTech 8 演讲</a>PDF 第 16 页（幻灯片 15）。按用户选定口径，刺客信条影使用全部 512 probes 重追 400 个方向的名义预算；实际演讲中只有约 16% 重追 GBuffer，其他 probe 可复用几何，此处不采用该折减。idTech 8 取每帧一个 16³ cascade 加一个 10³ local volume、64 rays 的高档配置。</p>
<p>分批调度跨网格尾部回绕，每帧补足 800 或 1274 个，不留短尾批。以上匹配的是名义探针追踪预算；inactive 探针仍遵循 DDGI 原策略，仅追踪 32 条固定射线，所以实际 TraceRay 少于名义值。直接光阴影射线和 FG 射线不计入该乘积。该实验不复现两款游戏的优先级调度、缓存复用或实际 GPU 工作量。</p>
<p>WorldCache 是本项目迁移版：每帧 240×135 个更新路径起点、最多 3 跳、2²⁰ 条目、density 20、最小 cell 0.025、history 16、64 帧未用淘汰，不设亮度 clamp。它没有 DDGI probe，不强行套用这三档预算。</p>
<p>PT 复用相同场景/灯光的 131072 spp 未降噪参考。MSE 为共同可见表面 mask 内线性 HDR RGB；HDR-FLIP 使用共同曝光范围、ACES、PPD 67。所有展示图共用曝光。每条曲线仅一条随机序列，不把微小差异解释为普遍优势。</p>
<h2>最终结果</h2><table><tr><th>方案</th><th>probe/帧</th><th>累积帧数</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>整图 ms</th><th>稳定检查</th></tr>{rows}</table>
<p>下表直接比较相同算法在不同更新预算下的稳定图，不与 PT 混淆。小差异表示两档预算最终接近同一画面，不意味着每个像素严格相等。</p><table><tr><th>低预算方案</th><th>与对应全量更新稳定图的 MSE</th></tr>{cross_rows}</table>
<h2>1. MSE 收敛</h2><img src="mse-convergence.png"><h2>2. HDR-FLIP 收敛</h2><img src="hdr_flip-convergence.png">
<h2>最终画面稳定性</h2><p>不是只判断 probe 数值稳定：至少累积 65536 帧，并要求连续两次累积翻倍同时满足以下条件：最终颜色差的线性 RGB RMS / PT RGB RMS &lt;0.1%；统一显示映射后平均绝对颜色变化 &lt;0.25/255，99 百分位 &lt;2/255；对 PT 的 MSE 与 HDR-FLIP 相对变化各 &lt;1%。未满足则继续翻倍，表中明确标记是否通过。这是静态最终画面的实用判稳，非数学无偏或逐像素零变化保证。</p>
<table><tr><th>方案</th><th>尾段相对 RGB RMS</th><th>显示平均变化 /255</th><th>显示 P99 变化 /255</th><th>MSE 变化</th><th>HDR-FLIP 变化</th></tr>{stable_rows}</table>
<h2>3. 原生 DDGI 稳定后 HDR-FLIP</h2><p>采用每帧全量更新 probe 的稳定图。这里的“全量”是更新频率，原生 DDGI 本身在全分辨率像素上查询 probe。</p><a href="ddgi_full-flip-1080p.png"><img src="ddgi_full-heatmap.png"></a>
<h2>4. DDGI＋半分辨率 FG 稳定后 HDR-FLIP</h2><p>采用每帧全量更新 probe，FG 仍为半分辨率。</p><a href="fg_full-flip-1080p.png"><img src="fg_full-heatmap.png"></a>
<h2>5. WorldCache＋半分辨率 FG 稳定后 HDR-FLIP</h2><a href="worldcache-flip-1080p.png"><img src="worldcache-heatmap.png"></a>
<p>三图共用固定 Magma [0,1] 色标：暗色误差小、亮色误差大；不是百分比相似度，也不区分偏亮/偏暗。mask 外是深灰背景。</p>
<p>原图：<a href="ddgi_full.png">原生 DDGI</a> · <a href="fg_full.png">DDGI＋半 FG</a> · <a href="worldcache.png">WorldCache＋半 FG</a> · <a href="pt.png">PT</a>；<a href="summary.json">完整数据、参数、源码哈希和各预算最终图之间的差异</a>。</p>'''
(O/'report.html').write_text(html,encoding='utf-8')
print({n:{'frame':r['final_frame'],'stable':r['stable'],'metrics':r['checkpoints'][str(r['final_frame'])]} for n,r in info['runs'].items()})
