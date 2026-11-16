# 官方 DDGI 示例运行与 Falcor 对照

官方 RTXGI-DDGI 1.3.7 的 Cornell 场景已跑通。统一场景、相机、灯光和主要探针参数后，Falcor 普通 DDGI 的空间分布、活跃探针总数和间接光能量与官方接近。本次结果支持这条接入路径基本正确；未覆盖 WRC、所有材质、大场景和动态场景。

## 启动报错

用户截图中的 `Direct3D12.cpp:2448` 对应 `CreateStateObject()`：官方测试程序创建光追管线失败。首次构建关闭了 NVAPI，但该版本的 shader 编译仍硬编码 `GFX_NVAPI=1`。恢复官方默认 `RTXGISAMPLES_GFX_NVAPI=ON` 后，可以启动并渲染。

随后发现官方程序按枚举顺序选中了 AMD 核显，约 760 帧后在 `timestamps->Map()` 再次报错。为控制测试设备，在设备创建处加入 NVIDIA VendorId 筛选，固定使用本机 RTX 5080。之后原配置连续运行超过一万帧，未重现上述错误。没有采集第二次错误的 HRESULT 或 DRED，不能据此断言其底层驱动根因。

## 代码与测试边界

- 来源：NVIDIA 官方仓库 [v1.3.7](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/tree/v1.3.7)，使用随包提供的 `cornell.glb` 和原始 `cornell.ini` 完成首次运行。
- 与下载的 tag 压缩包核对 346 个文件，唯一源码差异是 `Direct3D12.cpp` 中两行显卡选择适配；补丁保存在 `build/official-ddgi/comparison/nvidia-adapter-only.patch`。官方 shader、SDK 算法与场景未改。
- Falcor 实际部署的 SDK shader/header 共 28 个文件，与官方版本在统一 CRLF/LF 后文本完全相同。
- 依赖使用 DXC 1.7.2207、Agility SDK 1.606.3；原 Packman 下载返回 403，改从 Microsoft 对应发行包取得。
- 对照过程中没有修改 Falcor 产品代码，也没有修复暂缓的 relocation 振荡问题。

## 对照方法

在两边加载同一份官方 GLB。相机位置 `(0.1,1,4)`，朝向 `-Z`，垂直视场 45°；使用官方方向光、黑色天空。分辨率 640×360，关闭 AO、色调映射和抖动，比较纯间接光。

| 项目 | 对照设置 |
|---|---|
| 网格 | 9×9×9，中心 `(0,1,0)`，间距 0.3 |
| 每探针射线 | 256 |
| Relocation / Classification | 都开启 |
| 最小正面距离 | 0.03（适配 Falcor 的硬编码比例） |
| Normal / View bias | 世界距离 0.02 / 0.1 |
| Irradiance / Distance 内部 texel | 6 / 14 |
| Hysteresis | 0.97 |
| Irradiance / Brightness threshold | 0.25 / 0.1 |
| RayData / Irradiance / ProbeData | F32×4 |
| Distance | 官方 F32×2；Falcor F32×4，实际使用前两通道 |
| Scrolling / WRC / RTXDI | 对照时关闭 |

这些是单独保存的对照配置，不是官方默认值。官方默认的最小正面距离为 0.1，且纹理精度、阈值、显示设置不同。Falcor 在 256 和 1024 次更新后导出 EXR；官方预热后通过原生 F1/F2 导出截图和中间纹理。双方随机序列、初始化历史权重及阴影射线偏移实现不同，因此不预期逐像素完全相等。

## 结果与亮度差定位

| 观察项 | 结果 |
|---|---|
| 探针总数 | 双方 729 |
| 活跃探针总数 | 双方 280；未逐探针核对 ID |
| Falcor relocated 数量 | 16 |
| 表面/背景 mask 不同的像素 | 0 |
| Falcor 非有限值 | 0 |
| 原始间接光 RGB 均值比，Falcor / 官方 | 1.0852 / 1.0793 / 1.0861 |
| 计入相机反照率转换差异后的均值比 | 1.0064 / 1.0008 / 1.0073 |
| 同上，像素相对 L1 误差 | 1.62% |

官方 TestHarness 的 `shaders/include/Common.hlsl:32` 中，`LinearToSRGB()` 写成了 `pow(rgb * 1.055, 1/2.4) - 0.055`。标准的高值分支应为 `1.055 * pow(rgb, 1/2.4) - 0.055`。该函数写入相机 GBuffer 后，再由 `SRGBToLinear()` 解码，反照率被压低；例如官方白色材质的红通道从约 0.725 降至 0.672。

按这个公式与 8 位量化预测的 GBuffer 值，与实际导出逐像素相符。它主要解释了约 8% 的亮度差，属于官方示例的相机着色路径，不是 SDK 探针更新算法。分析时用实际 GBuffer 反照率比值换算输出，没有改任一程序的渲染代码。剩余误差包含不同采样序列、阴影偏移、有限收敛和截图量化，未进一步分离各项占比。

官方截图为 UNORM8。为减小暗部量化误差，只开启 +3 档曝光并在分析时除以 8，未发生通道饱和；换算后的量化步长为 `1/(255×8)`。上述数字来自一次收敛后截图，不是跨场景验收阈值。

下图左侧为计入官方相机反照率转换差异后的结果，右侧为 Falcor。两者统一采用 `pow(clamp(12×L),1/2.2)` 提亮展示，指标使用线性数据。

![间接光对照](../../build/official-ddgi/comparison/comparison-albedo-accounted.png)

## 复现与文件

项目根目录下执行：

```powershell
& ./build/official-ddgi/Run-OfficialCornell.ps1
```

该入口运行原始官方 Cornell 配置，使用上述 NVIDIA 显卡选择适配版可执行文件。对照数据在 `build/official-ddgi/comparison/`：

- `original-settings.png`：官方原始配置截图。
- `matched.ini` / `matched-exposed.ini`：统一参数配置及仅提高截图曝光的配置。
- `cornell.pyscene`、`falcor-*.exr`、`falcor-stats.json`：Falcor 场景包装及线性输出。
- `official/`：官方原生导出的截图、GBuffer、探针纹理。
- `image-comparison.json`、`sdk-audit.json`、`source-audit.json`：数值和来源核对。
- `comparison.png`：未计入相机反照率差异的并排图；`comparison-albedo-accounted.png`：计入后的并排图。

生成与分析脚本为 `build/official-ddgi/prepare_comparison.py`、`comparison_render.py`、`analyze.py` 和 `audit_sdk.py`。F1 保存截图，F2 保存中间纹理，数字 2 切换纯间接光。脚本使用项目已有的 `F:` 路径映射。
