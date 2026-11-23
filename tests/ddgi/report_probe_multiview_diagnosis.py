from pathlib import Path
import json,statistics,sys,hashlib
R=Path(__file__).resolve().parents[2];D=R/'build/probe-multiview-diagnosis-routed';O=R/'docs/2026-11-23_DDGI多视图瓶颈排查';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
assert (D/'complete.json').exists() and not (D/'failure.txt').exists()
data=json.loads((D/'complete.json').read_text())
def load_run(r):
 e=json.loads((D/r['file']).read_text())['events'];result={}
 for suffix,label in [('gpu_time','gpu'),('cpu_time','cpu')]:
  result[label]={k.split('/')[-2]:statistics.mean(v['records'][4:]) for k,v in e.items() if k.endswith('/'+suffix) and any(k.endswith('/'+s+'/'+suffix) for s in ['RenderGraphExe::execute()','RasterVisibility','ProbeUpdate','RasterProbeCapture','CullCaptureDraws'])}
 return {k:v for k,v in r.items() if k not in ['file','stats']}|result
runs=[load_run(r) for r in data['runs']];live=[load_run(r) for r in data['normal1024']]
def avg(rows,key):return {k:statistics.mean(r[key][k] for r in rows) for k in rows[0][key]}
groups=[]
for mode,div in [(0,1),(1,1),(2,1),(3,1),(4,1),(5,1),(3,2),(3,4),(3,0)]:
 for mv in [False,True]:
  rows=[r for r in runs if r['mode']==mode and r['triangleDivisor']==div and r['multiview']==mv]
  groups.append({'mode':mode,'divisor':div,'multiview':mv,'gpu':avg(rows,'gpu'),'cpu':avg(rows,'cpu'),'pipeline':avg(rows,'pipeline'),'count':len(rows),'graphicsClockMHz':[min(c['graphics'] for r in rows for c in r['clocks']),max(c['graphics'] for r in rows for c in r['clocks'])]})
def group(mode,div=1,mv=False):return next(g for g in groups if g['mode']==mode and g['divisor']==div and g['multiview']==mv)
liveGroups=[{'multiview':mv,'gpu':avg([r for r in live if r['multiview']==mv],'gpu'),'cpu':avg([r for r in live if r['multiview']==mv],'cpu')} for mv in [False,True]]
validation=json.loads((D/'validation.json').read_text());validationSummary={}
for across in [False,True]:
 rows=[r for r in validation if r['across']==across];validationSummary[str(across)]={k:sum(r['stats'][k] for r in rows) for k in ['referencePixels','missingCapturePixels','extraCapturePixels','capturePositionMismatch','captureNonFinite']};validationSummary[str(across)]['batches']=len(rows)
summary={'groups':groups,'live1024':liveGroups,'validation':validationSummary,'runs':runs,'liveRuns':live,'source_sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [R/'Source/Falcor/Core/API/Device.cpp',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemap.cpp',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapIndirect.3d.slang',R/'Source/RenderPasses/RTXGIDDGI/ProbeCubemapCull.cs.slang',R/'tests/ddgi/probe_multiview_diagnosis.py']}}
(O/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
fig,axes=plt.subplots(1,3,figsize=(16,4.7),layout='constrained')
for j,(mv,label,color) in enumerate([(False,'Per face','#e98a3b'),(True,'Native multiview','#4085cf')]):
 p=group(0,mv=mv)['pipeline'];axes[0].bar([i+(j-.5)*.35 for i in range(3)],[p[k]/1e6 for k in ['IAPrimitives','VSInvocations','CInvocations']],width=.35,label=label,color=color)
 modes=[(0,1),(1,1),(2,1),(3,1),(4,1)]
 axes[1].bar([i+(j-.5)*.35 for i in range(5)],[group(m,d,mv)['gpu']['RasterVisibility'] for m,d in modes],width=.35,color=color)
 xs=[0,.25,.5,1.];axes[2].plot(xs,[group(3,d,mv)['gpu']['RasterVisibility'] for d in [0,4,2,1]],'-o',label=label,color=color)
axes[0].set_xticks(range(3),['IA primitives','VS invocations','CInvocations'],rotation=15);axes[0].set(ylabel='D3D12 counter / million',title='Same output views, less IA / VS work');axes[0].legend()
axes[1].set_xticks(range(5),['Normal','Minimal PS','Full VS\nclip all','Tiny VS\nclip all','No POSITION\nclip all'],rotation=15);axes[1].set(ylabel='Capture visibility GPU ms',title='Stage ablations / 32 probes')
axes[2].set(xlabel='Submitted triangle fraction',ylabel='Capture visibility GPU ms',title='Tiny VS + all clipped, fixed draw count');axes[2].legend()
for ax in axes:ax.grid(axis='y',alpha=.25)
fig.savefig(O/'diagnosis.png',dpi=150);plt.close(fig)
a=group(0,mv=False);b=group(0,mv=True)
labels={'IAVertices':'IA顶点计数','IAPrimitives':'IA三角形计数','VSInvocations':'VS调用计数','CInvocations':'送入光栅器的primitive计数','CPrimitives':'裁剪后的primitive计数','PSInvocations':'PS调用计数'}
counterRows=''.join(f"<tr><td>{label}</td><td>{a['pipeline'][k]:,.0f}</td><td>{b['pipeline'][k]:,.0f}</td><td>{(b['pipeline'][k]/a['pipeline'][k]-1)*100:+.2f}%</td></tr>" for k,label in labels.items())
modeLabels=[(0,1,'正常几何捕获'),(1,1,'省略PS材质/alpha计算'),(2,1,'完整VS，强制全部裁剪'),(3,1,'极简VS，强制全部裁剪'),(4,1,'极简VS，不输入POSITION流，全裁剪'),(5,1,'校准：相同投影、不读取SV_ViewID，全裁剪'),(3,2,'极简VS，全裁剪，1/2三角形'),(3,4,'极简VS，全裁剪，1/4三角形'),(3,0,'空绘制列表')]
modeRows=''.join(f"<tr><td>{label}</td><td>{group(m,d,False)['gpu']['RasterVisibility']:.4f}</td><td>{group(m,d,True)['gpu']['RasterVisibility']:.4f}</td></tr>" for m,d,label in modeLabels)
liveRows=''.join(f"<tr><td>{'硬件多视图' if r['multiview'] else '原逐面'}</td><td>{r['gpu']['RenderGraphExe::execute()']:.3f}</td><td>{r['gpu']['ProbeUpdate']:.3f}</td><td>{r['gpu']['RasterVisibility']:.3f}</td><td>{r['cpu']['RenderGraphExe::execute()']:.3f}</td></tr>" for r in liveGroups)
v=validationSummary['False'];base=liveGroups[0]['gpu']['RenderGraphExe::execute()'];mvtime=liveGroups[1]['gpu']['RenderGraphExe::execute()'];change=(mvtime/base-1)*100
body=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI多视图瓶颈排查</title><style>body{{background:#171a1f;color:#eee;font:17px/1.75 system-ui;max-width:1500px;margin:32px auto;padding:0 24px}}img{{max-width:100%}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px 12px;border-bottom:1px solid #555;text-align:left}}a{{color:#9cf}}code{{background:#28313c;padding:2px 5px}}</style>
<h1>DDGI多视图为什么没有明显收益</h1>
<p><b>结论：没有发现多视图未真正启用、漏视图或硬件mask未生效的错误；证据主要指向逐视图的大量几何处理吞吐，而非顶点shader中的变换计算、顶点位置流读取或像素材质计算。</b>同时发现并修正了一处不必要的视图依赖：纹理层偏移改由PSO静态设置，VS只输出与视图无关的层基址。修订后1024预算整图耗时变化 {change:+.2f}%，仍不构成明显改善。</p>
<h2>原生管线统计证实共享生效</h2><p>以下为32个probe、3个固定位置（cursor0/5000/10000）、每位置ABBA两次各模式的均值。原生D3D12_QUERY_DATA_PIPELINE_STATISTICS仅在独立诊断帧启用，计时期间关闭查询。</p>
<table><tr><th>计数/每32probe</th><th>原逐面</th><th>原生三视图</th><th>变化</th></tr>{counterRows}</table>
<p>IA及VS计数下降说明确实在共享源几何处理，GS计数为0；不是退回了旧GS或逐视图重放所有输入。送入光栅器的逻辑primitive数量仍接近不变：真实cubemap的各面投影不同，每个视角仍要处理其几何。注意：<a href="https://learn.microsoft.com/en-us/windows/win32/api/d3d12/ns-d3d12-d3d12_query_data_pipeline_statistics">CInvocations官方定义</a>是送入光栅器的primitive数，不是硬件裁剪周期；VS调用数下降也不等于同样比例的ALU时间下降。不能只凭这些计数指定某一个硬件单元为唯一瓶颈。</p>
<img src="diagnosis.png">
<h2>消融测试</h2><table><tr><th>诊断条件</th><th>原逐面GPU ms</th><th>多视图GPU ms</th></tr>{modeRows}</table>
<p>简化PS几乎不改变耗时；即使使用极简VS、完全不输入顶点POSITION流，且全部primitive在裁剪中丢弃，仍保留明显成本。另一方面，保持绘制命令数量不变、只削减三角形数量时，耗时接近线性减少。这些结果共同支持输入primitive处理/组装、逐视图几何扩展和光栅器前端等吞吐成本占主导，而非VS矩阵计算或PS材质计算占主导。精确区分这些微架构单元仍需要Nsight GPU Trace等硬件性能分析；本机没有安装该工具。</p>
<p>“全部裁剪”会改变管线行为，因此这些耗时差不能直接相减当作各阶段独立耗时。省略alpha会改变遮挡，也只是诊断。空列表只检验固定API/7个mask桶的开销；它不单独测量每条非空draw命令解释成本，但1/2、1/4三角形测试保留了原有draw命令数。诊断几何输出不能作为画质结果。</p>
<p>校准模式5从VS签名中完全去掉SV_ViewID，将组内视图设为同一投影，并强制全裁剪。它只用于观察减少视图相关计算的影响，不能用于正常cubemap。不同模式的CInvocations仍可能按逻辑view统计；这里没有把它解释为真实硬件裁剪被重复执行的次数。正常模式的投影保持各面真实方向。</p>
<h2>接入方式核查与修订</h2><p>RTX5070为Tier3；原生PSO创建包含3个视图，开启ViewInstanceMasking，按可见性mask生成7组16/32位索引列表，绘制前设置原生SetViewInstanceMask。两个分组布局都经捕获校验：同probe的三面PSO层偏移为0/1/2；相邻三probe同朝向面为0/6/12。VS输出公共层基址，不再逐视图输出层偏移。这样删除了一个不必要的SV_ViewID依赖；SV_Position仍必须依赖视图。</p>
<p><a href="https://microsoft.github.io/DirectX-Specs/d3d/ViewInstancing.html">微软规范</a>明确：Tier3在首次引用SV_ViewID的阶段开始视图实例化；视图相关输出也会按视图数计入输出预算。这里真实投影在VS依赖SV_ViewID，所以不能假定“整个VS只跑一次，后面所有几何工作也都只跑一次”。PSO静态层路由减少了不必要的输出依赖，但没有改变逐视角实际几何量。</p>
<p>同probe分组逐批验证全部10648个probe，共333批：缺失像素 {v['missingCapturePixels']}、额外像素 {v['extraCapturePixels']}、非有限值 {v['captureNonFinite']}。与旧GS命中点差超过1mm的像素 {v['capturePositionMismatch']:,} 个，包含不同三角形取胜的边界差异，故不宣称逐位相同。跨probe分组另验证3批，同样未检出新增缺失像素。</p>
<h2>重新确认每帧1024probe的正常运行</h2><table><tr><th>方案</th><th>完整图GPU ms</th><th>Probe更新GPU ms</th><th>几何捕获GPU ms</th><th>完整图CPU ms</th></tr>{liveRows}</table>
<p>此表使用生产shader：诊断分支在编译时移除，不采集管线统计，不复制诊断参考纹理，不删三角形。持续更新1024 probe/帧且Accumulate开启；相同进程与场景按ABBA预热32帧、计时128帧，去掉前4条Profiler记录，两轮等权平均。默认仍关闭硬件多视图。下一步应优先减少无用几何，例如meshlet级保守视锥剔除或适合probe捕获的LOD，而不是继续期待单纯多视图共享解决全部成本。</p>
<h2>复现条件与测量边界</h2><p>SponzaLambert、默认相机、方向光50、点光关闭、1920×1080、RTX5070/D3D12。22³官方probe布局，256方向/probe，32²六面cubemap、原八点查询。诊断先用射线全量更新512帧，随后冻结同一probe场和位置，以单批32probe隔离绘制；所有模式保留后续真实命中着色：正常模式保存命中纹理，消融模式在几何计时区间外恢复它。避免缺少后续光照工作和资源转换混入对照。</p>
<p>每次计时前用原生查询提交并等待GPU完成预热，NVML确认GPU已升频；期间不采集查询，不调用NVML。计时后另取查询帧及时钟快照。表格为3个位置、每位置每模式两次共6次的均值；各次128帧，去掉前4条记录。不同位置工作量不同，因此不把跨位置方差解释为统计置信区间。</p>
<p>新增的probeCaptureDiagnosticMode、probeCapturePipelineStats、probeCaptureDiagnosticRestore和probeCaptureTriangleDivisor都仅用于诊断，默认关闭/1。消融需要captureOnly及optimized capture，防止污染正常GI。正常shader不含动态诊断分支。此次不重新测完整画质指标，之前稳定画质报告保留；本轮路由变更经全probe几何校验。</p>
<p><a href="summary.json">全部计数、耗时、时钟和源码哈希</a>。脚本：tests/ddgi/probe_multiview_diagnosis.py、report_probe_multiview_diagnosis.py。<a href="../2026-11-23_DDGI硬件多视图捕获对比/report.html">上一轮画质与耗时报告</a>。</p></html>'''
(O/'report.html').write_text(body,encoding='utf-8')
print(json.dumps({'live1024':liveGroups,'normalCounters':{'baseline':a['pipeline'],'multiview':b['pipeline']},'validation':validationSummary},indent=2))
