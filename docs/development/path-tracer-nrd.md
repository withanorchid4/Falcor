# 官方 PathTracerNRD 接入

## 2026-09-23 默认配置修订（实施前）

用户要求默认使用官方示例配置。之前包装脚本关闭 DLSS、保留 Halton 抖动，会缺少最后的时间抗锯齿重建；因此取消包装脚本对 DLSS 的覆盖，直接沿用官方图全部 Pass 参数，包括 DLSS Enabled / Balanced、Halton 32、PathTracer 1 spp。包装层仅保留加载图及暂停场景时钟，方便静态检查。官方图及算法源码不修改。

同步启动说明和现有集成检查，单独输出到 `build/nrd-dlss-validation`，保留此前 NRD-only 验证记录。验证 D3D12 下 DLSS 实际初始化、Room/Cornell 输出、相机变化及分辨率切换，查看输出图像。下面的 DLSS=False 结果属于修订前历史记录，不代表新的启动默认值。

修订验证已完成：D3D12 集成进程退出码 0，DLSS 启用，Room 256 帧、相机变化、Cornell 与 400×300 分辨率切换均完成；14 张最终 HDR 输出有限、非黑、尺寸正确。已查看 Room 与 Cornell PNG。相同静态 8 帧检查的最终输出时间 log MSE 为 1.46801e-6（此前无 DLSS 为 0.00181863），说明该检查下的连续帧更稳定，不代表动态画质或无偏准确度保证。原始 PathTracer/参考分支仍有之前的非有限值问题。`git diff 759aad03 -- scripts/PathTracerNRD.py` 为空，官方图未改动。现有窗口参数未自动覆盖，重新使用 NRD 入口启动即采用新默认值。

2026-09-23，实施前记录。用户明确停止 SVGF 的继续开发，改为使用官方 NRD 示例。

## 范围与顺序

1. 保留官方 `scripts/PathTracerNRD.py`、PathTracer 和 NRDPass 原始算法与信号连线。它分别处理漫反射/粗糙镜面、理想反射、透射，并在反射率重调制后输出；包含一个普通累积参考分支。
2. 先重现本机 D3D12 初始化问题，使用项目内的配置或依赖修正使设备正常创建。NRDPass 明确要求 D3D12；不移植到 Vulkan，也不为此擅自修改系统安全设置或驱动。
3. 在单独启动包装脚本中加载官方图，默认关闭可选 DLSS，保持原生分辨率以隔离 NRD 效果。明确记录官方示例 maxIntensity=250 的预处理及残余信号选择，不把输出称为无偏参考。官方图本身不改动。
4. 加入明确的 NRD 启动入口；保留当前场景/相机的配置备份。GPU API 无法在现有进程内切换，需要新的 D3D12 进程。先验证后台运行，之后展示程序。
5. 验证 Room 与 Cornell 场景、持续静态帧、相机变化、原生分辨率 HDR 输出有效性，并实际查看纹理/玻璃/墙面。报告已验证结果及仍存在的限制，不用单纯噪声下降代替画质验收。

SVGF 的时间/空间独立开关请求已由用户取消；未开始相应代码修改。后续本地 SVGF 接入已按用户要求清理，见 `remove-svgf-integration.md`。

## D3D12 初始化诊断及修复计划

已复现设备失败。首先发现只构建 Mogwai 的流程没有部署 `falcor-copy-files` 目标，导致 D3D12 子目录缺失；执行该目标后仍失败。隔离测试：系统 D3D12CreateDevice 成功；最小原生程序导出 SDK 717 并加载项目同版预览运行库，返回 0x887e0003；改为微软同批发布的正式版 1.616.0 / SDK 616 后成功。因此将项目 Agility 依赖及对应导出版本一起调整为 616，并将运行库复制目标纳入 Falcor 构建依赖，避免仅构建 Mogwai 时漏部署。保持系统配置和驱动不变。实验性功能警告在 Slang 2025.13.2 源码中不是致命返回，不能将它当作唯一原因。

参考：微软 https://devblogs.microsoft.com/directx/agility-sdk-1-717-preview-and-1-616-retail/ ，以及本地 `build/nrd-device-probe*.cpp` 的独立实测。NRD 不依赖 SDK 717 新增的预览特性；正式版的实际构建及渲染仍需验证。

## 验证结果

- 正式版 SDK 切换后 Release 构建成功。Mogwai 日志确认 RTX 5080 / Direct3D 12 / SM6.8；未修改系统开发者设置、驱动或 Windows 安全设置。
- `tests/nrd/integration.py` 实测 Room 256 帧、相机移动、Cornell、640×360 → 400×300 分辨率切换。包装脚本 DLSS=False；NRD 默认 1 spp，官方 NRD/PathTracer/图文件相对上游无改动。
- `tests/nrd/check_results.py` 检查 14 张 NRD HDR，全部为有限数，尺寸正确且非黑屏。8 个连续静态帧 log1p HDR 时间均方差从原始 0.0916101 降至 NRD 0.00181863；这只是时间平滑指标，且包含官方亮度截断影响，不是准确度指标。
- 已查看 Room 的 NRD/参考 PNG 与 Cornell PNG：地板与桌面木纹保留，墙面噪声下降；玻璃、植物与窗边仍有残余噪声/局部瑕疵。没有声称完全消除白点或达到离线真值。
- 原始 PathTracer 在 Room 部分帧仍出现非有限通道，参考累积保留这些异常（结果 JSON 有详细计数）。NRD 输出通过有限性检查，不代表路径追踪源头问题已经修复。
- 窗口检查时旧 Mogwai 已关闭，未新建“当前会话已备份”的假记录。此前 `build/before-svgf-reference-fix.py` 备份继续保留；本次通过新 NRD 入口打开 Room。
- 实际通过 `Run-Falcor.ps1 -Renderer NRD -Scene Room` 启动可见窗口，确认 Active Graph=PathTracerNRD、Output=ToneMapperNRD.dst。原生 1280×720 默认视角下木桌、地板纹理清晰可辨，玻璃透射可见，窗边/玻璃局部仍有残余噪声。

复现：`Mogwai.exe --device-type d3d12 --headless --deferred --script F:/tests/nrd/integration.py --width 640 --height 360`，随后用仓库 Python 运行 `tests/nrd/check_results.py`。图像、日志、数值结果在 `build/nrd-validation*`。
