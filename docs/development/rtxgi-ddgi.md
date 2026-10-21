# RTXGI-DDGI 接入

`RTXGIDDGI` 是统一预览入口中的第四个独立渲染图，使用 NVIDIA [RTXGI-DDGI](https://github.com/NVIDIAGameWorks/RTXGI-DDGI) 的动态探针方案。Falcor 负责场景、三角形光线追踪、材质与灯光采样，DDGI 负责探针辐照度、距离矩、历史融合、重定位、分类和表面查询。传统 `TraditionalProbeGI` 仍用于静态烘焙对照。

构建通过 `cmake/rtxgi-ddgi.cmake` 下载固定版本 v1.3.7（提交 `c233266e95931231961f35c842c78e7c4bdc50cf`），并验证 SHA-256。SDK 解压到忽略的构建目录。此适配调用 SDK 原始着色器内核，由 Falcor 分配和绑定 GPU 资源，不编译 SDK 自带的原生 D3D12/Vulkan 库和测试程序。首次配置需联网；后续使用构建目录中的依赖缓存。

## 启动与切换

```powershell
.\Run-Falcor.cmd -Renderer DDGI -Scene Cornell
.\Run-Falcor.cmd -Renderer DDGI -Scene Room
```

后端为 D3D12。普通 `Run-Falcor.cmd` 也会加载 DDGI，可在 **Graphs → Active Graph → RTXGIDDGI** 切换。最终显示输出为 `Display.dst`。四个图共享场景和相机，只有当前图执行；切走 DDGI 会暂停更新，切回后保留已有历史，换场景则重建体积并重新收敛。

DDGI 无需手动 Bake，也不读取或写入静态探针缓存。移动相机不会重烘焙；光源和材质变化通过逐帧更新逐渐传播。历史权重较高时，明暗变化之后会有收敛延迟。场景几何发生较大变化后，可以重置历史以消除旧照明残留。

画面表面的直接照明默认使用 Falcor 已有的 `RTXDIPass` / RTXDI 1.3.0-falcor。`Visibility` 同时提供可见性和屏幕运动向量，RTXDI 通过 ReSTIR DI 做时空重采样；本图使用 `SpatiotemporalResampling` 和带可见性射线的 `RayTraced` 偏差校正，其余参数沿用现有模块默认值。`DirectLighting.color` 已含直接照明、自发光和环境背景，DDGI 只向它加上 `DDGI.indirect`，不会再次叠加自发光或背景。

探针射线仍在命中点独立计算直接光，再加入上一帧 DDGI 的漫反射反馈；屏幕空间 RTXDI reservoir 不用于任意探针命中点。射线直接命中发光面或逃逸到环境时，不把这部分直接照明再次写入探针。这样 `DDGI.indirect` 只表示至少经过一次额外表面散射的漫反射贡献，避免和画面的直接光重复相加。两个 NVIDIA SDK 的原始算法内核均保持不变。

重置后的历史权重从 `updatedFrames / (updatedFrames + 1)` 逐渐提高，最大不超过设置的 `hysteresis`；前 32 帧关闭 SDK 的增亮限幅，之后恢复。这可加快冷启动收敛，同时保留稳定运行时的历史融合。ReSTIR DI 改善直接光采样，但不等同于降噪器；本图尚未接入 NRD、TAA 或其他最终图像降噪，半影、反光和运动边界仍可能有噪声。

在 `DDGI` 面板关闭 **Use RTXDI direct light**，可原位对照此前每类光源单次采样的直接光；切换不会清空探针历史。RTXDI 采样参数在 `DirectLighting` 面板调整。这个对照开关只改变合成所用的直接光，连接着的 RTXDI pass 仍会执行，因此不能用它直接测量旧版的独立运行耗时。**Indirect only** 会隐藏所有直接光、自发光和环境背景。

Room 原有环境图含非有限 HDR 像素。DDGI 与 RTXDI 的 Falcor 适配层各维护一份 GPU 副本，将非有限或负的 HDR 通道置零后生成采样分布；各自的实际照明查询与背景查询使用相同的清理数据，并保留场景的环境强度和旋转。这避免个别异常 HDR 像素污染整个采样层级，不会修改场景或磁盘上的原始资产。

## 初始参数与接口

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `gridCounts` | `(8, 6, 8)` | 单个规则体积，共 384 个探针 |
| `raysPerProbe` | `256` | 每探针每次更新的射线数 |
| `hysteresis` | `0.97` | 历史权重；增大可降低噪声，减小可加快响应 |
| `normalBias`, `viewBias` | `0.05`, `0.05` | 查询点沿法线与视线的偏移，按最小探针间距的比例配置 |
| `autoBounds` | `true` | 从场景范围生成探针体积 |
| `enableRelocation` | `true` | 使用几何距离信息调整探针位置 |
| `enableClassification` | `true` | 分类并跳过不适合更新的探针 |
| `updateEnabled` | `true` | 暂停或恢复逐帧更新，保留当前结果 |
| `showProbes` | `false` | 显示探针位置供布局检查 |
| `indirectOnly` | `false` | 只显示间接漫反射贡献 |
| `useRTXDI` | `true` | 使用已连接的 RTXDI 直接光；关闭或未连接输入时使用旧采样器 |
| `intensity` | `1.0` | 间接光照输出倍率 |

图定义位于 `scripts/RTXGIDDGI.py`，内部 pass 名为 `DDGI`，直接光 pass 名为 `DirectLighting`。输入 `vbuffer` / `viewW` 来自 `VBufferRT`；可选输入 `directLighting` 接收已含自发光和背景的外部直接光。输出 `color` 为合成 HDR，`indirect` 为间接漫反射 HDR，均在色调映射之前。不连接 `directLighting` 的已有自定义图仍可独立运行。

脚本可使用以下接口做原位控制，避免创建新 pass 丢失历史：

```python
p = m.activeGraph.getPass("DDGI")
p.set_properties({"updateEnabled": False})
p.set_properties({"updateEnabled": True})
p.set_properties({"useRTXDI": False})  # 原位对照旧直接光采样
p.set_properties({"useRTXDI": True})
p.reset()  # 在下一次执行时清空历史
print(p.updatedFrames, p.status)
print(p.stats)  # 按需 GPU 回读：数量、有限性和 irradianceMax
```

`stats` 提供 `updatedFrames`、`totalProbes`、`activeProbes`、`relocatedProbes`、`finite` 与 `irradianceMax`，并检查射线、距离矩与辐照度纹理中的有限性。材质、直接光、历史查询和最终射线结果的异常输入会计入对应诊断项，用于定位无效数据。统计回读会同步 GPU，适用于诊断，不应每帧调用做性能测量。

## 当前边界

- 本版接入 D3D12、单个自动包围体积；SDK 自身的 Vulkan 支持不代表此 Falcor 适配已支持 Vulkan。显式选择 DDGI + Vulkan 会被启动器拒绝。
- 支持三角形场景和 alpha test。其他几何类型需要补充相应追踪实现。
- 当前 RTXDI pass 使用针孔视线；默认图固定使用 Center 像素采样。此组合尚未接入薄透镜景深或像素抗锯齿。
- 主要近似漫反射间接光。镜面多次反射、正确透射和玻璃等效果不能与完整 PathTracer 等价。
- 自动范围方便初次接入，但不会替代场景布局设计。大场景、薄墙和复杂室内需要调整探针密度与查询偏移，重定位和距离矩不能保证消除所有漏光。
- 默认 384 × 256 条探针射线加上更新与屏幕查询有持续开销；本版没有跨体积调度、滚动体积、场景缓存或预算驱动更新。
- 静态探针模式中的 “DDGI weights” 只是一种插值对照；它不等同于这里逐帧运行的 RTXGI-DDGI。

## 可复现验证

使用本机已有的 Python 和 `F:` 工程别名运行：

```powershell
python F:\tests\ddgi\run_validation.py
```

运行器以 `--device-type d3d12 --headless --deferred` 启动 Release Mogwai，基础分辨率为 320 × 240，所有日志、HDR 与临时静态缓存均写入新的 `build/ddgi-validation/<时间-随机标识>/`。不会读取或覆盖用户原有探针缓存。

`integration.py` 在一个进程中执行四图切换、Cornell/Room 场景切换、光源变化、冻结与恢复、重置、重定位与分类开关及 400 × 300 分辨率切换。Cornell 将发光材质强度降至四分之一，Room 将环境光强度降至四分之一，再恢复原值。PathTracer 以每帧 8 spp、64 帧累积提供明暗趋势对照。

`check_results.py` 检查线性 HDR 全部有限且有非零光照、冻结后的间接光一致、调暗及恢复方向正确，并记录 DDGI 与 PathTracer 的均值响应。它还检查真实 GPU 探针状态，不能仅以启用参数证明重定位和分类有效。这是功能验证，不是无偏画质或性能基准。

复用已完成的渲染结果：

```powershell
python F:\tests\ddgi\run_validation.py --reuse-renders F:\build\ddgi-validation\<运行目录>
```

实际执行结果以对应运行目录的 `integration.json` 和 `results.json` 为准；只有完成 GPU 渲染和图像检查后才能报告通过。

RTXDI 合成与直接光采样的专项验证：

```powershell
python F:\tests\ddgi\run_rtxdi_validation.py
```

输出在独立的 `build/rtxdi-ddgi-validation/<时间-随机标识>/`。在 Cornell 和 Room 上检查同帧 `DDGI.color = DirectLighting.color + DDGI.indirect`、间接光开关、旧采样器切换、冻结历史、相机移动与返回、灯光调暗及恢复、401 × 301 奇数尺寸和无外部输入的兼容路径。每场景两种采样方式各捕获 32 张连续原始 HDR，报告时域方差；重采样带来的样本相关性也会降低该指标，不能将它视作对参考图的误差或等预算性能提升。GPU 计时单独捕获，不包含截图读回。

## 2026-10-21 本机验证结果

在 NVIDIA GeForce RTX 5080、D3D12、Release Mogwai 上完成验证。本机产物位于 `build/ddgi-validation/20261021-123151-a7ba66ea/`，运行器与图像检查均正常退出。

- 四个渲染图在同一进程中执行，共享场景和相机；切离 DDGI 不更新历史，切回继续。
- Cornell 和 Room 的场景切换、光源调暗和恢复、冻结及恢复、冻结状态下重置、探针调试显示以及分辨率切换均通过。
- 30 张 DDGI 线性 HDR 捕获全部有限且非零；射线、距离矩、探针数据和辐照度回读无非有限值。
- 两个场景在所有统计阶段的材质、直接光、历史查询与最终射线异常拒绝计数均为零。
- 禁用重定位与分类并重置后，两场景均为 384 个活动探针、0 个位移探针；启用后的实际状态见下表。

| 测量 | Cornell | Room |
| --- | --- | --- |
| 开启分类后活动探针 / 总数 | 292 / 384 | 277 / 384 |
| 开启重定位后有位移的探针 | 23 | 24 |
| 冻结期间间接 HDR 最大绝对差 | `1.49e-7` | `5.96e-8` |
| 光源降至四分之一、更新 96 帧后的间接均值 / 基线 | 0.3364 | 0.3630 |
| 同次光源变化的 PathTracer 全图均值 / 基线 | 0.2499 | 0.2624 |
| 恢复原光源并更新 96 帧后的间接均值 / 调暗结果 | 2.4604 | 1.9345 |

上述明暗比例证明动态响应方向正确，也显示 96 帧后历史尚未完全回到稳态，不能据此宣称与 PathTracer 等价。已人工查看两个场景的显示捕获：Cornell 可见间接照明和颜色传播；Room 的玻璃器皿、镜面和透射效果与 PathTracer 差别明显，直接光单帧采样也有可见噪声。这些是当前漫反射方案及未接最终图像降噪的边界，验证不覆盖任意场景画质。

## RTXDI 接入验证（2026-10-21）

Release 全量构建和 RTXDI 专项验证通过，使用 RTX 5080 / D3D12。专项产物在 `build/rtxdi-ddgi-validation/20261021-152747-96c9f71a/`。

原有四图切换、双场景、动态探针与重置回归也通过，产物在 `build/ddgi-validation/20261021-152859-20501611/`，其中 30 张 DDGI HDR 检查通过。

- 650 张线性 HDR 输出全部有限。同帧合成最大绝对误差 `3.81e-6`；未出现直接光、自发光或背景重复叠加。
- 开关 RTXDI / Indirect only 保持冻结的间接光不变，Cornell / Room 最大绝对差分别为 `2.09e-7` / `7.45e-8`。未连接外部直接光的兼容图也正常运行。
- 场景切换、相机移动及返回、401 × 301 尺寸切换、探针恢复更新均完成。相机测试检查有限性和合成，不构成无拖影证明。
- 将源光强降到四分之一，扣除自发光和背景后的表面直接光均值分别变为约 `0.246` / `0.258` 倍；恢复后回到约 `0.984` / `1.009` 倍。
- 在 320 × 240、冻结探针、每模式连续 32 帧的测试中，RTXDI / 旧采样的平均像素亮度时域方差比为 Cornell `0.742`、Room `0.0257`。这是原始信号的时域波动，包含样本相关性影响，不是参考图误差，也不是等成本比较。
- 同尺寸下 RTXDI 直接光 pass 的 GPU 中位时间约为 Cornell `0.094 ms`、Room `0.107 ms`；不含动态探针更新成本，不能外推为 720p 或完整实时 GI 帧率。

本次只接入 ReSTIR DI 采样，最终画面仍未接 NRD/TAA；单面光源半影等区域保留可见噪声。
