import json,pathlib,hashlib,shutil,subprocess,sys
sys.path.insert(0,'F:/build/official-ddgi/python-libs')
import numpy as np,OpenEXR
s=json.loads(pathlib.Path('F:/build/gi-evaluation-current.json').read_text());w=pathlib.Path(s['work']);r=pathlib.Path(s['result']);rep=r/'reproduction'
def save(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return OpenEXR.File(str(p)).channels()['RGB'].pixels
def git(*args):return subprocess.check_output(['git','-C','F:/',*args],text=True,encoding='utf-8')
for name in ['capture.py','run.py','control.py','score.py','lambert.pyscene','finalize.py']:shutil.copy2(w/name,rep/name)
(rep/'git-status.txt').write_text(git('status','--short'),encoding='utf-8')
(rep/'working-tree.patch').write_text(git('diff','--','Source/RenderPasses/RTXGIDDGI','Source/RenderPasses/PathTracer','Source/Falcor/Rendering/Materials','scripts/scenes'),encoding='utf-8')
sources={}
runtime=w/'runtime'
for folder in ['shaders/RenderPasses/RTXGIDDGI','shaders/RenderPasses/PathTracer','shaders/Rendering/Materials']:
 for p in (runtime/folder).rglob('*'):
  if p.is_file():
   rel=p.relative_to(runtime);dest=rep/'source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest);sources[str(rel)]={'sha256':sha(p),'snapshot':str(dest.relative_to(rep))}
for relative in ['Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.h']:
 p=pathlib.Path('F:/')/relative;dest=rep/'source'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest);sources[relative]={'sha256':sha(p),'snapshot':str(dest.relative_to(rep))}
binaries={}
for p in [runtime/'Mogwai.exe',runtime/'Falcor.dll',*list((runtime/'plugins').glob('*RTXGIDDGI*')),*list((runtime/'plugins').glob('*PathTracer*'))]:
 if p.is_file():binaries[str(p)]={'sha256':sha(p),'bytes':p.stat().st_size}
save(rep/'source-record.json',{'git_commit':git('rev-parse','HEAD').strip(),'sources':sources,'binaries':binaries,'notes':'DDGI/source DLL files unchanged by this experiment. Isolated PT shader patched only to suppress primary direct/emission. Existing dirty tree retained.'})
audit={}
for kind in ['Accumulate','AccumulateAll']:
 a=read(w/f'pt-a/frame-512.{kind}.output.0.exr');b=read(w/f'pt-default/frame-512.{kind}.output.0.exr');audit[kind]={'default_vs_minimalpayload_max_abs_error':float(np.abs(a-b).max())}
audit['lambert_ddgi_vs_native_max_abs_error']=max(float(np.abs(read(w/f'ddgi/frame-{i}.DDGI.indirect.0.exr')-read(w/f'lambert-ddgi/frame-{i}.DDGI.indirect.0.exr')).max()) for i in range(16385,16417))
save(rep/'audit.json',audit)
for case in ['ddgi','pt-a','pt-b','pt-default','lambert-ddgi','lambert-pt-a','lambert-pt-b']:
 dest=rep/'captures'/case;dest.mkdir(parents=True,exist_ok=True)
 for name in ['complete.json','command.json','timing.json']:
  if (w/case/name).exists():shutil.copy2(w/case/name,dest/name)
all_data=json.loads((r/'summary.json').read_text());n=all_data['cases']['native'];c=all_data['cases']['lambert-control'];o=all_data['official_summary']
def row(label,a):return f"| {label} | {a['mean_hdr_flip']:.4f} | {a['linear_rgb_mse']:.6g} | {a['gi_gpu_ms_mean']:.3f} | {a['luminance']['relative_difference']:+.1%} |"
table='| 对比 | Mean HDR-FLIP ↓ | 线性 RGB MSE ↓ | GI GPU ms | DDGI 平均亮度相对 PT |\n|---|---:|---:|---:|---:|\n'+ '\n'.join([row('官方 Test Harness（此前结果）',o),row('Falcor 当前材质',n),row('Falcor 纯 Lambert 材质对照',c)])
body=f'''# Falcor DDGI 与 Path Tracer 对比

已完成。**当前 Falcor 的差异比官方示例大；将材质对齐为纯 Lambert 后，误差接近官方的量级，但还没有一致。** 当前材质下，DDGI 的有效区域平均线性亮度比 PT 高 {n['luminance']['relative_difference']:.1%}；纯 Lambert 对照下则低 {-c['luminance']['relative_difference']:.1%}。测试没有修改产品 DDGI。

{table}

两组 Falcor 都逐帧评估 32 帧后取平均，没有额外平均 DDGI 图像。官方使用此前已完成的结果。三组使用同一几何、相机、mask、HDR-FLIP 参数和显示曝光；灯光衰减、材质、部分探针参数与预热预算仍有引擎差异，因此表格用于描述差异，不作为接入合格判据。MSE 保留各自原始辐射度尺度。

当前材质：左 DDGI，右 Falcor PT。两边显示首个表面的间接漫反射，统一 +3 EV、ACES、sRGB。代表帧 16416，HDR-FLIP {n['representative']['mean_hdr_flip']:.4f}。DDGI 的墙面、柱体和地面普遍偏亮，接触区也更平滑。

![当前材质对比](native/comparison.png)

同一帧的 HDR-FLIP 热力图，固定 0–1 色标。误差遍布表面，不仅集中在轮廓。

![当前材质误差](native/flip-heatmap.png)

材质控制实验保持颜色、几何、相机、灯光和 DDGI 参数不变，仅在独立测试场景中把三个 StandardMaterial 换成 PBRTDiffuseMaterial（纯 Lambert）。**32 帧 DDGI 与原材质逐像素完全相同**，PT 参考改变，HDR-FLIP 从 {n['mean_hdr_flip']:.4f} 降到 {c['mean_hdr_flip']:.4f}。这确认材质路径不一致是本次偏差的主要来源之一。

![纯 Lambert 对照](lambert-control/comparison.png)

原因在于 DDGI 更新和屏幕查询都按 `albedo / π` 计算；当前 StandardMaterial 实际编译的是 **Frostbite 漫反射 + GGX 镜面**。`BSDFConfig.slangh` 的默认宏覆盖了材质文件中 Disney 的概括性注释。粗糙度为 1 时，Frostbite 漫反射含 `energyFactor = 1 / 1.51`，另有随方向变化的散射因子；多次反弹会累积差异。纯 Lambert 控制同时去除了镜面分支，本次没有把两者的影响进一步单独分解。

Lambert 对照的 HDR-FLIP 比官方高 {c['mean_hdr_flip']-o['mean_hdr_flip']:.4f}。剩余差异不能直接归因于 DDGI 接入：Falcor 点光源使用近似 `1/r²` 衰减，官方用 `1/max(r,1)²`，并乘半径 4 的窗口函数；靠近顶灯的表面受光强度不同。两边还有 probe 格式、relocation 最小距离（Falcor 0.03、官方 0.1）、历史亮度阈值和官方 GBuffer 色彩往返转换等差别。本次保留这些原有行为。

每组 PT 为 **32,768 spp、最多 20 个表面顶点、关闭 RR、无降噪**，另跑不同随机序列。当前材质的 PT–PT HDR-FLIP 为 {n['reference_check']['mean_hdr_flip']:.4f}，Lambert 为 {c['reference_check']['mean_hdr_flip']:.4f}，分别约为 DDGI 差异的 {n['reference_check']['flip_fraction_of_candidate_error']:.1%}、{c['reference_check']['flip_fraction_of_candidate_error']:.1%}。参考仍有残余噪声，但不足以解释当前材质的大幅偏亮。另以相同种子检查 PT Default 与 MinimalPayload 后端，4,096 spp 的漫反射与完整间接光输出均逐像素一致。

DDGI：9×9×9 probes、每探针 256 rays、间距 0.3，最多 186,624 条 probe rays/更新；relocation 和 classification 开启。先更新 16,384 帧，再采集 32 帧。8,192 与 16,384 帧的 HDR-FLIP 变化约 0.002，按长预热后的固定预算结果报告。GPU 使用 RTX 5080 / 617.14；计时取 Falcor GPU profiler 的完整 DDGI pass，包含 probe 更新和屏幕查询，排除 GBuffer、PT、读回与文件输出，另取 511 个完整时间戳区间。未测试动态闪烁。

原始数据与复现：[当前配置](native/report.md)、[Lambert 对照](lambert-control/report.md)、[复现说明](reproduction/README.md)、[汇总 JSON](summary.json)。每个用例目录包含 32 份候选 EXR、两份独立 PT EXR、误差 EXR、mask、逐帧 CSV、计时 CSV 和 manifest。官方基线见 [此前报告](../2026-11-16_12-04_NVIDIA-DDGI-vs-PT_CornellBox/report.md)。
'''
(r/'report.md').write_text(body,encoding='utf-8')
for case,a,label in [('native',n,'当前 StandardMaterial'),('lambert-control',c,'纯 Lambert 材质')]:
 (r/case/'report.md').write_text(f'''# Falcor DDGI vs PT：{label}

已完成 32 帧静态评估。Mean HDR-FLIP **{a['mean_hdr_flip']:.4f}**；线性 RGB MSE **{a['linear_rgb_mse']:.6g}**；DDGI GPU **{a['gi_gpu_ms_mean']:.3f} ms**。

左 DDGI，右 PT；同相机、同灯光、同显示变换。代表帧 16416 的 HDR-FLIP 为 {a['representative']['mean_hdr_flip']:.4f}。

![对比](comparison.png)

![HDR-FLIP，固定 0–1](flip-heatmap.png)

| 有效帧 | Mean HDR-FLIP | 线性 RGB MSE | GI GPU ms |
|---:|---:|---:|---:|
|32|{a['mean_hdr_flip']:.6f}|{a['linear_rgb_mse']:.9g}|{a['gi_gpu_ms_mean']:.6f}|

PT 32,768 spp，另跑独立序列，参考间 HDR-FLIP {a['reference_check']['mean_hdr_flip']:.6f}。DDGI 预热 16,384 帧；GPU 取独立 511 个完整时间戳区间，包含更新和查询。有限采样与有限反弹参考；静态单场景结果。材质模型和与官方示例的区别见[总报告](../report.md)。

[配置 manifest](manifest.json) · [逐帧指标](metrics.csv) · [GPU 计时](timing.csv) · [汇总](summary.json) · [PT EXR](reference/pt.exr) · [复现](../reproduction/README.md)
''',encoding='utf-8')
(rep/'README.md').write_text(f'''# 复现本次实验

运行目录：`{w}`；独立程序：`{runtime}/Mogwai.exe`。原产品源码和部署文件未修改。`source-record.json` 保存实际 shader 与二进制 SHA-256，`source/` 保存 DDGI、PT、材质 shader 和 DDGI host 源码快照；`git-status.txt` 与 `working-tree.patch` 记录实验时已有改动。独立运行目录共用未修改 DLL 与依赖；PT shader 独立复制。

本次测量补丁只在 `addToPathContribution` 中排除 `vertexIndex == 1` 的贡献。PT 的后续路径继续正常跟踪，关闭 NRD demodulation 后读取漫反射 AOV；同时保留完整间接光输出用于核查。`PathTracer.slang.original`、`PathTracer.slang.evaluation` 和 `pt-indirect.patch` 保存补丁。它们不是产品修复。

固定状态文件为 `F:/build/gi-evaluation-current.json`。以下命令会重跑本次工作目录；另做新实验时先建立新状态与结果目录，避免覆盖。

```powershell
python -X utf8 "{w}/run.py"
python -X utf8 "{w}/control.py"
python -X utf8 "{w}/score.py"
python -X utf8 "{w}/finalize.py"
```

`run.py` 依次运行当前材质 DDGI、PT A、PT B。`control.py` 运行 Lambert PT A/B；Lambert DDGI 使用同一 capture.py，环境设置 `GI_CASE=ddgi`、`GI_OUT=lambert-ddgi`、`GI_SCENE={w}/lambert.pyscene`。所有运行均设置 `FALCOR_DEVMODE=0`、`FALCOR_MEDIA_FOLDERS=F:/media`、`GI_SMOKE=0`，命令为 `Mogwai.exe --device-type d3d12 --headless --deferred --script capture.py --width 960 --height 540 --logfile <log>`，工作目录 runtime。capture.py 使用快照 scene.json，而非用户正在编辑的灯光配置。

PT 8 spp/帧 × 4096 帧，fixedSeed=frame，第二序列加 104729；Default 后端审计为 GI_CASE=pt-default、GI_PT_TRACE=Default、GI_PT_FRAMES=512。审计结果见 audit.json。采集与计时详情见 captures/。

评分依赖 Python、NumPy 2.5.4，以及 `F:/build/official-ddgi/python-libs` 的 OpenEXR 3.5.4、flip-evaluator 1.7、Pillow 13；Magma 色表读取 matplotlib 数据文件。冻结的 FLIP 曝光取此前官方实验，不随候选改变。默认产品场景与显示配置未被改写。
''',encoding='utf-8')
print('reports and source snapshots saved',flush=True)
