from pathlib import Path
import sys,json,hashlib,re
R=Path(__file__).resolve().parents[2];D=R/'build/ddgi-tetrahedral';O=R/'docs/2026-11-22_DDGI四探针四面体插值对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'));sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
from matplotlib import colormaps
assert (D/'complete.json').exists() and not (D/'failure.txt').exists()
def read(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels;assert np.isfinite(a).all();return a
ref=read(R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr')
mask=np.linalg.norm(read(D/'eight-8192.Visibility.normW.0.exr'),axis=-1)>.5
assert np.array_equal(read(D/'eight-8192.Visibility.posW.0.exr'),read(D/'four-8192.Visibility.posW.0.exr'))
assert np.array_equal(read(D/'eight-8192.Visibility.normW.0.exr'),read(R/'build/sponza-sun50-20261120/pt-512.Visibility.normW.0.exr'))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
ev=-2.32679
def display(a):
 x=np.maximum(a*2**ev,0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1);return np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
def pic(a):return Image.fromarray(np.uint8(np.clip(display(a)*255+.5,0,255)))
summary={};arrays={};prefix='/onFrameRender/RenderGraphExe::execute()'
for name in ['eight','four']:
 a=read(D/(name+'-8192.Accumulate.output.0.exr'));b=read(D/(name+'-4096.Accumulate.output.0.exr'));arrays[name]=a
 f=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 delta=np.abs(display(a)[mask]-display(b)[mask])*255
 rel=float(np.sqrt(np.mean((a[mask].astype('float64')-b[mask])**2)/np.mean(a[mask].astype('float64')**2)))
 summary[name]={'mse':float(np.mean((a[mask].astype('float64')-ref[mask])**2)),'hdr_flip':float(f[mask].mean()),'relative_tail_rms':rel,'display_tail_mean_levels':float(delta.mean()),'display_tail_p99_levels':float(np.percentile(delta,99)),'stable':bool(rel<.001 and delta.mean()<.25 and np.percentile(delta,99)<2),'timings':{}}
 for mode in ['live','frozen']:
  t=json.loads((D/(name+'-'+mode+'-timing.json')).read_text())['events'];summary[name]['timings'][mode]={k.removeprefix(prefix):v['stats'] for k,v in t.items() if k.startswith(prefix) and k.endswith('/gpu_time')}
 pic(a).save(O/(name+'.png'));heat=np.uint8(colormaps['magma'](f)[:,:,:3]*255);heat[~mask]=[23,26,31];Image.fromarray(heat).save(O/(name+'-flip.png'))
pic(ref).save(O/'pt.png')
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
canvas=Image.new('RGB',(1920,580),(23,26,31));draw=ImageDraw.Draw(canvas)
for j,n in enumerate(['eight','four']):canvas.paste(pic(arrays[n]).resize((960,540)),(j*960,40));draw.text((j*960+12,5),'8 probes' if n=='eight' else '4 probes / tetrahedral',font=font,fill='white')
canvas.save(O/'comparison.png')
# Identical exposure for crops, focus on arch/column contacts and floor grid boundaries.
for label,box in [('arch',(1050,80,1800,650)),('floor',(550,650,1350,1080)),('left',(30,200,650,850))]:
 c=Image.new('RGB',((box[2]-box[0])*3,box[3]-box[1]+40),(23,26,31));dr=ImageDraw.Draw(c)
 for j,n in enumerate(['eight','four','pt']):
  a=ref if n=='pt' else arrays[n];c.paste(pic(a).crop(box),(j*(box[2]-box[0]),40));dr.text((j*(box[2]-box[0])+8,4),n,font=font,fill='white')
 c.save(O/(label+'.png'))
# Boost all three images equally for indirect-light artifact inspection.
ev += 3
c=Image.new('RGB',(2400,470),(23,26,31));dr=ImageDraw.Draw(c)
for j,n in enumerate(['eight','four','pt']):
 a=ref if n=='pt' else arrays[n];c.paste(pic(a).crop((550,650,1350,1080)),(j*800,40));dr.text((j*800+8,4),n+' / +3 EV',font=font,fill='white')
c.save(O/'floor-boost.png')
ev -= 3
summary['configuration']=json.loads((D/'complete.json').read_text());summary['four_vs_eight_mse']=float(np.mean((arrays['four'][mask].astype('float64')-arrays['eight'][mask])**2))
summary['toggle_check']=json.loads((D/'toggle-check.json').read_text());summary['source_sha256']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [R/'cmake/ddgi-tetrahedral.cmake',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang']};summary['pt_spp']=65536;summary['flip_parameters']=params
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''.join(f"<tr><td>{n}</td><td>{s['mse']:.8g}</td><td>{s['hdr_flip']:.5f}</td><td>{s['timings']['live']['/gpu_time']['mean']:.3f}</td><td>{s['timings']['live']['/DDGI/PrimaryShading/gpu_time']['mean']:.3f}</td><td>{s['timings']['frozen']['/DDGI/PrimaryShading/gpu_time']['mean']:.3f}</td><td>{s['relative_tail_rms']*100:.4f}%</td></tr>" for n,s in summary.items() if n in ['eight','four'])
html='''<!doctype html><meta charset="utf-8"><title>DDGI 四探针插值对比</title><style>body{background:#171a1f;color:#eee;font:17px/1.7 sans-serif;max-width:1600px;margin:30px auto;padding:0 20px}img{max-width:100%}td,th{padding:8px;border:1px solid #555}a{color:#9cf}</style><h1>DDGI 四探针四面体插值对比</h1><p>SponzaLambert，1920×1080，RTX 5070、D3D12。默认相机，方向光50，点光关闭。原生DDGI像素查询，无Final Gather/NRD/ReSTIR。沿用官方Sponza探针布局22³，每probe 256条射线，全量更新，relocation/classification开启。两种插值分别预热8192帧，再清空Accumulate并累积8192帧。参考未经降噪65536 spp PT；相机/主表面法线逐像素校验相同。每组正常更新、冻结更新各计时512帧。</p><p>4点从原单元8个角点中选取包含查询点的四面体：立方体沿000→111对角线分为6份，根据bias后坐标排序选取四角。保留SDK方向、深度矩可见性和irradiance编码/解码。选择与重心权重按未relocate网格计算，可见性使用relocate后的实际探针位置。零权重不加下限，避免共享面额外贡献。所有DDGI缓存查询均使用所选模式，包括probe更新的递归间接光，因此本实验是完整路径对照。</p><table><tr><th>模式</th><th>MSE</th><th>HDR-FLIP</th><th>整图ms</th><th>主着色ms</th><th>冻结主着色ms</th><th>累积翻倍变化RMS</th></tr>'''+rows+'''</table><p>主着色包含直接光和阴影射线，并非纯probe插值耗时；冻结探针仍保留主着色。RMS比较4096→8192帧，用于检验稳定性，不等同正确性。指标在线性HDR可见表面mask上求值，FLIP使用ACES、PPD67及相同PT曝光范围。</p><img src="comparison.png"><p><a href="eight.png">8点1080p</a> · <a href="four.png">4点1080p</a> · <a href="pt.png">PT1080p</a></p><h2>观察与限制</h2><p>当前静态视角中，4点没有出现明显新增的硬边接缝或大块漏光，但暗部地面与墙脚局部的亮度分布有所改变，整体误差略增。两种模式仍保留相对PT的暗部/接触遮蔽偏差，4点并不改善这些问题。不能据单个静态相机排除所有方向性伪影或运动时的梯度变化。</p><p>整图加速不仅来自像素主着色：probe追踪命中点的递归间接光也查询相同插值，因此更新部分也受益。冻结主着色包含直接光与阴影射线，不能称为纯插值成本。</p><h2>局部检查（8点 / 4点 / PT）</h2><img src="arch.png"><img src="floor.png"><img src="left.png"><h2>暗部放大检查</h2><p>以下三图统一额外提亮3EV，仅用于检查伪影，不参与指标计算。</p><img src="floor-boost.png"><h2>HDR-FLIP热力图</h2><p>Magma固定[0,1]，黑紫误差低，橙黄误差高。8点在前，4点在后；mask外深灰。</p><img src="eight-flip.png"><img src="four-flip.png"><p><a href="summary.json">完整数据与配置</a></p>'''
(O/'report.html').write_text(html,encoding='utf-8');print(json.dumps({n:summary[n] for n in ['eight','four']},ensure_ascii=False,indent=2))
