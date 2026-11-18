"""Score native 1080p captures and publish full-size images with matched exposure."""
from pathlib import Path
import sys,json,hashlib,csv,re
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/highres-1080p-split-rerun'
OUT=ROOT/'docs/2026-11-18_DDGI-1080p';OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
def read(tag,channel='Accumulate.output'):
 a=OpenEXR.File(str(DATA/(tag+'.'+channel+'.0.exr'))).channels()['RGB'].pixels.astype(np.float32)
 assert a.shape==(1080,1920,3) and np.isfinite(a).all(),tag
 return np.ascontiguousarray(a)
a,b=read('pt-a-32768'),read('pt-b-32768');ref=np.ascontiguousarray((a+b)*.5)
OpenEXR.File({}, {'RGB':ref}).write(str(DATA/'reference-65536spp.exr'))
mask=np.linalg.norm(read('mask','Visibility.normW'),axis=-1)>.5
np.save(DATA/'surface-mask.npy',mask)
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
reference_noise=mse(a,b)/4
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
error_maps={}
def score(x, name=None):
 err=flip_evaluator.evaluate(ref,x,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 if name is not None:error_maps[name]=err.copy()
 return {'mse':mse(x,ref),'hdr_flip':float(err[mask].mean())}
def display(a):
 x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(x*255+.5))
labels={'ddgi':'Original DDGI + Accumulate','half':'Half FG + Accumulate (960 x 540 rays)',
        'full':'Full FG + Accumulate (1920 x 1080 rays)','pt':'PT reference / 65536 spp / no denoising'}
metrics={};convergence={};timing={};pngs={'pt':display(ref)}
for mode in ['ddgi','half','full']:
 assert info[mode+'_stats']['finite']
 for key in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:assert info[mode+'_stats'][key]==0
 x=read(mode+'-65536');previous=read(mode+'-32768');metrics[mode]=score(x,mode);prevscore=score(previous)
 checkpoints={str(n):mse(read(mode+'-'+str(n)),ref) for n in info['checkpoints']}
 convergence[mode]={'checkpoint_mse':checkpoints,'mse_change':metrics[mode]['mse']/prevscore['mse']-1,
  'flip_change':metrics[mode]['hdr_flip']/prevscore['hdr_flip']-1,'tail_difference_mse':mse(x,previous),
  'estimated_tail_over_error':mse(x,previous)/metrics[mode]['mse']}
 mean=None;m2=None
 for i in range(8):
  v=read(mode+'-stable-'+str(i))[mask].astype(np.float64)
  if mean is None:mean=v.copy();m2=np.zeros_like(mean)
  else:
   delta=v-mean;mean+=delta/(i+1);m2+=delta*(v-mean)
 metrics[mode]['temporal_rgb_variance_8frames']=float(np.mean(m2/8))
 profile=json.loads((DATA/(mode+'-timing.json')).read_text());prefix='/onFrameRender/RenderGraphExe::execute()'
 timing[mode]={'samples':profile['frame_count'],'gpu_frame_ms':profile['events'][prefix+'/gpu_time']['stats']['mean'],
  'passes':{s:profile['events'][prefix+'/'+s+'/gpu_time']['stats']['mean'] for s in ['Visibility','DDGI','Accumulate','Display']+(['Reconstruct'] if mode=='half' else [])}}
 timing[mode]['dispatches']={name:profile['events'][prefix+'/DDGI/'+name+'/gpu_time']['stats']['mean'] for name in ['PrimaryShading']+(['HalfGather'] if mode=='half' else [])}
 pngs[mode]=display(x)
 print(mode,metrics[mode],convergence[mode],flush=True)
for k,img in pngs.items():img.save(OUT/(k+'.png'))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
def panel(keys,images,width,height,columns):
 canvas=Image.new('RGB',(width*columns,(height+52)*((len(keys)+columns-1)//columns)),(23,26,31));draw=ImageDraw.Draw(canvas)
 for i,k in enumerate(keys):
  x=i%columns*width;y=i//columns*(height+52)
  draw.text((x+18,y+10),labels[k],font=font,fill='white');canvas.paste(images[k],(x,y+52))
 return canvas
panel(['ddgi','half','full','pt'],pngs,1920,1080,2).save(OUT/'comparison-4k.png')
panel(['ddgi','half','full'],pngs,1920,1080,3).save(OUT/'comparison-three.png')
# Use the same discrete Magma lookup as Falcor FLIPPass; fixed [0,1] scale.
map_source=(ROOT/'Source/RenderPasses/FLIPPass/flip.hlsli').read_text()
map_body=map_source.split('static const float3 MagmaMap[] = {',1)[1].split('};',1)[0]
magma=np.array([[float(c) for c in v.split(',')] for v in re.findall(r'float3\(([^)]+)\)',map_body)],dtype=np.float32)
assert magma.shape==(256,3)
def colorize(error):
 indices=np.floor(np.clip(error,0,1)*255+.5).astype(np.uint8)
 return np.uint8(np.clip(magma[indices],0,1)*255+.5)
heat_images={}
for mode,err in error_maps.items():
 rgb=colorize(err);rgb[~mask]=(23,26,31)
 heat_images[mode]=Image.fromarray(rgb)
 heat_images[mode].save(OUT/(mode+'-hdr-flip.png'))
 np.save(DATA/(mode+'-hdr-flip.npy'),err)
heat=panel(['ddgi','half','full'],heat_images,1920,1080,3)
legend=Image.new('RGB',(heat.width,heat.height+110),(23,26,31));legend.paste(heat,(0,0))
draw=ImageDraw.Draw(legend);y=heat.height
bar=colorize(np.repeat(np.linspace(0,1,1200,dtype=np.float32)[None,:],28,axis=0))
legend.paste(Image.fromarray(bar),(24,y+40))
draw.text((24,y+4),'HDR-FLIP / Magma [0,1]: dark purple = lower error; red-orange-yellow = higher error. Outside mask = blue-gray.',font=font,fill='white')
for i in range(6):draw.text((24+i*240,y+70),f'{i/5:.1f}',font=font,fill='white')
legend.save(OUT/'errors-hdr-flip.png')
roi=(760,480,1260,980)
crops={k:img.crop(roi).resize((1000,1000),Image.Resampling.NEAREST) for k,img in pngs.items()}
panel(['ddgi','half','full','pt'],crops,1000,1000,2).save(OUT/'detail-2x.png')
checks={'mse_and_flip_change_below_3percent':all(abs(v['mse_change'])<.03 and abs(v['flip_change'])<.03 for v in convergence.values()),
 'estimated_tail_below_5percent':all(v['estimated_tail_over_error']<.05 for v in convergence.values()),
 'reference_noise_below_5percent':reference_noise/min(v['mse'] for v in metrics.values())<.05}
result={'metrics':metrics,'timing':timing,'convergence':convergence,'checks':checks,'reference_noise_mse_estimate':reference_noise,
 'flip_parameters':params,'capture':info,'scene':json.loads((DATA/'scene.json').read_text()),
 'metric_domain':'linear HDR RGB MSE / HDR-FLIP on visible surface mask; final 65536-frame output',
 'variance_definition':'population variance of eight consecutive accumulated outputs after frame 65536; static only',
 'hardware':'RTX 5070 / D3D12','display':'ACES fitted +3EV followed by sRGB; common to every PNG',
 'crop_xyxy':roi,'heatmap':{'metric':'HDR-FLIP','scale':[0,1],'palette':'Magma (Falcor FLIPPass LUT)','outside_mask':'dark blue-gray','normalization':'fixed shared scale, no per-image normalization'}}
(OUT/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
with (OUT/'metrics.csv').open('w',newline='',encoding='utf-8-sig') as f:
 writer=csv.DictWriter(f,fieldnames=['mode','mse','hdr_flip','temporal_rgb_variance_8frames','gpu_frame_ms']);writer.writeheader()
 for k,v in metrics.items():writer.writerow({'mode':k,**v,'gpu_frame_ms':timing[k]['gpu_frame_ms']})
rows=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.5f}</td><td>{v['temporal_rgb_variance_8frames']:.4g}</td><td>{timing[k]['gpu_frame_ms']:.3f}</td></tr>" for k,v in metrics.items())
convrows=''.join(f"<tr><td>{k}</td><td>{v['mse_change']:+.2%}</td><td>{v['flip_change']:+.2%}</td><td>{v['estimated_tail_over_error']:.2%}</td></tr>" for k,v in convergence.items())
stage_rows=''.join('<tr><td>'+stage+'</td>'+''.join('<td>'+ (f"{timing[mode]['passes'][stage]:.3f}" if stage in timing[mode]['passes'] else '—')+'</td>' for mode in ['ddgi','half','full'])+'</tr>' for stage in ['Visibility','DDGI','Reconstruct','Accumulate','Display'])
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>1080p DDGI / Half FG / Full FG</title>
<style>body{{max-width:1500px;margin:32px auto;padding:0 24px;background:#171a20;color:#ddd;font:16px/1.7 system-ui}}img{{max-width:100%}}a{{color:#8dc7ff}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px 12px}}select{{font:inherit}}</style>
<h1>1080p：原始 DDGI、半分辨率 FG、全分辨率 FG</h1>
<p>原生渲染 1920×1080；半分辨率 FG 在 960×540 代表像素上发射射线。Lambert Cornell、顶灯点光源、Test Harness 衰减、黑色环境。三组均先预热 probe 2560 帧，再累积 65536 帧，probe 持续更新，NRD 关闭。PT 为每帧 8 spp、两组独立 32768 spp 的平均，共 65536 spp，未经降噪。所有图片采用相同曝光与色调映射。</p>
<p><a href="comparison-three.png">三组横向原尺寸对比（5760×1132）</a> · <a href="comparison-4k.png">包含 PT 的原尺寸四宫格（3840×2264）</a></p>
<a href="comparison-4k.png"><img src="comparison-4k.png"></a>
<table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>时间方差 ↓</th><th>GPU 帧耗时 ms</th></tr>{rows}</table>
<p>误差统计针对最后一张累积图，在可见表面 mask 内计算；HDR-FLIP 使用 PPD 67 和参考图推导的统一曝光范围。时间方差取随后 8 帧，表示长时间静态平均后的波动，不能代表实时运动表现，也不宜与旧报告 64 帧窗口直接比较。GPU 耗时为 255 个区间的均值，包含 GBuffer、DDGI probe 更新、FG/重建、Accumulate 和显示；不包含漫长收敛过程，不能将展示画质视为单帧效果。</p>
<p><strong>结果：</strong>两种 FG 相对原始 DDGI 的 MSE 均降低约 92%，HDR-FLIP 降低约 60%。在 1080p 下，半／全分辨率已非常接近；半分辨率 MSE 略低约 1%，全分辨率 HDR-FLIP 略低，不能据此断言半分辨率的真实积分更准确，因为重建平滑和有限采样噪声都会影响指标。</p>
<p>本次采用独立半分辨率追踪 dispatch：半分辨率整图 {timing['half']['gpu_frame_ms']:.3f} ms，全分辨率 {timing['full']['gpu_frame_ms']:.3f} ms。半分辨率主表面着色 {timing['half']['dispatches']['PrimaryShading']:.3f} ms，独立 FG 追踪 {timing['half']['dispatches']['HalfGather']:.3f} ms，重建 {timing['half']['passes']['Reconstruct']:.3f} ms。主表面和 FG 是 DDGI pass 内部的 GPU dispatch，不是两个独立 render-graph pass；分项已包含在 DDGI 耗时中，不能重复相加。</p>
<h2>相对 PT Reference 的 HDR-FLIP 误差热力图</h2>
<p>每张图分别比较该方案与同一张未经降噪的 65536 spp PT Reference，显示每个像素的感知误差分布。暗紫黑色接近 0，表示更接近参考；随着误差增大，颜色经过紫、红、橙，到浅黄色（1）。三张图使用完全相同的 [0,1] Magma 彩色色标和 HDR-FLIP 参数，没有各自拉伸对比度；深蓝灰色背景是不参与统计的表面 mask 外区域。</p>
<p>它表征的是“差异”，不是百分比相似度，也不表示方案比参考更亮还是更暗。HDR-FLIP 同时考虑颜色和视觉特征差异；某个像素的值不能直接解释为该像素的亮度差。表中的 HDR-FLIP 是这些误差值在可见表面上的平均值。PT 本身仍有有限采样误差，热力图会包含它的影响。</p>
<a href="errors-hdr-flip.png"><img src="errors-hdr-flip.png" alt="原始 DDGI、Half FG、Full FG 相对 PT 的统一色标 HDR-FLIP 误差图"></a>
<p>原生 1920×1080 误差图：<a href="ddgi-hdr-flip.png">原始 DDGI</a> · <a href="half-hdr-flip.png">Half FG</a> · <a href="full-hdr-flip.png">Full FG</a>。本图使用 Falcor FLIPPass 的 Magma 调色板，仅改变误差的显示颜色，不改变 HDR-FLIP 数值；颜色用于表达误差大小，并非渲染画面本身的亮度。</p>
<h2>各 Render-graph pass 的 GPU 耗时</h2>
<table><tr><th>Pass</th><th>原始 DDGI ms</th><th>Half FG ms</th><th>Full FG ms</th></tr>{stage_rows}</table>
<h2>Pass 组织形式</h2>
<pre>原始 DDGI：Visibility (GBufferRT) → DDGI → Accumulate → Display
全分辨率 FG：Visibility (GBufferRT) → DDGI [含全分辨率 FG] → Accumulate → Display
半分辨率 FG：Visibility (GBufferRT) → DDGI → Reconstruct → Accumulate → Display
PT Reference：Visibility (GBufferRT) → PT (8 spp/frame) → Accumulate → Display</pre>
<table><tr><th>阶段</th><th>分辨率／职责</th></tr>
<tr><td>Visibility</td><td>1920×1080，中心采样，无相机抖动、无 DOF；输出可见性和视线方向，半分辨率路径额外向 Reconstruct 提供全分辨率法线及线性深度。</td></tr>
<tr><td>DDGI：probe 更新</td><td>9×9×9 probes，每 probe 256 rays；更新 irradiance、distance、relocation/classification。三个方案相同，持续更新。</td></tr>
<tr><td>DDGI：PrimaryShading</td><td>1920×1080。原始 DDGI：直接光＋probe 插值；全分辨率 FG：直接光＋逐像素 FG；半分辨率 FG：只计算主表面直接光、发光／背景及重建所需的材质反射率。</td></tr>
<tr><td>DDGI：HalfGather</td><td>仅半分辨率 FG 启用。独立 960×540 ray-generation dispatch，对应固定全分辨率代表像素 (2x,2y)，沿用原 BRDF 采样与随机种子；读取前一 dispatch 的结果前有 UAV 同步。此 Lambert 场景每个有效采样位置最多一根漫反射 FG 射线。</td></tr>
<tr><td>Reconstruct</td><td>仅半分辨率实验图启用。1920×1080 compute，8×8 thread groups；16 邻点深度／法线引导重建，乘回全分辨率反射率并加直接光。未改变滤波规则。</td></tr>
<tr><td>Accumulate</td><td>1920×1080 线性 HDR 逐像素静态平均；预热后清空，再累积 65536 帧。没有重投影；实验镜头固定，autoReset 关闭。</td></tr>
<tr><td>Display</td><td>相同曝光和 ACES 配置。计时包含此 pass；线性 EXR 捕获阶段仅标记 Accumulate.output，发布 PNG 统一使用 ACES fitted +3EV / sRGB。</td></tr></table>
<p>这是本实验使用的固定模式图。交互启动器为了支持动态切换，会始终连接 Reconstruct；在全分辨率下它退化为逐像素合成。没有 NRD、RTXDI 或 ReSTIR；PT 的间接光由路径追踪计算，而 FG 命中点的后续漫反射间接光仍查询 DDGI。</p>
<h2>原生 1080p 图片切换</h2><select onchange="document.getElementById('single').src=this.value"><option value="ddgi.png">原始 DDGI</option><option value="half.png">半分辨率 FG</option><option value="full.png">全分辨率 FG</option><option value="pt.png">PT reference</option></select>
<img id="single" src="ddgi.png"><p>单图：<a href="ddgi.png">DDGI</a> · <a href="half.png">Half FG</a> · <a href="full.png">Full FG</a> · <a href="pt.png">PT</a></p>
<h2>局部 2× 最近邻放大</h2><a href="detail-2x.png"><img src="detail-2x.png"></a>
<h2>收敛检查</h2><table><tr><th>方案</th><th>32768→65536 MSE 变化</th><th>HDR-FLIP 变化</th><th>末次翻倍图像差异 / 相对 PT 误差</th></tr>{convrows}</table>
<p>检查结果：{checks}。PT reference 剩余噪声估计 MSE：{reference_noise:.7g}。这些是有限采样的检查，相关 probe 更新会影响估计，不是无限采样证明。与低分辨率实验不能只比较数值：空间重建覆盖的世界范围和指标的像素尺度均发生变化。</p>
<p><a href="summary.json">完整参数与结果 JSON</a> · <a href="metrics.csv">CSV</a>。原始线性 EXR 位于 build/highres-1080p-split-rerun。</p></html>'''
(OUT/'report.html').write_text(html,encoding='utf-8')
sources=['Source/RenderPasses/FLIPPass/flip.hlsli','tests/ddgi/highres_accumulated_comparison.py','tests/ddgi/score_highres_accumulated_comparison.py','scripts/DDGIAccumulated.py','scripts/PTReference.py','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang','Source/RenderPasses/RTXGIDDGI/DDGIReconstruct.cs.slang']
(OUT/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},indent=2))
print(json.dumps({'checks':checks,'reference_noise':reference_noise}),flush=True)
