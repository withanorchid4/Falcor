"""Quality, actual GPU timing, and spatial cell-size audit for cache comparison."""
from pathlib import Path
import sys,json,hashlib
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-sharc-official-20261122';O=R/'docs/2026-11-22_Sponza方向光SHaRC官方配置对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
from matplotlib import colormaps
import matplotlib.pyplot as plt
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
cfg=json.loads((D/'display.json').read_text())
def read(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels
 assert np.isfinite(a).all();return a
def path(n,c):return D/(n+'-'+str(info['runs'][n]['frames'])+'.'+c+'.0.exr')
ref=read(info['pt_reference']);names=['worldcache','sharc','pt']
imgs={n:read(path(n,'Accumulate.output')) for n in names[:2]};imgs['pt']=ref
norm=read(D/'pt-512.Visibility.normW.0.exr');mask=np.linalg.norm(norm,axis=-1)>.5
for n in names[:2]:assert np.array_equal(read(path(n,'Visibility.normW')),norm)
pos=read(path('worldcache','Visibility.posW'));assert np.array_equal(pos,read(path('sharc','Visibility.posW')))
dist=np.linalg.norm(pos[mask]-np.array([-9,1.6,0]),axis=-1)
wc=.025*np.exp2(np.maximum(np.floor(np.log2(np.maximum(dist,.5)/.5)),0))
# Official SHaRC biases position before level selection. Preserve and audit it.
ds=np.linalg.norm(pos[mask]+1e-4-np.array([-9,1.6,0]),axis=-1)
sh=np.exp2(np.maximum(np.floor(np.log2(ds)+2),1)-2)/20
grid={'equal_width_fraction':float(np.mean(wc==sh)),'worldcache_widths':np.unique(wc).tolist(),'sharc_widths':np.unique(sh).tolist(),
 'formula_worldcache':'.025 * 2^max(0,floor(log2(distance/.5)))',
 'formula_sharc':'2^(max(1,floor(log2(distance)+2))-2)/20',
 'note':'SHaRC applies position bias 1e-4 before distance/level; WorldCache applies it only to cell coordinates. Boundary pixels may differ.'}
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
metrics={};times={};curves={}
def display(a,extra=0):
 x=np.maximum(a*2**(cfg['exposure_ev']+extra),0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))
for n,a in imgs.items():display(a).save(O/(n+'.png'))
for n in names[:2]:
 a=imgs[n];f=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 metrics[n]={'mse':float(np.mean((a[mask].astype(np.float64)-ref[mask])**2)),'hdr_flip':float(f[mask].mean())}
 heat=np.uint8(colormaps['magma'](np.clip(f,0,1))[:,:,:3]*255);heat[~mask]=[23,26,31];Image.fromarray(heat).save(O/(n+'-flip.png'))
 t=json.loads((D/(n+'-timing.json')).read_text());prefix='/onFrameRender/RenderGraphExe::execute()'
 times[n]={k[len(prefix)+1:-9]:v['stats']['mean'] for k,v in t['events'].items() if k.startswith(prefix+'/') and k.endswith('/gpu_time')}
 times[n]['graph_ms']=t['events'][prefix+'/gpu_time']['stats']['mean']
 curves[n]={}
 for frame in info['runs'][n]['checks']:
  a=read(D/(n+'-'+frame+'.Accumulate.output.0.exr'))
  curves[n][frame]=float(np.mean((a[mask].astype(np.float64)-ref[mask])**2))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
labels={'worldcache':'LumenWorldCache + half FG','sharc':'NVIDIA SHaRC + half FG','pt':'PT Reference / 65536 spp'}
def panel(extra=0,roi=None):
 w,h=(roi[2]-roi[0],roi[3]-roi[1]) if roi else (960,540)
 out=Image.new('RGB',(w*3,h+48),(23,26,31));d=ImageDraw.Draw(out)
 for i,n in enumerate(names):
  a=display(imgs[n],extra);a=a.crop(roi) if roi else a.resize((w,h))
  out.paste(a,(i*w,48));d.text((i*w+8,7),labels[n],font=font,fill='white')
 return out
panel().save(O/'comparison.png');panel(2,(440,640,1140,1080)).save(O/'contact-details.png')
fig,ax=plt.subplots(figsize=(8,4))
for n in names[:2]:
 x=[int(k) for k in curves[n]];ax.loglog(x,list(curves[n].values()),'-o',label=labels[n])
ax.set_xlabel('Accumulated frames after cache warmup');ax.set_ylabel('Linear HDR RGB MSE vs PT');ax.grid(True,alpha=.3);ax.legend();fig.tight_layout();fig.savefig(O/'convergence.png',dpi=160);plt.close(fig)
summary={'experiment':info,'metrics':metrics,'gpu_ms':times,'cell_audit':grid,'mse_curves':curves,'display':cfg,'flip_parameters':params,
 'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (R/'Source/RenderPasses/RTXGIDDGI').glob('*') if p.is_file()}}
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''
for n in names[:2]:
 r=info['runs'][n];check=r['checks'][str(r['frames'])]
 rows+=f'<tr><td>{labels[n]}</td><td>{r["frames"]}</td><td>{metrics[n]["mse"]:.8g}</td><td>{metrics[n]["hdr_flip"]:.5f}</td><td>{times[n]["graph_ms"]:.3f}</td><td>{check["relative_rgb_rms"]:.3%}</td></tr>'
obs=(O/'observations.html').read_text(encoding='utf-8') if (O/'observations.html').exists() else '<p>待检查画面。</p>'
html=f'''<!doctype html><meta charset="utf-8"><title>Sponza 方向光 SHaRC 与世界缓存对比</title><style>body{{background:#171a1f;color:#eee;font:17px/1.7 sans-serif;max-width:1600px;margin:30px auto;padding:0 20px}}img{{max-width:100%}}a{{color:#9cf}}td,th{{border:1px solid #555;padding:8px}}table{{border-collapse:collapse}}</style>
<h1>SponzaLambert：方向光 50，SHaRC 与 LumenWorldCache</h1>
<p>相机 (-9,1.6,0) 看向 (8,2.5,0)，方向光 (0.3,-1,0.2)、强度 RGB 50，点光关闭。已设为 SponzaLambert 默认灯光，原版 Sponza 不变。1920×1080，相同 Lambert 材质和法线修正。复用 11 月 20 日同灯光/相机的未降噪 PT 65536 spp；两组 GBuffer 法线与参考逐像素一致，两组位置缓冲也完全一致。</p>
<p>两组均为独立缓存＋960×540 FG＋相同深度/法线引导重建＋Accumulate（SingleCompensated）＋统一显示映射。NRD、ReSTIR、RTXDI 关闭，半分辨率采样位置固定。WorldCache 沿用原配置（8×8 GBuffer 起点、3 个更新顶点加末端 bootstrap）；SHaRC 恢复官方示例配置（5×5 下采样的相机射线，包含首个命中，最大 8 个顶点，无自定义末端 bootstrap）。两组缓存预热 8192 帧后清空屏幕累积。只对齐空间格子尺寸，不再强行对齐更新预算。</p>
<h2>格子大小对齐</h2><p>WorldCache：minCell=0.025、density=20；SHaRC：sceneScale=20、logarithmBase=2、levelBias=2。对应最小边长相同，1/2/4/8/16 米的格子边长分别为 0.05/0.1/0.2/0.4/0.8 米。对可见表面实测，格子边长相同的像素占比为 {grid['equal_width_fraction']:.6%}。细微边界差异可能来自位置偏置参与距离计算的时机；不修改官方 SDK。</p>
<p>WorldCache 沿用容量 2²⁰、history=16、stale age=64；SHaRC 使用官方示例容量 2²²、history=20、stale age=60，并启用材质去调制和原生 64 位哈希原子操作。WorldCache 核心缓存约 56 MiB；SHaRC 核心缓存约 160 MiB。两边的哈希冲突处理、法线分桶、历史融合和多跳更新算法保留原实现：WorldCache 用主轴六面法线分桶，SHaRC 默认用法线符号八象限。因此这不是所有缓存行为完全一致的实验。</p>
<h2>结果</h2><table><tr><th>方案</th><th>累积帧数</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>完整图 GPU ms ↓</th><th>末次翻倍相对 RGB RMS</th></tr>{rows}</table>
<p>稳定检查：累积翻倍后相对 RGB RMS &lt;0.1%，显示平均变化 &lt;0.25/255，P99 &lt;2/255；至少 16384 帧。GPU 为稳定期 512 帧均值，包含 GBuffer、缓存更新、Resolve、FG、重建、Accumulate 和显示，详细分项见 JSON。MSE 在可见表面 mask 内计算线性 HDR RGB；HDR-FLIP 共同曝光范围、ACES、PPD 67，不是百分比误差。</p>
<img src="comparison.png"><p><a href="worldcache.png">WorldCache 1080p</a> · <a href="sharc.png">SHaRC 1080p</a> · <a href="pt.png">PT 1080p</a></p>{obs}
<h2>接触细节（统一额外＋2 EV）</h2><img src="contact-details.png"><h2>累积过程 MSE</h2><img src="convergence.png">
<h2>HDR-FLIP 热力图</h2><p>统一 Magma [0,1]，暗为误差小，亮为误差大，mask 外为深灰。</p><p>WorldCache</p><img src="worldcache-flip.png"><p>SHaRC</p><img src="sharc-flip.png">
<h2>接入方式和限制</h2><p>官方示例基准固定为 NVIDIA RTXGI <a href="https://github.com/NVIDIA-RTX/RTXGI/tree/04372d7f91bb3a0444f9fd95d3f34381ea4e3b39/Samples/Pathtracer">04372d7f</a>。对照 UI.h、Pathtracer.cpp、Shaders/Pathtracer.hlsl 和 SharcResolve.hlsl。SDK 版本与该示例引用的子模块完全一致。Anti Firefly UI 字段在此提交中没有实际进入 SHaRC 着色器计算，因此没有自行添加过滤器。</p><p>SHaRC 使用 NVIDIA 官方 1.8.3（4e21b585），CMake 自动下载固定版本，SDK 未修改。执行顺序：GBuffer → SHaRC Update → UAV barrier → 官方 Resolve → UAV barrier → FG Query → Reconstruct → Accumulate → Display。SDK 的缓存重采样和相邻层历史融合启用；材质去调制开启，方向 SH 编码、responsive lighting 保持官方默认关闭，面向本次 Lambert 对比。</p>
<p>SHaRC 查询只发生在间接命中点，命中返回总出射辐亮度，不重复添加直接光。使用官方射线段长度大于格子对角线及 roughness footprint 判断，不满足或缓存缺失时继续追踪；最大 8 个路径顶点（包括已经由 GBuffer/FG 处理的相机首个命中），保留官方俄罗斯轮盘和 throughput<0.01 终止阈值；WorldCache 仍沿用原来的单次查询，缺失返回零。回退成本计入耗时，画质差异可能同时受缓存与回退策略影响。两边材质、解析光 NEE、环境 miss 与 alpha test 共用 Falcor 桥接。SHaRC 的随机数发生器、材质/光源接口及半分辨率 FG 输出仍使用 Falcor，不是整个官方渲染器逐位复刻；本轮只含一个方向光和 Lambert 材质。动态图、复杂镜面/透射材质和 Vulkan 本轮未验证。</p>
<p><a href="summary.json">完整配置/统计/耗时</a> · <a href="https://github.com/NVIDIA-RTX/SHARC">官方 SHaRC</a></p>'''
(O/'report.html').write_text(html,encoding='utf-8');print(json.dumps({'metrics':metrics,'gpu':times,'grid':grid},indent=2))
