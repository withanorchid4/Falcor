# SH Probe 的距离矩防漏光

> 本文记录早期 version 2 方向滤波方案。当前实现已按用户要求改为 texel 内独立采样与整数点读取，见 [texel 内采样开发约定](probe-texel-local-distance.md)。下文原始实现与实测结果作为历史记录保留。

2026-09-23，实施前设计；在原静态烘焙 Probe 插件中实现，不修改 Falcor 框架和 PathTracer/NRD。

## 依据

- 用户指定文章：https://www.cnblogs.com/KillerAery/p/16828304.html ，DDGI 的 probe update/gathering。
- 用户 PPT `黄铁豪答辩8.31（备注版）.pptx` 第 8–17 页及备注：八面体 DistanceMap、最近距离的一阶/二阶矩、三线性×方向×切比雪夫权重；第 12–13 页说明墙内探针和搬移的限制。文件实际位于 `D:/Wechat/chatlog/xwechat_files/wxid_h65dua960ii822_cedd/msg/file/2026-09/`。只作为参考，不修改或提交 PPT。
- 核对 NVIDIA RTXGI-DDGI 的 `Irradiance.hlsl`、`ProbeBlendingCS.hlsl` 所述算法语义；独立实现数学和资源组织，不复制其受限许可源码。https://github.com/NVIDIAGameWorks/RTXGI-DDGI

## 数据与烘焙

2026-09-23 调整前约定（按用户最新要求更新）：为分辨率对照将距离图上限从 32 提高到 128，默认仍为 14。构造参数校验、运行时配置校验和 GUI 共用同一上限。384 个 Probe 的 128 分辨率 atlas 为 2600×2600（含边界和空槽），RGBA32Float 约 103.1 MiB；保持现有缓存格式，变更分辨率仍要求重烘焙。本次只修改代码并编译，不操作用户界面、不覆盖当前缓存；运行中的 DLL 被占用时编译到备用目录。提高分辨率不改变角滤波指数或烘焙射线数量。

保留 9 个 RGB SH radiance 系数，新增每 Probe 的八面体距离矩。默认内部 14×14，可调 4..128；每块添加 1 texel 的折叠边界，Atlas 用近似正方形的 Probe 排列。RGBA32Float 存 E[d/D]、E[(d/D)^2]、累计角权重、保留值；D=distanceRangeScale×网格间距向量长度，默认 scale=2。归一化避免距离平方溢出；未命中按 D，双面几何为遮挡、保持原 alpha test；玻璃在距离图中也是几何遮挡，本版不做透明可见性。

复用每条烘焙路径第一段射线的 hitT 和原始均匀球面方向，与后续反弹无关。即使光照路径数值异常重试，距离统计仍取初始几何样本。每批 RayGen 写当前批射线，独立 ComputePass 将距离按 max(dot(texelDir,rayDir),0)^exponent 累积，默认 exponent=50。统计 E[d²] 而非 E[d]²；只在 Bake 时派发，不在运行时发额外可见性射线。无角样本的 texel 暂以 (1,1) 处理；低采样烘焙仍可能欠采样，应增加样本或降低距离锐度。边界 texel 用折叠后的相同方向独立计算，避免跨 Probe 插值和接缝读写竞争；显式 UAV 屏障。

## 运行时与调试

先用已有 normalBias 得到查询位置 Q；按 Probe→Q 的方向查距离图。归一化查询距离 t，μ=E[d/D]，v=max(E[(d/D)²]−μ²,varianceFloor)。t≤μ 时 visibility=1，否则 visibility=(v/(v+(t−μ)²))^visibilityPower；默认 power=3、varianceFloor=1e-6。方向权重为 ((dot(N,normalize(Probe−P))+1)/2)^2+0.2，方向来自未偏移表面点。乘原三线性权重后归一化；分母下限 1e-4，全部被拒绝时输出黑色，不把极小残余放大成漏光。

默认启用距离可见性与方向权重；master 开关关闭时精确回到原三线性+SH流程，另设方向权重开关。这些选项、varianceFloor、power 和 normalBias 即时生效，不重烘焙。距离分辨率、范围和角权重指数属于烘焙参数，修改会使缓存失效。

统一生产采样和选点检查的权重代码；选点面板显示原三线性权重、距离矩、查询距离、切比雪夫权重、最终权重。原诊断阴影射线保留，只用于比较真实几何可见性。增加可见性支持视图、选中 Probe 的八面体平均距离/方差图。

## 缓存与兼容

单个 .shprobe 文件升级 version 2：保留 SH 元数据和系数，新增距离参数、atlas 布局和归一化距离矩。加载检查版本、完整性、有限数及矩的物理范围；尺寸由本地设置计算，不相信文件中的分配大小。旧 version 1 明确提示缺少距离矩需重新 Bake，不悄悄假装已启用防漏光。保存仍在全部验证成功后临时文件原子替换，取消/失败不覆盖旧文件。新增数据随场景和烘焙参数一起失效。

## 验证顺序

构建插件；检查八面体映射/接缝与矩公式；建立遮挡墙测试，实际烘焙、关闭/开启可见性比较，检查选点权重和 HDR。验证新缓存重启加载与原图一致、旧缓存和截断/非有限矩拒绝、开关不重烘焙、分辨率变更重烘焙、切图保留缓存。用 Room 做实景观察并保留截图。距离矩是近似可见性，不承诺完全消除漏光；本次不做 relocation/classification、SDF、动态 GI、包体压缩或分层 Probe。

## 实测记录（2026-09-23）

- Windows Release 插件构建通过；D3D12 / RTX 5080 完成实际 GPU 烘焙和 Shader 编译。
- `tests/probe_gi/distance_visibility.py`：封闭明暗双室、8 个 Probe、2048 samples/probe；被隔墙挡住的 Probe 在四个有效选点的总权重均降至关闭时的一半以下。例如 0.141128 → 0.00000418；较困难选点仍有 0.460000 → 0.064694 的残余。
- `tests/probe_gi/check_distance_results.py`：所有八面体边界与折叠内部像素一致；距墙 0.48 的 Probe 在 +X 附近测得滤波均值 0.490323（角滤波下并非单根垂直射线距离）。
- 独立进程加载新缓存后，HDR 输出与刚烘焙时最大差值为 0；旧版本、截断、非有限及非法方差缓存均被拒绝。距离分辨率不匹配被拒绝；运行时开关保留烘焙数据。
- `tests/nrd/graph_switching.py` 通过：同进程切换 PathTracer / PathTracerNRD / TraditionalProbeGI、共用场景相机、切出暂停烘焙/切回继续、相机移动后切图保留缓存、换场景使 Probe 失效。结果 `build/gi-switch-validation/e79382f5/result.json`。
- 隔墙测试暗室图像的平均 Probe 光照为关闭时的 24.28%。这是同一烘焙结果的 A/B 抑制指标，不是相对 PathTracer 的误差或漏光消除率。
- Room 用 384 个 Probe、512 samples/probe 做场景兼容及 A/B 检查，HDR 有限，保留截图；仍可见局部斑块和残余漏光，不能据此声称完全解决。常规使用保持默认 2048 samples/probe；墙内探针、空间覆盖不足以及距离矩近似需要分别排查。

本地结果保存在忽略目录 `build/probe-distance-validation/`：`integration.json`、`load.json`、`results.json` 和对应 PNG/HDR；测试命令使用 `--device-type d3d12 --headless --deferred --script F:/tests/probe_gi/distance_visibility.py --width 640 --height 360`，环境变量 `PROBE_DISTANCE_TEST=bake` / `load` 分两次运行，再执行 `check_distance_results.py`。
