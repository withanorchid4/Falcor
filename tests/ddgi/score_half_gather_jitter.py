from pathlib import Path
import sys,json,hashlib
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
D=R/'build/half-gather-jitter';OLD=R/'build/highres-1080p-split-rerun'
O=R/'docs/2026-11-18_DDGI-half-sample-jitter';O.mkdir(exist_ok=True)
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
def load(path):
 a=OpenEXR.File(str(path)).channels()['RGB'].pixels;assert np.isfinite(a).all();return np.ascontiguousarray(a)
def read(tag):return load(D/(tag+'.Accumulate.output.0.exr'))
ref=load(OLD/'reference-65536spp.exr');mask=np.load(OLD/'surface-mask.npy')
params=json.loads((R/'docs/2026-11-18_DDGI-1080p/summary.json').read_text())['flip_parameters']
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
def flip(a):return float(flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0][mask].mean())
def display(a):
 x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055);return Image.fromarray(np.uint8(x*255+.5))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
labels={'fixed':'Fixed: top-left (0,0)','jitter':'Jitter: 8-frame phases','pt':'PT reference'}
def panel(items):
 w,h=items[0][1].size;c=Image.new('RGB',(w*len(items),h+52),(23,26,31));dr=ImageDraw.Draw(c)
 for i,(label,img) in enumerate(items):dr.text((i*w+12,10),label,font=font,fill='white');c.paste(img,(i*w,52))
 return c
result={'capture':info,'metrics':{},'reference':'Reused identical-scene undenoised PT 65536 spp from highres-1080p-split-rerun','flip_parameters':params}
imgs={}
for name in ['fixed','jitter']:
 a=read(name+'-65536');previous=read(name+'-32768')
 metric={'mse':mse(a,ref),'hdr_flip':flip(a),'checkpoint_mse':{str(n):mse(read(name+'-'+str(n)),ref) for n in info['checkpoints']},
 'mse_change_last_doubling':mse(a,ref)/mse(previous,ref)-1,'tail_difference_mse':mse(a,previous),'32_frame_hdr_flip':flip(read(name+'-32'))}
 mean=None;m2=None
 for i in range(8):
  v=read(name+'-stable-'+str(i))[mask].astype(np.float64)
  if mean is None:mean=v.copy();m2=np.zeros_like(mean)
  else:delta=v-mean;mean+=delta/(i+1);m2+=delta*(v-mean)
 metric['temporal_variance_8frames']=float(np.mean(m2/8))
 t=json.loads((D/(name+'-timing.json')).read_text());prefix='/onFrameRender/RenderGraphExe::execute()'
 metric['gpu_frame_ms']=t['events'][prefix+'/gpu_time']['stats']['mean']
 metric['passes']={k:t['events'][prefix+'/'+k+'/gpu_time']['stats']['mean'] for k in ['Visibility','DDGI','Reconstruct','Accumulate','Display']}
 result['metrics'][name]=metric;imgs[name]=display(a);imgs[name].save(O/(name+'.png'))
imgs['pt']=display(ref);imgs['pt'].save(O/'pt.png')
result['fixed_vs_previous_run_max_abs']=float(np.max(np.abs(read('fixed-65536')-load(OLD/'half-65536.Accumulate.output.0.exr'))))
assert result['fixed_vs_previous_run_max_abs']<1e-6
result['mse_change_jitter_vs_fixed']=result['metrics']['jitter']['mse']/result['metrics']['fixed']['mse']-1
result['flip_change_jitter_vs_fixed']=result['metrics']['jitter']['hdr_flip']/result['metrics']['fixed']['hdr_flip']-1
panel([('Fixed: top-left (0,0) / 65536 frames',imgs['fixed']),('Jitter: 8-frame phases / 65536 frames',imgs['jitter']),('PT reference / 65536 spp',imgs['pt'])]).save(O/'comparison.png')
roi=(760,480,1260,980)
panel([(labels[k],imgs[k].crop(roi).resize((1000,1000),Image.Resampling.NEAREST)) for k in ['fixed','jitter','pt']]).save(O/'detail.png')
for n in [1,8,32,128]:panel([(labels[k]+' / '+str(n)+' frames',display(read(k+'-'+str(n)))) for k in ['fixed','jitter']]).save(O/('frames-'+str(n)+'.png'))
(O/'summary.json').write_text(json.dumps(result,indent=2))
rows=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.5f}</td><td>{v['gpu_frame_ms']:.3f}</td><td>{v['temporal_variance_8frames']:.5g}</td></tr>" for k,v in result['metrics'].items())
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Half FG 采样偏移前后对比</title><style>body{{max-width:1500px;margin:36px auto;padding:0 24px;background:#171a20;color:#ddd;font:16px/1.7 system-ui}}img{{max-width:100%}}a{{color:#8dc7ff}}td,th{{border:1px solid #555;padding:8px 12px}}table{{border-collapse:collapse}}</style>
<h1>半分辨率 FG：固定位置与按帧偏移</h1><h2>图例与实验范围</h2>
<p><strong>Fixed（固定左上角）：</strong>半分辨率像素 (u,v) 每帧对应原图 (2u,2v)，块内偏移为 (0,0)。图像坐标 x 向右、y 向下，因此它是每个 2×2 块的左上角。这是旧实现的约定，不是 fixed 一词必然表示左上角，也不意味着射线方向固定；方向仍每帧随机采样。</p>
<p><strong>Jitter（按帧轮换位置）：</strong>对应原图 (2u,2v)+offset(frame)，四个块内位置轮换。两组始终从所选像素的中心读取 GBuffer，不额外进行像素内部子像素抖动。</p>
<p><strong>与本地 Lumen 的一致范围：</strong>只对齐 DownsampleFactor=2 时 Hammersley16(frame,8,0) 量化得到的块内偏移序列，以及在重建中使用实际样本位置的原则；序列由各自帧计数驱动，不要求两个程序起始相位同步。没有移植整套 ReSTIR Gather。</p>
<table><tr><th>步骤</th><th>本实现</th><th>本地 Lumen ReSTIR Gather</th></tr>
<tr><td>块内位置偏移</td><td>8 帧周期，四相位各两次</td><td>默认降采样2时相同的量化 Hammersley 序列</td></tr>
<tr><td>射线方向采样</td><td>Falcor SampleGenerator＋材质 BSDF 采样；Lambert 为余弦加权半球采样</td><td>BlueNoiseVec2＋UniformSampleHemisphere，初始候选为均匀半球采样</td></tr>
<tr><td>命中点光照</td><td>发光＋直接光＋DDGI 漫反射间接光</td><td>Surface Cache 或 Hit Lighting 路径</td></tr>
<tr><td>样本复用</td><td>未接 reservoir 时空重采样</td><td>reservoir 时间／空间重采样</td></tr>
<tr><td>重建</td><td>原来的 4×4 共16邻点深度／法线引导重建，坐标随偏移修正</td><td>本地默认16样本螺旋采样，另支持抖动双线性；从 reservoir 结合当前像素材质积分</td></tr>
<tr><td>时间处理</td><td>静态 Accumulate，无重投影</td><td>历史重投影、reservoir 复用与后续时间滤波</td></tr></table>
<p>因此本实验结论只反映“保留我们现有采样与重建，改变块内位置”的影响，不能用于判断完整 Lumen 方案的收益。</p>
<p><strong>本场景结论：</strong>前后稳定画面几乎一致，按帧偏移未带来明确的整体画质改善；稳定 MSE 略增约 0.34%，HDR-FLIP 略增约 0.03%。32 帧时 MSE 略降约 0.23%、HDR-FLIP 略降约 0.31%，不足以证明普遍改善。此结果针对静态 Lambert Cornell，不代表细小几何或运动场景。保留为可选开关，默认关闭。</p><p>验证：481×271 下，八帧实际追踪覆盖四种相位各两次；非当前相位像素没有 FG 输出。开关采样偏移、FG、全／半分辨率后均正确清空累积，输出有限。固定采样长累积结果与上一轮逐像素完全一致。</p>
<p>1920×1080 Lambert Cornell，顶灯点光源；FG 为 960×540。两组分别预热 2560 帧并重置累积，再累积 65536 帧。相同相机、probe、材质、灯光和 16-tap 重建。NRD/ReSTIR 关闭。PT 复用同场景之前已验证的 65536 spp 未降噪参考。统一 +3EV / ACES fitted / sRGB 显示。</p>
<p>偏移序列为 (0,0),(0,1),(0,0),(0,1),(1,0),(1,1),(1,0),(1,1)，对应 Hammersley(i,8) 量化到 2×2；各相位每周期出现两次。每帧所有块使用同一相位。射线发射位置、重建邻域中心、深度／法线读取均使用同一偏移；采样数量不变。</p>
<table><tr><th>方案</th><th>MSE</th><th>HDR-FLIP</th><th>GPU ms</th><th>末尾8帧时间方差</th></tr>{rows}</table>
<p>偏移相对固定：MSE {result['mse_change_jitter_vs_fixed']:+.2%}，HDR-FLIP {result['flip_change_jitter_vs_fixed']:+.2%}。时间方差来自静态长累积，不代表镜头运动表现；性能为一次 511 区间均值。</p>
<a href="comparison.png"><img src="comparison.png"></a><p>原生 1080p：<a href="fixed.png">固定位置</a> · <a href="jitter.png">按帧偏移</a> · <a href="pt.png">PT</a></p>
<h2>接触阴影与边缘：局部 2× 放大</h2><a href="detail.png"><img src="detail.png"></a>
<h2>短时累积：32 帧</h2><a href="frames-32.png"><img src="frames-32.png"></a>
<p>其他帧数：<a href="frames-1.png">1 帧</a> · <a href="frames-8.png">8 帧</a> · <a href="frames-128.png">128 帧</a>。<a href="summary.json">完整指标及收敛检查数据</a></p>
<p>界面 DDGI → Final gather → Jitter sample position 可选。默认保持固定位置，切换会重置累积。实验仅验证 Accumulate 路径；NRD 的历史投影仍需要单独适配，所以此选项暂不用于 NRD。</p></html>'''
(O/'report.html').write_text(html,encoding='utf-8')
paths=['Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang','Source/RenderPasses/RTXGIDDGI/DDGIReconstruct.cpp','Source/RenderPasses/RTXGIDDGI/DDGIReconstruct.cs.slang','tests/ddgi/half_gather_jitter_comparison.py','tests/ddgi/score_half_gather_jitter.py']
(O/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((R/p).read_bytes()).hexdigest() for p in paths},indent=2))
print(json.dumps(result,indent=2))
