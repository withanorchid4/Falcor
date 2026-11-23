from pathlib import Path
import sys,json,hashlib,re
R=Path(__file__).resolve().parents[2];D=R/'build/ddgi-raster-comparison';O=R/'docs/2026-11-23_DDGI光栅化探针更新对比';O.mkdir(exist_ok=True)
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
  t=json.loads((D/(name+'-timing.json')).read_text())['events'];summary[name]['timings'][mode]={k.removeprefix(prefix):v['stats'] for k,v in t.items() if k.startswith(prefix) and k.endswith('/gpu_time')}
 pic(a).save(O/(name+'.png'));heat=np.uint8(colormaps['magma'](f)[:,:,:3]*255);heat[~mask]=[23,26,31];Image.fromarray(heat).save(O/(name+'-flip.png'))
pic(ref).save(O/'pt.png')
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
canvas=Image.new('RGB',(1920,580),(23,26,31));draw=ImageDraw.Draw(canvas)
for j,n in enumerate(['ray','raster']):canvas.paste(pic(arrays[n]).resize((960,540)),(j*960,40));draw.text((j*960+12,5),'Ray visibility' if n=='ray' else 'Raster cubemap / 32 px face',font=font,fill='white')
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
summary['toggle_validation']=json.loads((R/'build/probe-raster-toggle/complete.json').read_text());summary['configuration']=json.loads((D/'complete.json').read_text());summary['raster_vs_ray_mse']=float(np.mean((arrays['raster'][mask].astype('float64')-arrays['ray'][mask])**2))
summary['source_sha256']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [R/'cmake/ddgi-tetrahedral.cmake',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemap.cpp',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemap.3d.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapCommon.slang']};summary['pt_spp']=65536;summary['flip_parameters']=params
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''
for name in ['ray','raster']:
 q=summary[name];t=q['timings']['live'];rows+=f"<tr><td>{name}</td><td>{q['mse']:.8g}</td><td>{q['hdr_flip']:.5f}</td><td>{t['/gpu_time']['mean']:.3f}</td><td>{t['/DDGI/ProbeUpdate/gpu_time']['mean']:.3f}</td><td>{q['relative_tail_rms']*100:.4f}%</td><td>{q['stable']}</td></tr>"
html="""<!doctype html><meta charset="utf-8"><title>DDGI 光栅化探针更新对比</title><style>body{background:#171a1f;color:#eee;font:17px/1.7 sans-serif;max-width:1600px;margin:30px auto;padding:0 20px}img{max-width:100%}td,th{padding:8px;border:1px solid #555}a{color:#9cf}</style><h1>DDGI 光栅化探针更新对比</h1><p>SponzaLambert，1920×1080，RTX 5070、D3D12。默认相机，方向光50、点光关闭。两组均22³官方布局，256个方向样本/probe/次更新，每帧32个probe循环更新（末尾回绕补足预算），hysteresis 0.97，原八点插值、两项数学精简开启，relocation/classification开启。无FG/NRD/ReSTIR。两组各预热65536帧（约197次全网格更新），再清空Accumulate，至少8192帧累积；按翻倍检查，必要时延长至32768帧。参考未经降噪65536 spp PT，主表面位置/法线一致。</p><p>Pass：光追后端 = probe射线可见性＋公共命中着色 → SDK八面体积分/重定位/分类；光栅后端 = 32 probe一批的分层cubemap可见性捕获（每面32²、六面、GS instancing、双面深度、alpha test）→ 按原DDGI方向最近邻读取捕获命中点 → 同一公共命中着色 → 原SDK积分。直接光阴影仍用射线，属于光栅可见性＋光追阴影的混合后端，并不是完整纯光栅GI。像素最终查询与Accumulate均保持原有路径。</p><p>cubemap存几何命中信息，不把整张cubemap每像素都着色；只着色原有256个方向样本。这样保持积分、照明估计器和光照递归一致；采集引入的角度离散、近裁剪与光栅精度差异仍然存在。近裁剪0.0001，远裁剪与原DDGI最大射线距离一致（两倍探针网格包围盒对角线，最小1）。整个cubemap的栅格化已计入GPU耗时。</p><table><tr><th>采集后端</th><th>MSE</th><th>HDR-FLIP</th><th>整图ms</th><th>探针更新ms</th><th>累积翻倍RMS</th><th>稳定</th></tr>"""+rows+"""</table><p>GPU计时为稳定阶段512帧平均；整图包含持续探针更新和显示流程。这里每帧32个probe，不可直接与此前全量更新的帧耗时比较。当前光栅版本为GS实例批处理原型，仍重复处理场景几何，尚无probe专用物体剔除/meshlet筛选；结果不代表光栅化方案的最佳性能上限。</p><img src="comparison.png"><p><a href="ray.png">光追1080p</a> · <a href="raster.png">光栅1080p</a> · <a href="pt.png">PT1080p</a></p><h2>结论与局部检查</h2><p>两组均通过稳定检查且缓存数据全为有限值。光栅MSE高约0.64%，HDR-FLIP低约0.00060，整体画质接近；这些小幅差异不能说明光栅更准确。当前视角未见明显新增的cubemap接缝或大块漏光；两组共同存在相对PT的暗部和接触遮蔽偏差。量化采集会改变薄几何命中及relocation/classification：射线活跃4330、重定位455个，光栅活跃4288、重定位403个。</p><p>当前光栅后端更慢：每帧32probe时，更新由0.100ms增至5.573ms，整图由1.883ms增至7.351ms。主要成本是重复光栅化几何。应保留射线更新默认；本版用于研究对照，若继续优化需重点改进每probe几何剔除、批处理和分辨率调度。</p><p>已验证后端切换会重置历史，并通过16/32/64面分辨率切换与有限值检查。未测试所有相机路径，不能排除运动和极薄几何处的伪影。</p><h2>局部对照（ray / raster / PT）</h2><img src="arch.png"><img src="floor.png"><img src="left.png"><p>以下统一额外提亮3EV检查暗部，不用于指标。</p><img src="floor-boost.png"><h2>HDR-FLIP热力图</h2><p>Magma固定[0,1]：黑紫误差低，橙黄误差高；先ray后raster。</p><img src="ray-flip.png"><img src="raster-flip.png"><p>指标在线性HDR可见表面mask评估，HDR-FLIP使用ACES、PPD67和同一PT曝光范围。</p><p><a href="summary.json">完整数据与配置</a></p>"""
(O/'report.html').write_text(html,encoding='utf-8');print(json.dumps({n:{k:v for k,v in summary[n].items() if k!='timings'} for n in ['ray','raster']},indent=2))
