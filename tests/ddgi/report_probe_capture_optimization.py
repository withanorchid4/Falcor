from pathlib import Path
import json,statistics,sys,html
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
O=R/'docs/2026-11-23_DDGI光栅捕获批处理优化';O.mkdir(exist_ok=True)
A=R/'build/probe-capture-optimization';B=R/'build/probe-capture-validation'
a=json.loads((A/'complete.json').read_text());b=json.loads((B/'complete.json').read_text())
def timings(root,rows):
 out=[]
 for r in rows:
  events=json.loads((root/r['file']).read_text())['events']
  t={k.split('/')[-2]:statistics.mean(v['records'][4:]) for k,v in events.items() if k.endswith('/gpu_time') and any(k.endswith('/'+s+'/gpu_time') for s in ['RenderGraphExe::execute()','ProbeUpdate','RasterProbeCapture','RasterVisibility','CullCaptureDraws','CapturedSampleShading','SDKUpdate'])}
  out.append({**{k:v for k,v in r.items() if k not in ['stats','file']},'ms':t})
 return out
fixed=timings(A,a['timings']);normal=timings(B,b['normalTimings'])
def means(rows):return {k:statistics.mean(r['ms'].get(k,0) for r in rows) for k in sorted(set(k for r in rows for k in r['ms']))}
groups=[{'size':size,'optimized':opt,'ms':means([r for r in fixed if r['size']==size and r['optimized']==opt])} for size in [16,32,64] for opt in [False,True]]
norm=[{'optimized':opt,'ms':means([r for r in normal if r['optimized']==opt])} for opt in [False,True]]
valid=b['validation'];keys=['referencePixels','missingCapturePixels','extraCapturePixels','capturePositionMismatch','captureNonFinite','captureMaterialMismatch','captureSameTrianglePositionMismatch','visibleMeshViews','candidateMeshViews']
v={k:sum(x['stats'].get(k,0) for x in valid) for k in keys};v['maxPositionError']=max(x['stats']['captureMaxPositionError'] for x in valid);v['batches']=len(valid);v['probes']=10648;v['texels']=10648*6*32*32
summary={'fixedFieldTimings':groups,'normalUpdateTimings':norm,'validation':v,'normalStats':b['normalTimings'][-1]['stats'],'fixedRuns':fixed,'normalRuns':normal}
(O/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
(O/'validation.json').write_text(json.dumps(valid,indent=2),encoding='utf-8')
fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
for opt,label,color in [(False,'Original GS','#e78337'),(True,'Culled VS/PS','#387ac2')]:
 rows=[x for x in groups if x['optimized']==opt];axes[0].plot([x['size'] for x in rows],[x['ms']['RasterProbeCapture'] for x in rows],'-o',label=label,color=color)
axes[0].set(xlabel='Cubemap face width',ylabel='GPU milliseconds',title='Capture + shared sample shading (32 probes)');axes[0].legend();axes[0].grid(alpha=.25)
for i,s in enumerate(['RasterVisibility','CullCaptureDraws','CapturedSampleShading','SDKUpdate','RenderGraphExe::execute()']):
 for j,(row,color) in enumerate(zip(norm,['#e78337','#387ac2'])):axes[1].bar(i+(j-.5)*.35,row['ms'].get(s,0),width=.35,color=color)
axes[1].set_xticks(range(5),['Visibility','Cull','Shading','SDK','Whole graph'],rotation=20);axes[1].set(ylabel='GPU milliseconds',title='Normal rolling updates (32 probes/frame)');axes[1].grid(axis='y',alpha=.25)
fig.savefig(O/'timings.png',dpi=160);plt.close(fig)
rows=''.join('<tr><td>%s</td><td>%.3f</td><td>%.3f</td><td>%.1f%%</td></tr>'%(s,norm[0]['ms'].get(k,0),norm[1]['ms'].get(k,0),100*(1-norm[1]['ms'].get(k,0)/norm[0]['ms'][k]) if norm[0]['ms'].get(k,0)>0 else 0) for s,k in [('几何捕获','RasterVisibility'),('probe更新整体','ProbeUpdate'),('完整RenderGraph','RenderGraphExe::execute()')])
resrows=''.join('<tr><td>%s² × 6</td><td>%.3f</td><td>%.3f</td></tr>'%(size,next(x['ms']['RasterProbeCapture'] for x in groups if x['size']==size and not x['optimized']),next(x['ms']['RasterProbeCapture'] for x in groups if x['size']==size and x['optimized'])) for size in [16,32,64])
old=norm[0]['ms']['RenderGraphExe::execute()'];new=norm[1]['ms']['RenderGraphExe::execute()']
text=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI光栅捕获批处理优化</title><style>body{{background:#181b20;color:#e9edf2;font:16px/1.75 system-ui;margin:32px auto;max-width:1120px;padding:0 24px}}h1,h2{{line-height:1.3}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px 15px;border-bottom:1px solid #47515b}}a{{color:#8fcbff}}img{{max-width:100%}}code{{background:#283039;padding:2px 5px}}</style>
<h1>DDGI光栅捕获：批处理与几何剔除优化</h1>
<p>在SponzaLambert、1080p、方向光50、每帧32个probe、每probe256个DDGI方向、cubemap每面32²下，完整图耗时从 <b>{old:.3f} ms 降到 {new:.3f} ms</b>，减少 {(1-new/old)*100:.1f}%。原射线更新仍保留为默认后端；光栅模式下默认启用新的捕获优化。</p>
<h2>为什么原版慢</h2><p>原版把全场景三角形交给32个GS实例，每个实例再检查6个面。三角形的粗剔除已经发生在大量GS工作之后。光栅还必须处理场景几何与六面覆盖；射线后端只查询256个方向，并利用BVH跳过无关几何。减少cubemap像素不能消除这部分开销。</p>
<p>新的组织：GPU计算可见的“mesh实例 × probe面” → 分别生成16/32位索引的间接绘制列表 → 普通VS/PS直接写192层纹理 → 按原DDGI方向读取命中并执行原有着色 → SDK更新八面体贴图 → 屏幕查询 → Accumulate → Display。没有GS几何放大。物体世界包围盒进行保守六平面测试；动态、蒙皮、顶点动画物体不做包围盒剔除，无索引场景回退原路径。尚未做meshlet或遮挡剔除。</p>
<h2>与three.js的对照</h2><p>核对源码版本 <code>6c19b945079a46c1dfbacece38ae4c288364dabc</code>：<a href="https://github.com/mrdoob/three.js/blob/6c19b945079a46c1dfbacece38ae4c288364dabc/examples/jsm/lighting/LightProbeGrid.js">LightProbeGrid</a>每批8个probe，用48个子相机的ArrayCamera和2D atlas组织捕获；<a href="https://github.com/mrdoob/three.js/blob/6c19b945079a46c1dfbacece38ae4c288364dabc/src/renderers/common/Renderer.js">Renderer</a>用FrustumArray做物体级联合视锥剔除。<a href="https://github.com/mrdoob/three.js/blob/6c19b945079a46c1dfbacece38ae4c288364dabc/src/renderers/webgpu/WebGPUBackend.js">WebGPUBackend</a>逐子相机设置viewport并绘制；这一版本的循环只有layers测试，未见逐子相机的物体视锥测试。不能把“一次render调用”理解成只绘制一次几何。我们的方案参考其批量组织，额外实现了每个probe面的GPU剔除。</p>
<h2>分辨率与实测</h2><p>当前cubemap为32² × 6＝6144像素/probe，用于捕获几何；DDGI irradiance八面体有效区域6²（含边框8²），distance有效区域14²（含边框16²），用于存储滤波后的结果。角色不同，不能直接视为相同分辨率。捕获后仍只着色原有256个DDGI方向，未给6144个像素全部计算radiance；直接光阴影仍使用光追。</p>
<table><tr><th>正常轮转，GPU ms</th><th>旧GS</th><th>新剔除＋VS/PS</th><th>减少</th></tr>{rows}</table>
<img src="timings.png" alt="分辨率与正常更新耗时">
<table><tr><th>每probe捕获像素</th><th>旧捕获＋样本着色 ms</th><th>新捕获＋样本着色 ms</th></tr>{resrows}</table>
<p>分辨率消融固定probe场和起始位置0/5000/10000，每个位置按ABBA顺序测4次，每次预热64帧、记录256帧；这里冻结SDK更新以隔离捕获。正常轮转测试恢复SDK更新、每帧32probe，ABBA各记录1024帧、起始cursor一致。Profiler记录去掉前4条后求均值，再对各轮等权平均。GPU为RTX5070；其他程序不争用GPU。统计读回、校验pass均不计入测量。正常计时不是新的一轮画质收敛实验。</p>
<h2>剔除是否漏画</h2><p>先以全量射线更新4096帧得到相同的probe位置，再冻结probe场，逐批遍历全部10648个probe，对32²六面逐像素比较新旧几何命中。共比较 {v['texels']:,} 个像素，其中旧版命中 {v['referencePixels']:,} 个。新版少画 {v['missingCapturePixels']:,}、多画 {v['extraCapturePixels']:,}、非有限结果 {v['captureNonFinite']:,}。</p>
<p>两边都命中但位置差超过1mm的像素 {v['capturePositionMismatch']:,} 个（占旧版命中 {v['capturePositionMismatch']/v['referencePixels']*100:.5f}%），材质ID不同 {v['captureMaterialMismatch']:,} 个；相同三角形上超过1mm的位置差 {v['captureSameTrianglePositionMismatch']:,} 个，最大位置差 {v['maxPositionError']:.4f} 场景单位。因此不宣称逐位相同。差异出现在不同三角形取胜的像素；绘制顺序改变以及共面/边缘深度竞争是可能原因，尚未逐像素归因。本次验证说明所测静态Sponza下未检出包围盒剔除导致的空洞，不等于已验证所有动态场景或重新测过稳定PT误差。</p>
<p>保留旧模式便于复核：光栅开关 <code>rasterProbeUpdate</code>，新捕获开关 <code>optimizedProbeCapture</code>（默认true，界面Cull objects per probe face），分辨率 <code>probeCubemapSize</code>。八面体存储、SDK积分、probe方向数量、4/8点插值均保持原流程。仍慢于之前约1.88ms的射线图基线；下一步更有价值的是meshlet粒度剔除或更少的捕获面，而非单纯降低贴图分辨率。</p>
<p>复现脚本：<code>tests/ddgi/probe_capture_optimization.py</code>、<code>probe_capture_validation.py</code>。<a href="summary.json">汇总数据</a> · <a href="validation.json">逐批校验数据</a>。原画质报告保留在 <a href="../2026-11-23_DDGI光栅化探针更新对比/report.html">光栅与射线更新对比</a>，没有用本次捕获消融结果替代其收敛指标。</p></html>'''
(O/'report.html').write_text(text,encoding='utf-8');print(json.dumps({'normal':norm,'validation':v},indent=2))
