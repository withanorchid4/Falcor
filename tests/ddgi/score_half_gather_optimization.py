"""Compare split dispatch with the saved original implementation."""
from pathlib import Path
import sys,json,hashlib
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/'build/final-gather-python'))
import numpy as np,OpenEXR
D=R/'build/half-gather-optimization';O=R/'docs/2026-11-18_DDGI-half-dispatch-optimization';O.mkdir(exist_ok=True)
result={'resolution':[1920,1080],'rounds':3,'intervals_per_round':511,'timing':{},'image_difference':{},
 'scene':'Lambert Cornell, ceiling point light; same scene and seeds before/after',
 'image_check':'1024 warmup frames, then reset and accumulate 32 frames; linear HDR full-image difference',
 'boundary_check':'481x271: FG on/off, half/full switches, accumulator bypass and history reset passed',
 'notes':'No ReSTIR, NRD, sampling, or reconstruction filter changes. Debug probe/WRC overlays use the original combined dispatch.'}
prefix='/onFrameRender/RenderGraphExe::execute()'
for tag in ['baseline','split']:
 assert json.loads((D/tag/'complete.json').read_text())['passed']
 assert not (D/tag/'failure.txt').exists()
 result['timing'][tag]={}
 for mode in ['ddgi','half','full']:
  rounds=[json.loads((D/tag/(mode+'-'+str(i)+'-timing.json')).read_text()) for i in range(3)]
  assert all(v['frame_count']==511 for v in rounds)
  events=['','/DDGI']+(['/Reconstruct'] if mode=='half' else [])
  if tag=='split':events+=['/DDGI/PrimaryShading']+(['/DDGI/HalfGather'] if mode=='half' else [])
  result['timing'][tag][mode]={}
  for event in events:
   values=[v['events'][prefix+event+'/gpu_time']['stats']['mean'] for v in rounds]
   result['timing'][tag][mode][event or 'total']={'mean_ms':float(np.mean(values)),'round_means_ms':values}
for mode in ['ddgi','half','full']:
 def read(tag):return OpenEXR.File(str(D/tag/(mode+'.Accumulate.output.0.exr'))).channels()['RGB'].pixels
 a,b=read('baseline'),read('split');assert np.isfinite(a).all() and np.isfinite(b).all()
 diff=a.astype(np.float64)-b
 result['image_difference'][mode]={'max_abs':float(np.abs(diff).max()),'mse':float(np.mean(diff*diff))}
 assert result['image_difference'][mode]['max_abs']<1e-6
result['half_total_reduction']=1-result['timing']['split']['half']['total']['mean_ms']/result['timing']['baseline']['half']['total']['mean_ms']
(O/'summary.json').write_text(json.dumps(result,indent=2))
rows=''.join(f"<tr><td>{mode}</td><td>{result['timing']['baseline'][mode]['total']['mean_ms']:.3f}</td><td>{result['timing']['split'][mode]['total']['mean_ms']:.3f}</td><td>{result['image_difference'][mode]['max_abs']:.5g}</td></tr>" for mode in ['ddgi','half','full'])
(O/'report.html').write_text(f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI 半分辨率 dispatch 优化</title>
<style>body{{max-width:1000px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui;background:#171a20;color:#ddd}}td,th{{border:1px solid #555;padding:8px 16px}}table{{border-collapse:collapse}}a{{color:#8dc7ff}}</style>
<h1>半分辨率 Final Gather：独立追踪 dispatch</h1>
<p>半分辨率整图 GPU 耗时降低 {result['half_total_reduction']:.1%}。原来的 1920×1080 混合着色 dispatch 拆为全分辨率主表面着色与 960×540 FG 追踪。保留固定代表像素、随机种子、BRDF 采样、DDGI 命中点着色、16-tap 重建和 Accumulate；未加入 ReSTIR 或 NRD。</p>
<table><tr><th>方案</th><th>修改前 ms</th><th>拆分后 ms</th><th>最大线性 HDR 差值</th></tr>{rows}</table>
<p>RTX 5070 / D3D12，1920×1080，Lambert Cornell 顶灯点光源。每轮 511 个 GPU 区间，三轮交替顺序测量。总时间包含 GBuffer、probe 更新、直接光、FG/重建、累积与显示，不代表单帧就获得收敛画质。图像比较为预热 1024 帧后重置并累积 32 帧；半分辨率浮点误差来自拆分后的加减运算顺序，原始 DDGI 与全分辨率逐像素完全一致。没有重新运行 65536 帧收敛实验。</p>
<p>已通过 481×271 奇数尺寸下 FG 开关、全／半分辨率切换、累积关闭直通和重新开启清空历史测试。调试 probe/WRC 叠加显示保留原来的合并路径。前一轮变慢的四相 dispatch 与 groupshared 重建实验已经回退。</p>
<p><a href="summary.json">分阶段计时、每轮数据与图像误差</a> · <a href="../2026-11-18_DDGI-1080p-accumulated-comparison/report.html">优化前的高清收敛对比</a></p></html>''',encoding='utf-8')
sources=['Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang','Source/RenderPasses/RTXGIDDGI/DDGIReconstruct.cs.slang','tests/ddgi/half_gather_optimization.py','tests/ddgi/score_half_gather_optimization.py']
(O/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((R/p).read_bytes()).hexdigest() for p in sources},indent=2))
print(json.dumps(result,indent=2))
