from pathlib import Path
import sys,json,hashlib,re,statistics
R=Path(__file__).resolve().parents[2];D=R/'build/ddgi-raster-1024-comparison';O=R/'docs/2026-11-23_Sponza每帧1024探针光栅与射线对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'));sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
from matplotlib import colormaps
config=json.loads((D/'complete.json').read_text())
assert (D/'complete.json').exists() and not (D/'failure.txt').exists()
def read(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels;assert np.isfinite(a).all();return a
ref=read(R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr')
mask=np.linalg.norm(read(D/('ray-'+str(config['ray']['accumulated'])+'.Visibility.normW.0.exr')),axis=-1)>.5
assert np.array_equal(read(D/('ray-'+str(config['ray']['accumulated'])+'.Visibility.posW.0.exr')),read(D/('raster-'+str(config['raster']['accumulated'])+'.Visibility.posW.0.exr')))
assert np.array_equal(read(D/('ray-'+str(config['ray']['accumulated'])+'.Visibility.normW.0.exr')),read(R/'build/sponza-sun50-20261120/pt-512.Visibility.normW.0.exr'))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
ev=-2.32679
def display(a):
 x=np.maximum(a*2**ev,0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1);return np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
def pic(a):return Image.fromarray(np.uint8(np.clip(display(a)*255+.5,0,255)))
summary={};arrays={};prefix='/onFrameRender/RenderGraphExe::execute()'
for name in ['ray','raster']:
 n=config[name]['accumulated'];a=read(D/(name+'-'+str(n)+'.Accumulate.output.0.exr'));b=read(D/(name+'-'+str(n//2)+'.Accumulate.output.0.exr'));arrays[name]=a
 f=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 delta=np.abs(display(a)[mask]-display(b)[mask])*255
 rel=float(np.sqrt(np.mean((a[mask].astype('float64')-b[mask])**2)/np.mean(a[mask].astype('float64')**2)))
 summary[name]={'mse':float(np.mean((a[mask].astype('float64')-ref[mask])**2)),'hdr_flip':float(f[mask].mean()),'relative_tail_rms':rel,'display_tail_mean_levels':float(delta.mean()),'display_tail_p99_levels':float(np.percentile(delta,99)),'stable':bool(rel<.001 and delta.mean()<.25 and np.percentile(delta,99)<2),'timings':{}}
 for mode in ['live']:
  t=json.loads((D/(name+'-timing.json')).read_text())['events'];summary[name]['timings'][mode]={k.removeprefix(prefix):{'mean':statistics.mean(v['records'][4:]),'std_dev':statistics.pstdev(v['records'][4:]),'min':min(v['records'][4:]),'max':max(v['records'][4:])} for k,v in t.items() if k.startswith(prefix) and k.endswith('/gpu_time')}
 pic(a).save(O/(name+'.png'));heat=np.uint8(colormaps['magma'](f)[:,:,:3]*255);heat[~mask]=[23,26,31];Image.fromarray(heat).save(O/(name+'-flip.png'))
pic(ref).save(O/'pt.png')
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
canvas=Image.new('RGB',(1920,580),(23,26,31));draw=ImageDraw.Draw(canvas)
for j,n in enumerate(['ray','raster']):canvas.paste(pic(arrays[n]).resize((960,540)),(j*960,40));draw.text((j*960+12,5),'Ray visibility' if n=='ray' else 'Optimized raster / 32 px face',font=font,fill='white')
canvas.save(O/'comparison.png')
# Identical exposure for crops, focus on arch/column contacts and floor grid boundaries.
for label,box in [('arch',(1050,80,1800,650)),('floor',(550,650,1350,1080)),('left',(30,200,650,850))]:
 c=Image.new('RGB',((box[2]-box[0])*3,box[3]-box[1]+40),(23,26,31));dr=ImageDraw.Draw(c)
 for j,n in enumerate(['ray','raster','pt']):
  a=ref if n=='pt' else arrays[n];c.paste(pic(a).crop(box),(j*(box[2]-box[0]),40));dr.text((j*(box[2]-box[0])+8,4),n,font=font,fill='white')
 c.save(O/(label+'.png'))
# Boost all three images equally for indirect-light artifact inspection.
ev += 3
c=Image.new('RGB',(2400,470),(23,26,31));dr=ImageDraw.Draw(c)
for j,n in enumerate(['ray','raster','pt']):
 a=ref if n=='pt' else arrays[n];c.paste(pic(a).crop((550,650,1350,1080)),(j*800,40));dr.text((j*800+8,4),n+' / +3 EV',font=font,fill='white')
c.save(O/'floor-boost.png')
ev -= 3
summary['configuration']=json.loads((D/'complete.json').read_text());summary['raster_vs_ray_mse']=float(np.mean((arrays['raster'][mask].astype('float64')-arrays['ray'][mask])**2))
summary['source_sha256']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [R/'cmake/ddgi-tetrahedral.cmake',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemap.cpp',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemap.3d.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapCommon.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapCull.cs.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapIndirect.3d.slang',R/'scripts/scenes/SponzaLambert.pyscene',R/'scripts/scenes/Sponza.pyscene',R/'scripts/scenes/sponza_rtxgi.py']};summary['pt_spp']=65536;summary['flip_parameters']=params
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''
for name,label in [('ray','射线更新'),('raster','优化光栅更新')]:
 q=summary[name];t=q['timings']['live'];rows+=f"<tr><td>{label}</td><td>{q['mse']:.8g}</td><td>{q['hdr_flip']:.5f}</td><td>{t['/gpu_time']['mean']:.3f}</td><td>{t['/DDGI/ProbeUpdate/gpu_time']['mean']:.3f}</td><td>{config[name]['accumulated']}</td><td>{q['relative_tail_rms']*100:.4f}%</td></tr>"
a=summary['ray'];b=summary['raster'];speed=b['timings']['live']['/gpu_time']['mean']/a['timings']['live']['/gpu_time']['mean']
checks={n:[json.loads((D/(n+'-stability-'+str(i)+'.json')).read_text()) for i in [256,512,1024,2048,4096,8192] if (D/(n+'-stability-'+str(i)+'.json')).exists()] for n in ['ray','raster']}
(O/'stability.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
# Fixed-scale legend for the two HDR-FLIP maps.
legend=Image.new('RGB',(960,85),(23,26,31));dr=ImageDraw.Draw(legend)
colors=np.uint8(colormaps['magma'](np.linspace(0,1,900))[:,:3]*255);legend.paste(Image.fromarray(np.tile(colors[None,:,:],(18,1,1))),(20,24))
for value in [0,.2,.4,.6,.8,1.]:dr.text((20+int(value*900)-5,45),str(value),font=font,fill='white')
legend.save(O/'flip-legend.png')
body=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Sponza每帧1024探针：优化光栅与射线更新</title><style>body{{background:#171a1f;color:#eee;font:17px/1.75 system-ui;max-width:1500px;margin:32px auto;padding:0 24px}}img{{max-width:100%}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px 12px;border-bottom:1px solid #555;text-align:left}}a{{color:#9cf}}code{{background:#28313c;padding:2px 5px}}</style>
<h1>SponzaLambert：每帧1024 probe的光栅与射线更新对比</h1>
<p>两组均以Accumulate累积，持续更新probe，画面通过连续两次翻倍稳定检查后截图。优化光栅每面32²，开启逐probe面的物体剔除和间接VS/PS绘制。射线后端保持原实现。光栅整图耗时约为射线的 <b>{speed:.1f}倍</b>；本次画质数值见下表，不代表其他视角和分辨率的结论。</p>
<table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>整图GPU ms ↓</th><th>Probe更新GPU ms ↓</th><th>累积帧数</th><th>最终翻倍相对RMS</th></tr>{rows}</table>
<p>光栅相对射线的MSE变化为 {(b['mse']/a['mse']-1)*100:+.2f}%，HDR-FLIP变化为 {b['hdr_flip']-a['hdr_flip']:+.5f}；两种输出之间的线性HDR MSE为 {summary['raster_vs_ray_mse']:.8g}。完整1080p图和局部图如下。热力图均比较同一PT，固定Magma[0,1]，黑紫误差低，橙黄误差高，背景不参与统计。</p>
<img src="comparison.png" alt="左射线更新，右优化光栅更新"><p><a href="ray.png">射线1080p</a> · <a href="raster.png">优化光栅1080p</a> · <a href="pt.png">PT Reference 1080p</a></p>
<p>局部检查：本次静态视角的拱门、柱脚和地面未见明显新增的cubemap接缝或大块漏光；两组相对PT均存在暗部偏暗和局部间接光分布差异。光栅MSE略高、HDR-FLIP略低，这种微小变化不能说明其画质有实质改善。当前逐批重复绘制几何的成本很高，适合保留为实验后端，默认仍建议射线更新。</p><h2>共同测试条件与Pass组织</h2>
<p>RTX5070、D3D12、1920×1080；SponzaLambert默认相机，方向光强度50、点光关闭。22³＝10648个probe，官方Sponza布局，256方向/probe/次，hysteresis 0.97，relocation/classification开启。每帧严格更新1024 probe，末尾回绕补足预算，约10.4帧扫完整个网格。原八点插值，两项数学精简开启；无FG、NRD、ReSTIR和RTXDI。两个后端都保留同一照明、材料、八面体存储与插值实现。</p>
<p>射线：GBuffer → probe射线可见性与公共命中着色 → SDK八面体积分、重定位与分类 → 屏幕probe查询和直接光 → Accumulate → ToneMapper。光栅：GBuffer → 每32 probe一批，GPU包围盒六面剔除、间接VS/PS捕获六面命中 → 原256方向读取命中与公共着色 → 同一SDK更新 → 同一屏幕查询 → Accumulate → ToneMapper。1024个probe共32批，全部捕获、剔除、着色与SDK成本均计入耗时。直接光阴影仍用光追，属于混合后端。</p>
<p>每面32²意味着6144捕获像素/probe，而原射线后端查询256个方向；光栅仍需反复处理场景几何。捕获后只给原256方向着色。不能把两组称为相同可见性采样预算，但probe更新数、着色方向数和存储分辨率相同。</p>
<h2>收敛、参考与计时方法</h2>
<p>两组从空缓存开始，预热2048帧（约197轮网格更新），之后清空并开启Accumulate，使用SingleCompensated精度；期间probe继续更新。256/512/1024等翻倍检查N帧与N/2帧的累积输出。稳定标准：可见表面HDR相对RMS小于0.1%，相同显示变换下平均变化小于0.25个8位灰阶，99分位变化小于2个灰阶；连续两次检查通过才结束。这里的稳定表示在这些阈值下画面不再明显变化，不宣称数学上无限采样收敛。<a href="stability.json">逐次稳定检查</a>。</p>
<p>PT使用已有的同场景、同灯光、同相机、无降噪65536 spp参考；本次未重跑PT。逐像素确认两组GBuffer位置一致，并确认法线与该PT测试一致。MSE在线性HDR RGB上按可见表面mask求均值，HDR-FLIP使用官方flip_evaluator、ACES、PPD67和同一个PT推导的曝光范围。显示图统一曝光，不为各方案单独调亮度。</p>
<p>最终画质图截取后再测GPU时间，先预热32帧，再持续更新1024 probe/帧测256帧。去掉Profiler前4条记录后求均值，计时中Accumulate依然开启。整图包含GBuffer、DDGI、累积和显示；probe更新列包含全部32批捕获/追踪及SDK更新。统计读回与截图不计入。两组依次运行，没有并行争用GPU。数据均为有限值。</p>
<h2>局部对照：射线 / 优化光栅 / PT</h2><img src="arch.png"><img src="floor.png"><img src="left.png"><p>以下三组统一额外提亮3EV，仅检查暗部，不用于指标。</p><img src="floor-boost.png">
<h2>HDR-FLIP热力图</h2><p>先射线、后优化光栅。色标为感知误差，不是百分比相似度。</p><img src="flip-legend.png"><img src="ray-flip.png"><img src="raster-flip.png">
<p><a href="summary.json">完整指标、耗时分解、配置与源码哈希</a>。脚本：<code>tests/ddgi/probe_raster_1024_comparison.py</code>、<code>report_probe_raster_1024.py</code>。前一轮每帧32 probe的剔除优化测试见 <a href="../2026-11-23_DDGI光栅捕获批处理优化/report.html">批处理优化报告</a>，本轮不混用它的耗时。</p></html>'''
(O/'report.html').write_text(body,encoding='utf-8')
print(json.dumps({n:{k:v for k,v in summary[n].items() if k!='timings'} for n in ['ray','raster']},indent=2))
print('whole graph ratio',speed)
