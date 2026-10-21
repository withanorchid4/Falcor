# Probe 防漏光方案调研

2026-09-24。仅调研，没有修改渲染算法。源码链接指向当日读取的 main/master，后续可能变化。

## 当前约束与证据

- 距离图固定 14×14，不调整 normal/view bias，不恢复表面背面 Probe 全部剔除。
- 不引入每 Probe 四次切比雪夫；稀疏调度与可见性后端继续解耦。
- 固定案例：`build/probe-issues/20260924-104702-ae8fb0`。
- Probe 375 的相邻方向含真实墙面命中和越过有限墙边缘的 MISS；延长射线仍 MISS。
- MISS 以距离上限参与矩统计，导致混合方向的大方差。仅平滑画面或移开查询点不能证明根因已解决。

## 实现参考

| 实现 | 核对位置 | 具体机制 | 对本案例的判断（推断） |
| --- | --- | --- | --- |
| NVIDIA RTXGI-DDGI | [ProbeBlendingCS.hlsl](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/ProbeBlendingCS.hlsl) | 距离截到 `1.5 * length(probeSpacing)`；余弦幂方向加权后写入矩 | 可降低远距离样本影响，不能分离真实 HIT/MISS；方向滤波以前已试过 |
| RTXGI runtime | [Irradiance.hlsl](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl) | 双线性取矩、一次切比雪夫、概率立方、小权重连续压低 | 不是四次切比雪夫；不能恢复矩中丢失的遮挡边界 |
| RTXGI placement | [ProbeRelocationCS.hlsl](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/ProbeRelocationCS.hlsl)、[ProbeClassificationCS.hlsl](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/ProbeClassificationCS.hlsl) | 根据背面命中比例与附近表面距离移动/停用 Probe | 几何内部 Probe 的质量治理；有效室外 Probe 仍可能影响室内 |
| Unity APV | [ProbeVolume.hlsl](https://github.com/Unity-Technologies/Graphics/blob/master/Packages/com.unity.render-pipelines.core/Runtime/Lighting/ProbeVolume/ProbeVolume.hlsl) | `LoadValidityMask`、`WarpUVWLeakReduction`、`QualityLeakReduction`，按有效性与 Layer 控制插值 | 额外资格信息能阻止跨区域混合；Validity 本身并非逐点射线可见性 |
| Godot SDFGI | [sdfgi_preprocess.glsl](https://github.com/godotengine/godot/blob/master/servers/rendering/renderer_rd/shaders/environment/sdfgi_preprocess.glsl)、[gi.glsl](https://github.com/godotengine/godot/blob/master/servers/rendering/renderer_rd/shaders/environment/gi.glsl) | `MODE_OCCLUSION` 根据体素实体/朝向传播遮挡；运行时采样独立 3D 遮挡纹理乘权重 | 可参考其独立空间遮挡数据；额外体积内存、薄墙分辨率和插值误差需验证；不是直接替换矩公式 |

## 引擎文档的边界

- [Unity Leak Reduction 配置](https://docs.unity3d.com/6000.0/Documentation/Manual/urp/probevolumes-options-override-reference.html)：Performance 改采样 UVW、一次 APV 采样；Quality 一到三次 APV 采样。这里“一次”会读取多张 SH 纹理，不能等同于一条纹理指令。
- [APV 漏光处理](https://docs.unity3d.com/6000.0/Documentation/Manual/urp/probevolumes-troubleshoot-light-leaks.html)：Rendering Layers 可隔离室内外；调整体可使特定 Probe 无效。区域划分仍需处理门窗和跨区物体。
- [APV 有效性](https://docs.unity3d.com/6000.0/Documentation/Manual/urp/probevolumes-light-probe-validity.html)：Virtual Offset 改烘焙捕获位置；Dilation 给无效 Probe 填附近有效数据。不能把 Probe 有效等同于对所有着色点可见。
- [UE Volumetric Lightmaps](https://dev.epicgames.com/documentation/unreal-engine/volumetric-lightmaps-in-unreal-engine)：漏光排障建议增加空间采样密度或加厚墙体，没有给出等价的 14×14 距离矩修复。
- [GPU Lightmass](https://dev.epicgames.com/documentation/en-us/unreal-engine/gpu-lightmass-global-illumination-in-unreal-engine)：Aggressive Leak Prevention 使用缓存背面检测，Corner Rejection 拒绝角落缓存记录。属于烘焙 Irradiance Cache 措施。
- [Lumen](https://dev.epicgames.com/documentation/unreal-engine/lumen-technical-details-in-unreal-engine)：维护几何追踪表示；薄墙表示、遗漏遮挡物、追踪范围都影响漏光。与本案例已经确认的合法 MISS 不同。

UE 官方方案部分只核对官方文档；下面另行对照本地 MagicDawn 修改，不能将其当作 UE 官方实现。

## NVIDIA RTXGI/DDGI 与 MagicDawn 对比

比较范围：NVIDIA RTXGI-DDGI 的距离矩防漏光路径，以及本地 `C:/Users/Admin/Desktop/烘焙GI调研/magicdawn-ue554` 的 VLM/PRT 路径。MagicDawn 有旧版 `MAGICDAWN_DEPTH_LL_ENABLE` 和 PRT `ENABLE_VISIBLE_MASK` 等不同条件编译分支；以下不代表所有分支同时启用。

两者的核心流程相同：双线性采样距离均值 μ 和二阶矩 m₂，计算 `variance = abs(m₂ - μ²)`；当 `d > μ` 时计算切比雪夫权重并取三次方；结合朝向权重、小权重抑制和三线性权重，最终归一化。两边都是每个 Probe 一次切比雪夫，并非每个 Probe 四次。

| 项目 | NVIDIA RTXGI/DDGI | 本地 MagicDawn |
| --- | --- | --- |
| 距离矩采样 | 双线性采样八面体距离图 | 双线性采样八面体距离图 |
| 朝向权重 | `((n·l + 1) / 2)² + 0.2` | 旧分支相同；PRT 分支将常数参数化，并对 wrap 项取非负值 |
| 朝向使用的位置 | 原始表面点 P 到 Probe | 从偏移后的查询位置构造方向；旧分支还考虑 ProbeBiasMap 中的 Probe 位置偏移 |
| 切比雪夫 | `d <= μ` 时取 1，否则取 `[variance / (variance + (d-μ)²)]³` | 同样的公式，受开关控制 |
| 可见性最低权重 | 固定 `0.05` | 可配置；旧分支默认 `0.01`，PRT 分支由参数传入，不能用旧分支默认值代替实际配置 |
| 小权重抑制 | 朝向与可见性相乘后，阈值 `0.2` 以下使用连续三次压低，再乘三线性权重 | 同样的处理顺序 |
| 光照数据 | 运行时采样方向性 irradiance 纹理 | 所检查的路径混合 VLM 的 SH 系数 |
| 距离图覆盖 | 按 DDGI Volume 组织 | PRT 分支只给符合条件的最细一级 VLM brick 查询距离图 |
| Probe 位置处理 | 提供 Relocation 和 Classification | 旧分支读取 ProbeBiasMap，并可调整带偏移 Probe 的贡献；尚未核对该图的生成规则 |
| 额外室内处理 | 本次所查距离矩路径不包含 MagicDawn 的室内体积接口 | 存在 Interior Volume/Portal 查询位置调整入口；本地缺少部分被引用实现，完整行为及实际启用状态未确认 |

源码依据：

- [RTXGI Irradiance.hlsl](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl)：距离矩、朝向、可见性和最终混合。
- [MagicDawn VolumetricLightmapCommonPRT.ush](C:/Users/Admin/Desktop/烘焙GI调研/magicdawn-ue554/Engine/Shaders/Private/PRT/VolumetricLightmapCommonPRT.ush:85)：PRT 权重函数 `CalcProbeWeight`。
- [MagicDawn VolumetricLightmapSharedPRT.ush](C:/Users/Admin/Desktop/烘焙GI调研/magicdawn-ue554/Engine/Shaders/Private/PRT/VolumetricLightmapSharedPRT.ush:252)：双线性距离图采样、8 Probe 权重和 SH 混合；同文件前部有最细 brick 限制与室内体积调用入口。
- [MagicDawn VolumetricLightmapShared.ush](C:/Users/Admin/Desktop/烘焙GI调研/magicdawn-ue554/Engine/Shaders/Private/VolumetricLightmapShared.ush:125)：旧分支权重与 ProbeBiasMap 处理。
- [MagicDawn SceneRendering.cpp](C:/Users/Admin/Desktop/烘焙GI调研/magicdawn-ue554/Engine/Source/Runtime/Renderer/Private/SceneRendering.cpp:174)：旧分支 `GMinChebyshevWeight` 默认值。

对当前案例的判断：单独换成 MagicDawn 的运行时切比雪夫公式不能证明会修复问题，因为核心公式基本相同。已定位的异常来自近墙 HIT 与远处 MISS 混合后的输入距离矩。尚需核对 MagicDawn 的距离图烘焙、MISS 编码和过滤规则，才能判断它是否在输入阶段采取了不同处理；不能根据运行时公式推断其烘焙行为。

## 后续选择（尚未实施）

2026-09-24 后续已做一次静态 DDGI 距离矩/权重同步对照，见 [实施与验证记录](probe-ddgi-alignment.md)。特定硬边的相邻像素跳变减小，但整墙暗块和漏光仍存在；以下区域隔离、独立遮挡场与 HIT/MISS 分离仍未实施。

1. 若目标是低成本工程阻漏，可验证 APV 式区域/Layer 权重门控。保留 14×14，不修改查询 bias；但它不修复原始方差形状，且需区域标记。
2. 若目标是更通用的几何可见性，可评估 Godot 式独立空间遮挡场。烘焙时用现有射线产生遮挡数据是我们自己的适配方案，不是 Godot 原算法。总内存与带宽必须单独预算，不能声称免费。
3. 若必须只用现有距离矩预算，现有一二阶矩不能唯一确定混合分布。应比较统计表示的改动，不能承诺只调切比雪夫常数即可彻底解决。

## 保留备选：命中矩与 MISS 比例分离

记录 H = 命中数 / 总数，M1 = 命中距离和 / 总数，M2 = 命中距离平方和 / 总数。插值后用 M1/H、M2/H 计算条件命中矩；H=0 独立处理为可见。候选可见性为 `(1-H) + H * ChebyshevHit`，再评估原有指数压缩。

这只是本项目候选，不是以上官方方案。已有局部 CPU 数据对照，尚未完成整帧质量、门窗、全 MISS、远处真实命中和性能验证。此轮按用户要求保留，不实施。
