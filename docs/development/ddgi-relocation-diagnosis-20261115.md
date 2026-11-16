# Bistro 探针 relocation 振荡诊断

2026-11-15。当前接入的 NVIDIA RTXGI-DDGI SDK 1.3.7 原生 relocation 在 Bistro 上复现了位置振荡。GPU 分支日志确认：probe 172 的上下跳动由连续的背面逃逸移动造成；probe 99 则在表面避让和回归网格之间形成稳定循环。两者机制不同。

## 方法与范围

BistroExterior，8×6×8 探针，每探针 256 条射线，自动体积，开启 relocation/classification，关闭 WRC，固定场景时间。分析连续 128 次探针更新。SDK 的移动表达式保持原样，只在 GPU 分支内记录原因、所选射线、距离、旧偏移、候选偏移、最终偏移和是否接受。程序退出时额外产生的第 129 次更新未纳入分析。

偏移已经由 SDK 解码为世界空间单位，世界位置为初始网格位置加偏移。网格间距约为 `(27.3052, 11.2407, 28.9800)`。本项目设置安全距离 `0.1 × 最小间距 = 1.124073`，背面比例阈值为 25%。relocation 检查前 32 条固定方向射线，因此至少 9 条背面命中就触发逃逸分支。

## 重点：probe 172

网格坐标 `(4,2,5)`，初始位置 `(38.07444,12.36487,47.74231)`。下面各行均为实际被接受的背面逃逸移动。

| 更新帧 | 背面数 / 32 | 最近背面射线 | 移动方向 | 移动后世界 Y |
|---|---:|---:|---|---:|
| 2 | 9 | 15 | 向上 | 13.41580 |
| 3 | 13 | 19 | 向下 | 12.37087 |
| 4 | 14 | 15 | 向上 | 13.41580 |
| 5 | 14 | 19 | 向下 | 12.37087 |
| 6 | 15 | 15 | 向上 | 13.41580 |
| 7 | 15 | 19 | 向下 | 12.37087 |

射线 15 的方向约为 `(-0.12845, +0.99122, +0.03125)`；射线 19 约为 `(-0.04507, -0.97474, -0.21875)`。方向本身固定，变的是移动后的射线起点和最近命中结果。

原生移动公式为：

```text
新偏移 = 旧偏移 + 最近背面方向 × (最近背面距离 + 0.5 × 安全距离)
```

第 4 帧向上移动长度为 `0.492149 + 0.562037 ≈ 1.054186`；第 5 帧向下移动长度为 `0.509977 + 0.562037 ≈ 1.072014`。两者的 Y 分量都约为 1.044934，产生明显的上下跳动。

因果链是：当前位置背面比例超过阈值 → 穿过最近背面并额外移动半个安全距离 → 下一帧从新位置追踪 → 另一方向的背面成为最近命中且比例仍超标 → 再向相反方向移动。算法没有记录上一帧的移动原因，也没有来回振荡检测。

X/Z 同时缓慢漂移，因此这是高度交替、伴随水平漂移，并非完整三维坐标严格两点循环。整个 128 帧中该探针从未进入“回归初始网格”分支。后段还有候选移动超出允许偏移范围而被拒绝的情况，不能把这些尝试算成实际位移。

本次未记录命中三角形和实例 ID，尚不能判断具体是哪片模型、单面几何或法线问题导致这些背面命中。日志已定位移动反馈机制；模型拓扑成因需要另一次几何命中诊断。

## 对照：probe 99

此探针背面数为零，也会持续振荡。安全距离为 1.124073，稳定后的行为如下：

| 状态 | 最近正面距离 | 原生分支 | Y 偏移变化 |
|---|---:|---|---|
| 较低位置 | 约 1.104845 | 距表面太近，沿射线 15 避让 | 0.25561 → 1.24683 |
| 较高位置 | 约 2.124073 | 距表面够远，向初始网格回退 | 1.24683 → 0.25561 |

128 帧中避让和回归各执行 64 次。这证明原生启发式在当前尺度与几何下可以出现持续两帧循环。

SDK 的正面避让分支实际使用 `fullOffset = offset + farthestFrontfaceDirection`，即一个世界单位的步长。它前面计算了 `farthestFrontfaceDistance`，但该值没有用于位移表达式。这是当前 SDK 源码的行为，本次没有修改；不能把修正此分支直接当作 probe 172 背面振荡的修复。

## 实现归属与结论

`Source/RenderPasses/RTXGIDDGI/ProbeRelocation.cs.slang` 直接包含 SDK 的 `ProbeRelocationCS.hlsl`。移动规则来自 NVIDIA；本项目负责射线追踪、距离/背面结果写入、每帧调度和体积参数。当前路径每帧从“网格位置 + 已保存偏移”发射射线，随后根据这些结果计算下一帧偏移。

这次证据可以认定为原生 relocation 规则在当前输入下的收敛问题。尚未在 NVIDIA 独立示例上复现，也未定位模型三角形，因此不将其扩大为所有 DDGI 实现都存在的确定缺陷。

诊断目录：`build/relocation-diagnosis/20261115-220502/`。`probe-172.csv` 和 `probe-99.csv` 保留完整逐帧字段；`analysis.json` 保留各探针振荡统计。CSV 原因码：1=背面逃逸，2=正面避让，3=回归网格，4=避让方向条件不满足，0=无候选；`accepted` 表示候选通过范围检查，实际移动还需比较 old/new。

临时 GPU 埋点、CPU 回读及逐帧日志输出已移除，恢复包含原生 SDK shader。本次未修改 relocation 算法。清理后重新编译成功，并在 Bistro 完成 4 帧运行检查，探针纹理数值有限。原始 SDK 文件 SHA256 在诊断前后保持一致。

## 官方示例复核与性能对照

官方 test-harness 的 `DDGI.cpp` 编译 SDK 的 `ProbeRelocationCS.hlsl`；`DDGI_D3D12.cpp::Execute()` 在射线追踪和探针混合之后调用 `RelocateDDGIVolumeProbes()`。它对选中更新的体积执行这一步；可选 variability 收敛逻辑可停止整个体积的更新，并非 relocation 内部的振荡检测。

需要补充版本差异：[v1.3.7](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/v1.3.7/rtxgi-sdk/shaders/ddgi/ProbeRelocationCS.hlsl) 中确实是 `farthestFrontfaceDistance *= min(...)`，而 2026-11-15 核查的[官方 main](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/ProbeRelocationCS.hlsl) 已改成 `farthestFrontfaceDirection *= min(farthestFrontfaceDistance, 1.f)`，使正面避让步长受到命中距离限制。背面逃逸及回归网格公式仍相同。此改动不直接解决 probe 172 的背面振荡；probe 99 所选方向为 miss，距离极大，两版本在这一步也都是一个世界单位。

官方按场景配置安全距离，例如 [Sponza 配置](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/samples/test-harness/config/sponza.ini) 为 0.3，并提示与 view bias 协调。本项目把它固定为最小间距的 10%，在当前稀疏 Bistro 网格上是 1.124。建议开放独立配置，同时调整探针覆盖范围、密度和查询 bias；不应只减小安全距离而忽略查询偏移。

性能测试使用现有 Release 程序，无诊断回读和逐帧日志：Bistro，1280×720，8×6×8，256 rays，classification 开启、WRC 关闭、固定相机。Show probes 分别关闭和开启；每组按 relocation 关/开/开/关顺序，各窗口重置并预热 128 帧，再预热 profiler 12 帧，测量 128 次 renderFrame。Profiler 每窗口导出 127 个有效记录。以下为两个同条件窗口 GPU 均值的平均值。

| 显示探针 | relocation | 整帧 GPU ms | DDGI pass ms | SDKUpdate ms |
|---|---|---:|---:|---:|
| 关 | 关 | 3.893 | 0.469 | 0.0568 |
| 关 | 开 | 3.989 | 0.541 | 0.0653 |
| 开 | 关 | 5.535 | 2.084 | 0.0570 |
| 开 | 开 | 8.251 | 4.795 | 0.0658 |

隐藏探针球时整帧约增加 2.5%；显示时约增加 49%，对应 GPU 耗时倒数下降约 33%，并未在此条件下复现帧率减半。headless GPU 计时不等于用户窗口的呈现 FPS。

主要瓶颈位于我们自己的 `RTXGIDDGI.rt.slang::overlayProbes()`：每个像素遍历全部探针；relocation 开启时，循环内 `DDGIGetProbeWorldPosition()` 还会读取偏移纹理。1280×720×384 约为每帧 3.54 亿次球体候选检查。显示开启时，相机着色阶段从约 1.862 ms 增至 4.552 ms；探针更新阶段仅从约 0.221 ms 增至 0.243 ms。活跃探针数从 159 变为 175，也增加少量射线着色工作。

官方显示路径则通过 [ProbesUpdateCS](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/samples/test-harness/shaders/ddgi/visualizations/ProbesUpdateCS.hlsl) 更新探针实例变换，再由 [ProbesRGS](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/samples/test-harness/shaders/ddgi/visualizations/ProbesRGS.hlsl) 追踪探针 TLAS。优先改进本项目显示路径：采用实例化球体光栅化并进行场景深度测试，或采用官方的探针 TLAS，消除每像素遍历全部探针。

振荡改进建议分两步验证：先开放并调节安全距离；再加入稳定后暂停位置更新、几何变化后重新定位的调度。暂停应保留已有偏移及 SDK relocation 标志，只跳过移动 dispatch，继续更新 GI；当前 UI 关闭 relocation 会重置历史，不能当作冻结位置使用。持续动态模式可进一步加入回归分支滞回和反向移动检测，避免简单平滑使探针停在墙内。上述方案均尚未实施，也未宣称能保证收敛。

性能原始记录：`build/relocation-diagnosis/perf-20261115-221426/`，含八个 timing JSON 和 `complete.json`。本轮仅增加诊断脚本与报告，没有修改产品渲染代码。
