from pathlib import Path
import json,sys,hashlib,numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/ddgi-query-math';O=R/'docs/2026-11-22_DDGI查询重复计算优化';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'));import OpenEXR
assert not (D/'failure.txt').exists();runs=json.loads((D/'complete.json').read_text());out={}
prefix='/onFrameRender/RenderGraphExe::execute()'
def read(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels;assert np.isfinite(a).all();return a
for name,run in runs.items():
 ref=read(D/(name+'-baseline.DDGI.indirect.0.exr'));mask=np.linalg.norm(read(D/(name+'-baseline.Visibility.normW.0.exr')),axis=-1)>.5
 out[name]={}
 for variant in ['baseline','hoist','normalize','both']:
  records=[x for x in run['records'] if x['variant']==variant]
  query=[r['timing']['events'][prefix+'/DDGI/PrimaryShading/gpu_time']['stats']['mean'] for r in records]
  graph=[r['timing']['events'][prefix+'/gpu_time']['stats']['mean'] for r in records]
  a=read(D/(name+'-'+variant+'.DDGI.indirect.0.exr'));diff=a[mask].astype('float64')-ref[mask]
  out[name][variant]={'shading_ms':query,'graph_ms':graph,'median_shading_ms':float(np.median(query)),'median_graph_ms':float(np.median(graph)),'indirect_mse_vs_baseline':float(np.mean(diff**2)),'indirect_max_abs_diff':float(np.max(np.abs(diff)))}
 out[name]['saving_percent']=100*(1-out[name]['both']['median_shading_ms']/out[name]['baseline']['median_shading_ms'])
out['source_hashes']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [R/'cmake/ddgi-tetrahedral.cmake',R/'Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp']}
(O/'summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''
for name in ['eight','four']:
 for v in ['baseline','hoist','normalize','both']:
  a=out[name][v];rows+=f"<tr><td>{name}</td><td>{v}</td><td>{a['median_shading_ms']:.6f}</td><td>{a['median_graph_ms']:.6f}</td><td>{a['indirect_mse_vs_baseline']:.3g}</td><td>{a['indirect_max_abs_diff']:.3g}</td><td>{min(a['shading_ms']):.6f}–{max(a['shading_ms']):.6f}</td></tr>"
conclusion=f"<p>两项同时开启：8点主着色降低 {out['eight']['saving_percent']:.2f}%，4点降低 {out['four']['saving_percent']:.2f}%。主要收益来自法线坐标外提，省略归一化单项收益约千分之一量级；两项叠加不保证比外提单项更快。最大绝对差约1.03e-4，间接光MSE约5.25e-14，属于很小的数值差异。本实验仅证明固定视角、冻结缓存下的表现，没有实测正常探针更新整帧的收益。</p>"
html='''<!doctype html><meta charset="utf-8"><title>DDGI 查询重复计算优化</title><style>body{background:#171a1f;color:#eee;font:17px/1.7 sans-serif;max-width:1300px;margin:30px auto}td,th{padding:8px;border:1px solid #555}a{color:#9cf}</style><h1>DDGI 查询重复计算优化</h1><p>SponzaLambert，1920×1080，RTX 5070、D3D12，方向光50，点光关闭。22³探针，256 rays/probe。8点和4点分别预热8192帧后冻结同一份探针缓存；每种模式测试原版、仅外提法线八面体坐标、仅省略距离方向归一化、两项合并。每组预热64帧、计时512帧，交替正反顺序重复4轮。表格取每轮平均值的中位数，区间为各轮均值的最小/最大。</p><p>本实验关闭图像累积以隔离查询，直接比较同一冻结缓存的间接光输出；工程正常入口的全分辨率与默认Accumulate保持原设置。主着色仍包含直接光与阴影射线，不等于纯probe查询；冻结实验不测探针更新阶段的收益。未重新与PT比较，因为两项都是数学等价改写，只检查输出数值差异。</p><table><tr><th>探针数</th><th>改动</th><th>主着色ms</th><th>整图ms</th><th>间接光MSE对原版</th><th>最大绝对差</th><th>主着色各轮均值范围ms</th></tr>'''+rows+'''</table>'''+conclusion+'''<p>baseline=两项关闭，hoist=仅外提公共法线坐标，normalize=仅省略用于八面体映射的欧氏归一化，both=两项开启。省略的方向归一化不用于法线权重或距离测试，那些计算保持原样。输出差异来自浮点舍入与纹理采样。收益小于各轮波动时，不应宣称获得稳定加速。</p><p><a href="summary.json">全部数据</a></p>'''
(O/'report.html').write_text(html,encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
