from pathlib import Path
import json,statistics,sys,hashlib
R=Path(__file__).resolve().parents[2];D=R/'build/ddgi-multiview-1024-comparison';B=R/'build/ddgi-raster-1024-comparison';O=R/'docs/2026-11-23_DDGI硬件多视图捕获对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'));sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
from matplotlib import colormaps
assert (D/'complete.json').exists() and not (D/'failure.txt').exists()
config=json.loads((D/'complete.json').read_text());baseline=json.loads((B/'complete.json').read_text());paired=json.loads((D/'paired.json').read_text());n=config['multiview']['accumulated']
def read(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels;assert np.isfinite(a).all();return a
ref=read(R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr')
mask=np.linalg.norm(read(D/f'multiview-{n}.Visibility.normW.0.exr'),axis=-1)>.5
assert np.array_equal(read(D/f'multiview-{n}.Visibility.posW.0.exr'),read(B/f"raster-{baseline['raster']['accumulated']}.Visibility.posW.0.exr"))
assert np.array_equal(read(D/f'multiview-{n}.Visibility.normW.0.exr'),read(R/'build/sponza-sun50-20261120/pt-512.Visibility.normW.0.exr'))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
arrays={name:read(B/f"{name}-{baseline[name]['accumulated']}.Accumulate.output.0.exr") for name in ['ray','raster']};arrays['multiview']=read(D/f'multiview-{n}.Accumulate.output.0.exr')
def display(a,ev=-2.32679):
 x=np.maximum(a*2**ev,0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1);return np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
def pic(a,ev=-2.32679):return Image.fromarray(np.uint8(np.clip(display(a,ev)*255+.5,0,255)))
quality={}
for name,a in arrays.items():
 f=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 quality[name]={'mse':float(np.mean((a[mask].astype('float64')-ref[mask])**2)),'hdr_flip':float(f[mask].mean())};pic(a).save(O/(name+'.png'))
 heat=np.uint8(colormaps['magma'](f)[:,:,:3]*255);heat[~mask]=[23,26,31];Image.fromarray(heat).save(O/(name+'-flip.png'))
pic(ref).save(O/'pt.png')
quality['multiview_vs_raster_mse']=float(np.mean((arrays['multiview'][mask].astype('float64')-arrays['raster'][mask])**2))
def times(root,rows):
 out=[]
 for row in rows:
  events=json.loads((root/row['file']).read_text())['events'];t={k.split('/')[-2]:statistics.mean(v['records'][4:]) for k,v in events.items() if k.endswith('/gpu_time') and any(k.endswith('/'+s+'/gpu_time') for s in ['RenderGraphExe::execute()','ProbeUpdate','RasterVisibility','CullCaptureDraws','CapturedSampleShading','SDKUpdate'])}
  out.append({k:v for k,v in row.items() if k!='stats'}|{'ms':t})
 return out
runs=times(D,paired);timing={str(mv):{k:statistics.mean(r['ms'].get(k,0) for r in runs if r['multiview']==mv) for k in runs[0]['ms']} for mv in [False,True]}
validation=json.loads((D/'validation.json').read_text());keys=['referencePixels','missingCapturePixels','extraCapturePixels','capturePositionMismatch','captureNonFinite','captureMaterialMismatch','captureSameTrianglePositionMismatch'];valid={k:sum(r['stats'][k] for r in validation) for k in keys};valid['maxPositionError']=max(r['stats']['captureMaxPositionError'] for r in validation)
stability=json.loads((D/'multiview-stability.json').read_text())
exploratory={}
for label,folder in [('sameProbe','probe-multiview-masked-smoke'),('acrossProbes','probe-multiview-across-smoke')]:
 P=R/'build'/folder;c=json.loads((P/'complete.json').read_text());exploratory[label]=times(P,c['timings'])
summary={'quality':quality,'timing':timing,'pairedRuns':runs,'stability':stability,'validation':valid,'configuration':config,'exploratory':exploratory,'flipParameters':params,'source_sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [R/'Source/Falcor/Core/API/Device.cpp',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemap.cpp',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapIndirect.3d.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapCull.cs.slang',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h']}}
(O/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');(O/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
c=Image.new('RGB',(1920,580),(23,26,31));dr=ImageDraw.Draw(c)
for j,name in enumerate(['raster','multiview']):c.paste(pic(arrays[name]).resize((960,540)),(j*960,40));dr.text((j*960+12,5),'Per-face capture' if name=='raster' else 'Hardware multiview / 3 views + native masks',font=font,fill='white')
c.save(O/'comparison.png')
for label,box in [('floor',(550,650,1350,1080)),('arch',(1050,80,1800,650))]:
 w=box[2]-box[0];c=Image.new('RGB',(w*3,box[3]-box[1]+40),(23,26,31));dr=ImageDraw.Draw(c)
 for j,name in enumerate(['raster','multiview','pt']):c.paste(pic(ref if name=='pt' else arrays[name],.67321 if label=='floor' else -2.32679).crop(box),(j*w,40));dr.text((j*w+8,4),name+(' / +3 EV' if label=='floor' else ''),font=font,fill='white')
 c.save(O/(label+'.png'))
rows=''.join(f"<tr><td>{label}</td><td>{quality[name]['mse']:.8g}</td><td>{quality[name]['hdr_flip']:.5f}</td><td>{timing[str(mv)]['RenderGraphExe::execute()']:.3f}</td><td>{timing[str(mv)]['ProbeUpdate']:.3f}</td></tr>" for name,label,mv in [('raster','原逐面光栅捕获',False),('multiview','原生三视图＋硬件mask',True)])
change=(timing['True']['RenderGraphExe::execute()']/timing['False']['RenderGraphExe::execute()']-1)*100
body=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI硬件多视图捕获对比</title><style>body{{background:#171a1f;color:#eee;font:17px/1.75 system-ui;max-width:1500px;margin:32px auto;padding:0 24px}}img{{max-width:100%}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px 12px;border-bottom:1px solid #555;text-align:left}}a{{color:#9cf}}code{{background:#28313c;padding:2px 5px}}</style>
<h1>DDGI硬件多视图捕获：SponzaLambert / 1024 probe每帧</h1>
<p>已接入真正的D3D12 View Instancing。RTX5070实测Tier3；六面分成两组三视图，按可见性mask分组间接绘制，并用原生SetViewInstanceMask关闭不可见视图。<b>本次未获得明显加速</b>：完整图耗时变化 {change:+.2f}%。选项保留，默认关闭；原射线后端和逐面光栅均可用。</p>
<table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>完整图GPU ms</th><th>Probe更新GPU ms</th></tr>{rows}</table>
<p>画质均对照同一个未经降噪65536 spp PT。原逐面光栅的画质图复用上一轮已稳定结果；本轮重新测了两方案的GPU耗时。新多视图从空缓存预热2048帧，再Accumulate {n} 帧，连续两次通过稳定检查。原图两组不是相同随机序列，微小差异不能直接视为系统性画质增益。多视图与原光栅之间的HDR MSE＝{quality['multiview_vs_raster_mse']:.8g}。原射线图先前约2.11ms，仅作背景参考，本轮不重新计时。</p>
<img src="comparison.png"><p><a href="raster.png">原光栅1080p</a> · <a href="multiview.png">多视图1080p</a> · <a href="pt.png">PT1080p</a></p>
<h2>具体接入</h2><p>底层通过Device.cpp的PSO创建dispatcher，在shader显式声明gFalcorViewInstancing3参数块时，使用ID3D12Device2::CreatePipelineState及D3D12_VIEW_INSTANCING_DESC创建三个视图的PSO。SV_ViewID选择投影，VS写入相应纹理层。没有改Slang二进制包。其他shader继续原有PSO创建路径。能力不足的设备/后端自动回退逐面路径。</p>
<p>GPU计算物体包围盒对各面的可见性。三个视图有7种非空可见性mask，分别生成16/32位索引间接绘制列表；CPU在各列表前设置对应硬件mask。这样不可见视图不会仅仅在VS末端裁掉。着色、256方向样本/probe、八面体存储、SDK积分/重定位/分类、屏幕查询和Accumulate都保持同一流程；1024预算也保持不变。</p>
<p>还测试了把相邻三个probe的同朝向面放在一组，使用同样的硬件mask。探索计时中它略慢于原逐面路径；同probe三面的分组基本持平。因此没有自动替换默认路径。硬件多视图允许共享世界空间变换等工作，但每个视角的投影、三角形裁剪及光栅化仍需执行。本次结果表明仅靠这部分共享不足以解决约80ms的捕获开销；尚未用Nsight拆分各硬件阶段，不能仅凭这个计时把全部成本归因于某个单独阶段。</p>
<h2>验证与计时</h2><p>SponzaLambert默认相机，方向光50、点光关闭，1920×1080；官方22³探针布局，256方向/probe，每帧1024个probe轮转、末尾回绕补足预算；cubemap每面32²，relocation/classification开启，hysteresis0.97，八点插值，两项数学优化开启；无FG/NRD/ReSTIR/RTXDI。</p>
<p>在稳定probe位置上冻结SDK更新，遍历全部10648个probe，与旧GS捕获逐像素核对：旧版命中 {valid['referencePixels']:,} 个像素，新版缺失 {valid['missingCapturePixels']:,}、新增 {valid['extraCapturePixels']:,}、非有限值 {valid['captureNonFinite']:,}。位置差超过1mm的命中 {valid['capturePositionMismatch']:,} 个；其中相同三角形上的位置差 {valid['captureSameTrianglePositionMismatch']:,} 个，最大位置差 {valid['maxPositionError']:.4f} 场景单位。不同三角形取胜的边界差异仍存在，不能宣称逐位相同。</p>
<p>画质阶段恢复持续更新1024 probe/帧，清空并开启SingleCompensated Accumulate。最终累积翻倍相对RMS={stability['relative_rms']*100:.4f}%，显示平均变化={stability['mean_display_levels']:.4f}个8位灰阶，99分位={stability['p99_display_levels']:.4f}灰阶。阈值分别为0.1%、0.25和2，连续两次通过。这里稳定指满足画面变化阈值。</p>
<p>计时在同一进程、同一场景、同一图中按原逐面→多视图→多视图→原逐面的ABBA顺序进行，每次预热32帧、记录128帧，去掉Profiler前4条后求均值。两轮等权平均。全部32批捕获、硬件mask列表、SDK更新均计入；计时期间probe持续更新且Accumulate开启。截图、CPU诊断读回、可见性校验不计入。两组GBuffer位置一致，法线与PT一致。MSE在线性HDR可见表面mask上求均值，HDR-FLIP使用官方flip_evaluator、ACES、PPD67和统一曝光范围。</p>
<h2>局部图：原光栅 / 多视图 / PT</h2><p>地面统一提亮3EV检查暗部；拱门使用原曝光。</p><img src="floor.png"><img src="arch.png">
<h2>HDR-FLIP热力图</h2><p>固定Magma[0,1]，黑紫误差小、橙黄误差大；先原逐面、后多视图。非百分比相似度。</p><img src="raster-flip.png"><img src="multiview-flip.png">
<p>开关：DDGI → Raster cubemap probe capture → Cull objects per probe face → Hardware multiview (3 views)。View grouping选择同probe的面或相邻probe同朝向面。默认硬件多视图关闭。脚本：tests/ddgi/probe_multiview_comparison.py、probe_multiview_benchmark.py。<a href="summary.json">指标、逐轮耗时、配置和源码哈希</a> · <a href="validation.json">全probe校验</a>。API参考：<a href="https://microsoft.github.io/DirectX-Specs/d3d/ViewInstancing.html">D3D12 View Instancing规范</a>。</p></html>'''
(O/'report.html').write_text(body,encoding='utf-8');print(json.dumps({'quality':quality,'timing':timing,'changePercent':change,'validation':valid},indent=2))
