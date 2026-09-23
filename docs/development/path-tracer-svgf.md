# PathTracer + SVGF 接入约定

2026-09-23：先记录本设计，再实现。目标是在当前 Vulkan 环境试用仓库自带 SVGF，而非另写一个降噪算法。

## 实现范围

1. 新增 `scripts/PathTracerSVGF.py`，参考官方 `tests/image_tests/renderpasses/graphs/SVGF.py`。使用同一 GBufferRaster 为 PathTracer 和 SVGF 提供可见性、法线、深度及其导数、运动向量、位置和自发光，PathTracer 提供 color/albedo。Raster 是因为当前 GBufferRT 没有 SVGF 必需的 pnFwidth。
2. 默认 1 spp、SVGF 原有四轮 à-trous 和时间参数，不预先关闭焦散、不限制亮度，不改变原 PathTracer 和 Probe GI 的算法。降噪作用于线性 HDR，之后 ToneMapper 显示。
3. 三个明确输出：`ToneMapperSVGF.dst`（默认降噪）、`ToneMapperRaw.dst`（同帧原始）、`ToneMapperReference.dst`（独立普通累积）。SVGF 前后不串联普通累积；参考分支默认无限累积、Auto Reset 开启。
4. 若原有 SVGF 的历史管理影响集成，限于该 Pass 增加 Reset history，并在重新载入场景、场景内容/光照变化和渲染选项变化时清历史。普通相机移动使用官方重投影，不能每帧清空；分辨率变化沿用 compile 清理。保持官方滤波核心；若实测发现必要的兼容/背景/边界问题，先补记本设计再修复。
5. `Run-Falcor.ps1` 增加 `-Renderer PathTracer|SVGF`，保持原默认值；新增便捷 `Run-SVGF.cmd`。运行中可 Load Script 后切 Active Graph，共享当前场景。补充中文使用说明、参数含义、已知镜面/玻璃和 firefly 限制。

## 验证

- 优先仅构建所需 SVGF 插件。实测 Mogwai 已加载全部插件并锁住 SVGF DLL，必须先用 Save Config 保存现有会话，才关闭并更新插件；完成后恢复会话并加载新图。
- 实际 Vulkan / Room 与 Cornell 运行，保存同帧 raw/filtered HDR，检查有限性、可视对照以及静态时间波动是否降低。指标不能代替高采样参考图的精度验证，不宣称无偏或消除所有白点。
- 测试关闭 SVGF 的输出与原始相符、Reset、相机移动、场景切换、渲染参数变化和分辨率变化。不把脚本调用控制器当作真实 UI 操作验证。
- 完成后通过当前 Mogwai 的 Load Script 入口加载并选择新图；若 UI 操作受阻，提供已验证的启动入口并明确限制。

## 验证记录

Windows Release / RTX 5080 / Vulkan 实测：

- 编译通过，`tests/svgf/integration.py` 完成 Room、Cornell、返回 Room、关闭/开启、手动清历史、改采样数、相机移动和 640×480 → 400×300 分辨率切换。SVGF 静态帧计数达到 48，移动相机保留历史，其他指定切换后回到 1。
- 保存 15 组 raw / filtered / reference HDR 及显示 PNG。15 张 filtered HDR 全部有限；最终改用 RGBA32Float 后，关闭滤波与同帧 raw 最大差为 0。
- 8 个连续帧的 log1p HDR 时间均方差，raw 为 0.1297592，SVGF 为 0.00117469，比值约 0.00905。这仅表征平滑程度，不代表相对真值的误差减少 99%。原始 24 个非有限通道位置在两侧指标中一致排除，并在 results.json 单独报告。
- 未修改的 PathTracer 在个别 Room 帧输出 NaN，普通 Reference 历史也会受其污染。此轮不改 PathTracer；SVGF 现有 NaN 输入保护生效，不能把参考累积当成已通过有限性验证的真值。此源头问题仍需单独排查。
- 实际查看显示图：墙面噪声明显减少；radiance 模式避免漫反射去调制对玻璃/镜面错误染色，但 1 spp 下桌面纹理、植物和玻璃有明显平滑。不是 NRD 品质等价替代。
- 配置备份 `build/before-svgf-session.py`。Save Config 只导出底层 FBX 路径，恢复脚本改为加载原 `.pyscene` 以恢复材质和环境设置，再应用保存的相机/图参数；原配置文件不改动。
- 最终 `long_run.py` 连续 6000 帧通过：历史为 6000，64/512/2048/6000 帧的 filtered HDR 全部有限，中央墙面均值维持约 0.047–0.048，无黑屏。已查看第 6000 帧显示图。该测试先完成首次场景更新，再关闭相机动画并设定视角，暂停时钟但保留场景动画变换。
- 最终可见窗口已恢复保存的相机及旧图，并选中 PathTracerSVGF / ToneMapperSVGF.dst；实际展开 SVGF 面板看到 Frames since reset = 10475，画面正常。当前场景时钟暂停，相机仍可操作。

可复现：启动 Mogwai `--device-type vulkan --headless --deferred --script F:/tests/svgf/integration.py --width 640 --height 480`，然后用仓库 Python 执行 `tests/svgf/check_results.py`。日志和图像在 `build/svgf-validation*`，设计变更见下一节。

## Vulkan 兼容调整（在修改前记录）

首次实际执行确认 GBufferRaster 因缺少 ROV 支持拒绝 Vulkan 设备。改用 GBufferRT，其他通道保持语义一致。SVGF 的 PositionNormalFwidth 改为可选输入：缺省时在已有深度/法线打包全屏 pass 中，通过世界位置和 guide normal 的 ddx/ddy 生成 `length(abs(ddx)+abs(ddy))` 的变化率（与 Raster 定义核对），写到额外 RG32Float 附件供重投影读取。传入旧 Raster pnFwidth 时仍优先使用原输入。这只是输入适配，滤波核心不变。

第二次实际执行的所有生命周期断言通过，但图像显示原版去调制使用 `max(albedo, 0.001)`、重调制直接乘 `albedo`，导致零 albedo 的玻璃/金属失去能量。先记录后修复：两处使用相同下限；不据此宣称镜面降噪正确。GBufferRT 的背景深度是正大数而 SVGF 假设负深度；用无效 guide normal 将背景标成负深度，最终直接输出原始背景颜色，避免背景被错误调制/滤波。补充零 albedo 和背景通路实际图像检查。

全颜色去调制还会把镜面/透射能量错误地按漫反射 albedo 重新着色（Room 桌面出现黄斑）。增加可选 `Demodulate`（插件默认 true 保持旧图行为，新完整 PathTracer 图显式 false）：false 时过滤去掉 emission 后的 radiance，最终只加回 emission；不会把整个镜面结果乘上漫反射颜色，但会牺牲部分纹理清晰度。仍复用原 SVGF 滤波核，不实现新的信号拆分降噪器。使用文档说明此取舍。

可见窗口验证发现：Animate Scene 开启时每帧清历史，关闭后计数正常增长；长时间后出现黑屏。新增持续运行验证（保存的用户视角，至少 6000 帧）。原输入防护只识别 NaN，不处理 Inf 和历史统计量异常：扩展有限性检查，在重投影历史不合法时拒绝历史，当前样本/亮度平方不合法时丢弃该异常样本。补全重投影纹理读之前的边界检查，并夹紧方差邻域坐标。输出改为 RGBA32Float 避免有效 HDR 在半精度输出中溢出。不截断普通有限 radiance，不改变路径追踪器。启动器的 SVGF 预览暂停场景时间以获得静态预览；运行中加载图不自动改变场景时间，文档提示 Animate Scene。

补充：不能将此前黑屏直接归因为 Inf。关闭整个场景动画还可能改变此 FBX 的节点变换；首次持续测试因此偏离室内视角，虽然有限性通过，但图像验收不通过。最终改为暂停时钟、保留场景变换，并先初始化场景再固定非动画相机；重新完成 6000 帧且实际查看室内墙面。有限性防护属于已知非有限输入的稳健性修正，不声称完全定位原版数值错误或先前黑屏根因。
