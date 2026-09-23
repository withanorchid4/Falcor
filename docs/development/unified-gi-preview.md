# 单窗口 GI 算法切换

2026-09-23，实施前记录。用户要求在一个程序中切换普通 PathTracer、官方 NRD 和传统 Probe。

## 方案

1. 统一入口 `Run-Falcor.cmd` 默认采用 D3D12，加载三个已有 Render Graph，通过 Mogwai 自带 Active Graph 下拉框切换。共用当前场景、相机，只有当前图执行。不改算法或 Mogwai 框架。
2. 新增组合脚本，复用 `PathTracer.py`、官方 `PathTracerNRD.py`、`TraditionalProbeGI.py`。NRD 保留 DLSS Balanced 等官方参数；普通 PathTracer 默认显示普通累积分支；Probe 默认手动 Bake。
3. 原有 NRD、Probe 快捷入口保留为兼容入口，D3D12 下打开相同三张图，只指定初始图。保留 Probe 的场景、模式、样本数及 revision 参数。明确指定 Vulkan 时保留无 NRD 的单图启动方式，NRD + Vulkan 拒绝启动。
4. 切图不会重建图或重载场景，因此 Probe 已烘焙结果应保留；切离 Probe 时其烘焙暂停，切回继续。切场景仍按现有逻辑清除不匹配探针结果。暂停场景时钟，允许相机操作。
5. 先完成集成验证再交付：同一 D3D12 进程逐个切换并输出图像；Probe 手动烘焙、切离暂停及切回保留；切场景后更新所有图。验证用独立缓存文件，避免覆盖用户缓存。更新使用说明。

## 验证结果

- `tests/nrd/graph_switching.py` 已在同一 D3D12 进程通过上述检查，退出码 0，结果在 `build/gi-switch-validation/f33e947d/result.json`。
- Cornell 三张图均渲染，场景对象与相机位置保持一致；Probe 小网格测试烘焙切离时进度不变，切回完成。经过 PathTracer、NRD 和相机移动后，探针仍 Ready，缓存字节不变。
- 换 Room 后三张图均输出图像，Probe 进入未烘焙状态，不覆盖旧缓存。已查看 Probe、普通路径追踪和 NRD 图像；本检查验证切换及状态，不作低样本画质验收。
- PowerShell 语法检查通过；拦截 Start-Process 检查统一启动、NRD/Probe 快捷方式及显式 Vulkan 参数，NRD + Vulkan 正确拒绝。保留从 F: 别名启动的兼容行为。
- 本次未更改 C++ 框架或算法，不需重新编译。当前旧窗口需重新通过统一入口启动一次，之后均在 Active Graph 切换。
