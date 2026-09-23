# 传统光照探针：使用与结果

## 墙面硬边修复与对照开关

预览脚本现在默认开启 **Probes → Distance visibility → Reject back-facing probes**。它在原朝向权重上增加平滑半球抑制：表面背面的 Probe 不再保留最低权重，接近切平面的方向平滑淡出。已在保存的问题快照和另一个房间视角验证，消除了该墙面上由明亮墙后 Probe 引起的块状硬边；不增加射线或距离图读取，不需要重新 Bake。

- 保持 **Enable visibility** 和 **Normal direction weight** 开启；关闭 **Reject back-facing probes** 可对比原效果。
- **Distance map filtering → Smooth moments** 是另一项独立实验：对同样四个 texel 使用 smoothstep 权重重建一阶/二阶矩，减轻方差的网格硬边。它只能使本次暗块变软，不能单独消除漏光，因此默认仍为 Bilinear。
- 两个开关会保存到图和问题快照。旧图未指定新选项时仍保持旧行为；新启动的预览图默认开启背面抑制。
- 这不是完整遮挡替代：位于正面但被另一面墙挡住的 Probe 仍依赖距离矩。覆盖不足时可能变暗，墙角、装饰线和其他漏光仍需单独排查。

实验与验证记录见 [硬边修复文档](docs/development/probe-hard-edge-fix.md)。

## 保存问题视角，使用脚本重现

发现墙面问题时，保持当前相机和参数，可先右键选点，再通过 **File → Load Script** 运行 `F:/scripts/SaveProbeSnapshot.py`。要求Probe已Ready、未在Bake，Display关闭Auto Exposure。结果保存到 `F:/build/probe-issues/日期时间-ID/`，`latest.txt` 指向最近一次成功保存的案例。

快照包含相机位置/角度/焦距、分辨率、当前图和参数、选点及八探针数据、缓存副本与哈希、环境/常用材质与光源属性、干净PNG及HDR/EXR。保存过程短暂关闭调试覆盖层并冻结时间，随后恢复；不操作相机、不重烘焙。

之后复现不需要在程序中点击。在项目目录执行：

```powershell
.\Replay-ProbeSnapshot.ps1 -Snapshot 'F:\build\probe-issues\日期时间-ID'
```

它启动独立headless Mogwai，恢复状态、加载快照缓存、渲染后退出，不操作已打开的窗口。结果位于该案例的 `runs/日期时间-ID/`：`display.png`、`before-after.png`（左原始/右重放）、`difference-x8.png`、`comparison.json`（HDR误差及选点前后数据）、`render.json`（实际参数与DLL/shader哈希）。无代码/参数变化时，先确认误差接近零，再使用这个案例验证修复。

若要显式调整参数，写一个JSON文件（例如 `{"normalBias":0.06,"viewBias":0.24}`），传入 `-Overrides 参数文件.json`。若修改烘焙算法，额外传 `-Rebake`，新缓存只写本次run的 `rebaked.shprobe`，原案例不变。仅改变运行时算法时保持原缓存。

第一版针对标准Probe图，固定曝光；不保存PathTracer/NRD历史，不是完整场景资产打包。几何和纹理仍依赖原文件；交互式纹理替换、未落盘的几何编辑、自定义材质内部数据不保证复原。场景入口/主模型/环境图和快照缓存发生已检测到的变化时拒绝重放。详见 [开发文档](docs/development/probe-issue-replay.md)。

## 距离矩防漏光（新增）

本轮预览脚本默认启用 **Probes → Distance map bake settings → Distance bake mode → Angular weighted (DDGI-style)**。先用 **Distance rays per probe = 2048、Angular sharpness = 50**，然后重新 **Bake**。角度加权只发生在烘焙阶段；运行时仍每 Probe 一次切比雪夫。需要对比旧方式时切回 **Texel-local**，恢复原分辨率/每texel样本数后 Load matching cache。

角度滤波用 `max(dot(texelDirection, rayDirection),0)^sharpness` 分别加权平均距离和距离平方。指数越大范围越窄；可能减轻不连续感，也可能把近远表面的距离混合而增加漏光，不保证单独消除墙面伪影。本版没有额外高斯模糊或DDGI动态历史混合。

当前基础方差实验采用 `max(E[d²] - E[d]², 0) + 1e-6`，在距离矩插值后相加。**Base variance (normalized)** 可调；选点中的 `variance` 仍表示未加基础值的测得方差，面板另行列出基础值。已有缓存直接使用，无需重烘焙。零方差位置与原先1e-6下限效果相同；不能据此保证消除明暗边界。

### Normal / View bias 对比

在 **Probes** 面板调整 **Normal bias** 与 **View bias**，分别沿表面法线和朝相机方向偏移查询点：

`Q = P + minProbeSpacing * (normalBias * N + viewBias * normalize(cameraPosition - P))`

两个系数独立调节，组合向量不再归一化。默认仍为 `0.05 / 0`。点击 **Normal/view formula preset** 设置为 `0.06 / 0.24`，等价于截图中的 `0.3 * (0.2N + 0.8V)`；**Reset bias defaults** 恢复原默认值。均无需重新 Bake，不增加距离图采样和切比雪夫次数。

固定一个问题选点，对比默认、纯 normal、组合 bias 下的 **Q point / mean / HIT / V / w**。黄色线段表示完整 normal+view 偏移；面板显示 Q 世界坐标。开启 view bias 后移动相机会自动刷新已选世界点的数据。bias 同时改变查询方向、距离及网格权重，不保证 d 与 mean 一直同号；过大的偏移可能穿过其他几何，view bias 也会引入随视角变化的光照。本版未增加深度检测或偏移回退。

开发与验证见 [normal/view bias 文档](docs/development/probe-normal-view-bias.md)。

### 实时射线参考与选点距离对照

在 **Probes → Distance visibility → Visibility method** 中切换：

- **Distance moments**：默认，使用烘焙距离矩和切比雪夫权重。
- **Ray traced (debug)**：从每个邻近 Probe 向偏移查询点发射遮挡射线，被挡住时权重为 0；每像素最多增加 8 条射线，用于检查距离矩误判，可能明显降低帧率。

两种模式共用同一份已烘焙 SH 和距离图，切换无需重新 Bake。`Enable visibility` 总开关关闭时恢复原三线性插值；`Visibility power` / `Base variance` 只影响距离矩模式。

在 Debugging 开启 **Pick surface (right click)** 后右键选点，每个邻居显示：

- **Q**：经过 Normal + View bias 的实际 GI 查询点；**P**：原始选中表面点。
- **stored mean**：按 Probe→对应点方向查询距离矩。默认 Bilinear 混合附近4个 texel 的一阶/二阶矩；Point 直接读取对应1个 texel。烘焙数据可来自 Texel-local 独立采样或 Angular weighted 方向加权；运行时读取模式与烘焙模式独立。
- **point**：Probe 到对应点的距离；**HIT**：从 Probe 沿相同方向发射射线所得最近交点距离，单位均为世界单位。
- **MISS**：在射线范围内没有交点，不能理解为遮挡距离恰好等于最大范围。范围至少为距离图最大范围，也覆盖查询点。
- **V moment / ray / used**：距离矩估计、硬射线判断、当前真正采用的可见性；**w** 仍是归一化后的最终光照权重。

例如 `HIT < point` 且 `stored mean > point` 时（忽略很小的端点容差），射线已经发现遮挡，但距离矩认为可见；射线模式应把该邻居权重归零。若 P 与 Q 的判断不同，先检查 Normal bias。所有邻居都被遮挡时 Probe 光照会变黑；墙内 Probe、覆盖不足及硬遮挡切换仍需另外处理。此参考不计算玻璃透射/折射。

实现及验证见 [射线可见性开发文档](docs/development/probe-ray-visibility.md)。

探针现在同时烘焙 SH 光照和八面体距离矩。运行时使用三线性权重、法线方向权重与切比雪夫可见性权重混合，降低被墙遮挡的 Probe 的贡献。仍是静态烘焙，不是完整动态 DDGI。

两种烘焙模式都将所有 Probe 的 SH 和距离矩保存在一个 `.shprobe` 文件中。Texel-local 沿用 version 3、自动后缀 `-texel-local`；Angular weighted 使用 version 4、后缀 `-angular`，两份缓存不会互相覆盖。version 1/2 仍要求重烘焙；新模式不能直接加载旧模式的数据。默认 SH 每 Probe 2048 样本；先完成 SH，再完成距离阶段才保存。

| 面板 | 参数及作用 |
| --- | --- |
| Distance map bake settings | Interior resolution 可调4..128，默认14；Distance bake mode 选择 Angular weighted 或 Texel-local。Angular：Distance rays per probe 默认2048，可调1..65536；Angular sharpness 默认50，可调1..256，同一条球面射线按夹角权重贡献给多个texel。Texel-local：每texel独立射线默认16，可调1..2048。两种模式的距离射线都与 SH 样本独立。Distance range 默认为格子对角线的2倍。修改后重新 Bake。384个 Probe 在128分辨率时 atlas 约占103.1 MiB。 |
| Distance visibility → Distance map filtering | 默认 Bilinear，也可选 Point。即时切换、不重烘焙，兼容现有version 3缓存。八面体边缘折叠回同一Probe，避免采到空边界或邻居Probe。生产可见性、P/Q调试及距离图预览共用该选项。Q texel仍显示包含方向的texel，Bilinear实际读取周围4个。 |
| Distance visibility | Enable visibility 默认开启；关闭恢复原三线性插值。Visibility method 可切换距离矩或射线参考。Normal direction weight 可单独关闭。距离矩模式下 Visibility power 越大抑制越强，Base variance 默认1e-6，统一加在插值后的非负方差上，越大越宽松（不再是最小值截断）。修改不重烘焙。 |
| Debugging → Surface view | Visibility support 显示估计的可见性支持程度；Selected probe: mean distance / distance stddev 显示选中 Probe 的完整八面体图，亮度按最大距离归一化。 |
| Debugging → Pick surface | 右键选点，显示 tri（原权重）、三种 V、w（最终权重）、P/Q 的距离均值/方差与真实 HIT。连线颜色来自 Probe→Q 的最近交点判断，便于发现估计与真实遮挡不一致。 |

距离使用独立射线的最近交点，不是多次反弹的路径长度。未命中按最大距离；透明材质在本版距离图中也算几何遮挡。距离图分辨率有限，低样本、薄几何或墙内探针仍可能出现瑕疵；本版未做 Probe relocation。所有权重都很小时会衰减为暗色，避免重新放大被遮挡 Probe 的残余。角度模式实现及验证见 [方向加权恢复文档](docs/development/probe-angular-restore.md)，独立模式见 [texel 内采样开发文档](docs/development/probe-texel-local-distance.md)。

这是规则网格 + 9 项 RGB 球谐的静态漫反射光照探针实现。先烘焙，再从文件加载并实时采样。开发顺序与算法约定见 [开发契约](C:/Users/Admin/Desktop/实时GI/Falcor/docs/development/traditional-probes.md)。

## 启动

统一入口为 `Run-Falcor.cmd`，在 **Active Graph** 选择 `TraditionalProbeGI` 即可；同一窗口可切回 PathTracer 或 PathTracerNRD。原来的 `Run-ProbeGI.cmd` 保留为快捷方式，默认打开 Cornell、选中 Probe 并等待手动操作，不会自动 Bake。未烘焙时显示材质颜色预览，面板标为 `Unbaked material preview`，方便观察场景；该预览不是 GI 结果。

切换 Active Graph 不会清掉已烘焙探针。烘焙期间切到其他图会暂停烘焙，切回继续；只有当前图执行。

### 在程序内切场景和手动 Bake

1. 使用 **File → Load Scene**，或 **Ctrl+Shift+O**，选择新的 `.pyscene` 场景文件。选择窗口只显示该后缀的文件，文件夹仍可进入。已有场景在 `F:\media\test_scenes\` 和 `F:\media\Arcade\` 下。Falcor 仍支持通过导入器加载 OBJ、FBX、glTF 等格式，可通过命令行或拖放加载。
2. 在渲染图控制面板展开 **Probes** Pass，调整下面的参数。若看不到图控制面板，可按 F6 切换显示。
3. 点击 **Bake**。烘焙期间显示每探针已完成样本数；可点 **Cancel bake** 取消，或点 **Restart bake** 从头开始。
4. 完成后自动保存并显示探针照明。需要使用以前的结果时，设置相同参数后点 **Load matching cache**；加载不匹配会在面板提示，程序不会退出。

换场景会清掉旧场景的探针、重置进度并自动适配新范围；样本数和网格密度等参数保留。新场景仍然等待你点击 Bake。可以在同一个窗口里反复切换，无需重启。

通过本地启动器运行时，场景选择窗口默认打开 `F:\media`（即项目的 `media` 目录）。常用文件：

- Cornell：`F:\media\test_scenes\cornell_box.pyscene`
- 灰白室内：`F:\media\test_scenes\grey_and_white_room\grey_and_white_room.pyscene`
- Arcade：`F:\media\Arcade\Arcade.pyscene`

需要换成自己的默认目录时，修改启动脚本中的 `$env:FALCOR_SCENE_FOLDER`。这只影响场景选择窗口，不会改变场景资产搜索路径。

| 面板参数 | 含义 | 修改后的行为 |
| --- | --- | --- |
| Grid counts XYZ | 每个轴的探针数量，2..32 | 旧结果失效，等待 Bake |
| Fit bounds to scene | 自动使用场景包围盒向内缩 5% 的范围 | 旧结果失效，等待 Bake |
| Grid min / Grid max | 关闭自动范围后设置世界坐标边界 | 旧结果失效；边界非法时提示并禁用 Bake/Load |
| SH samples per probe | 每个探针的光照路径总样本数，1..65536；不是每 texel 的距离样本 | 旧结果失效，等待 Bake |
| Samples per frame | 每帧每个探针的工作量，1..64 | 可在烘焙中调整，保留进度；越大越可能影响交互流畅度 |
| Max bounces | 探针路径允许的反射继续次数，0..8 | 旧结果失效，等待 Bake |
| Scene revision | 外部模型、贴图等资产的手动版本标签 | 旧结果失效，等待 Bake |
| Probe intensity / Normal bias / View bias | 实时光照强度、法线/朝相机的采样偏移 | 即时生效，不重烘焙 |

修改影响烘焙的参数会中止正在进行的 Bake，防止不同参数的样本混在一起。只有完整烘焙才写缓存，取消不会覆盖已有缓存。

### 可选命令行方式

```powershell
# 默认手动模式
.\Run-ProbeGI.cmd -Scene Cornell -Mode manual

# 自动开始烘焙，完成后自动保存并继续显示
.\Run-ProbeGI.cmd -Scene Cornell -Mode bake

# 只从文件加载；缺失或不匹配时会报错
.\Run-ProbeGI.cmd -Scene Cornell -Mode load

# 其他已有场景，分别保存缓存
.\Run-ProbeGI.cmd -Scene Room -Mode auto
.\Run-ProbeGI.cmd -Scene Arcade -Mode auto

# 增加球面采样数以降低烘焙噪声；以后 load 时使用同样的 Samples
.\Run-ProbeGI.cmd -Scene Cornell -Mode bake -Samples 8192
.\Run-ProbeGI.cmd -Scene Cornell -Mode load -Samples 8192
```

窗口内还可操作 `Enable probes`、`Probe lighting only` 和 `Preview unbaked surfaces`。勾选只看探针贡献时，直接光、可见发光面和环境背景不会混入该调试图；没有有效探针时该输出为黑色。关闭未烘焙预览后，未烘焙状态只显示直接解析光和表面自发光。

启动器默认 Vulkan，沿用 F: 映射和原有 UTF-8 修复。每次命令新开一个窗口，不要让多个烘焙进程写同一个缓存文件。

## 数据与参数

默认8×6×8，共384个探针。SH阶段：每 Probe 2048样本、最多3次反射继续，每帧每 Probe 16条路径，共128帧。距离阶段：每 texel 独立16条最近命中射线，按批次额外执行，不计算光照反弹；单次派发最多8192 texel / 65536射线。两个阶段都完成才 Ready。实际耗时取决于分辨率、样本数、场景和设备。

交互缓存保存为 `build/probes/<场景文件名>-<路径标识>-texel-local.shprobe`，完整位置显示在面板中。不同场景使用不同文件，切换场景不会互相覆盖。高级脚本仍可显式指定 `cacheFile`；原有 `cornell.shprobe` 属于显式文件，可通过该属性继续使用。自动命名不会删除旧文件。

缓存是带版本与元数据的文本文件，保存平均入射辐亮度 SH 和归一化距离的一阶/二阶矩。完成后只在 GPU 上查图、加权插值与卷积，不会继续追踪探针路径，也不逐帧读回 CPU。相机可见性和解析光源阴影仍使用光追。

通常直接在面板改参数即可。需要保存自己的默认配置时，也可修改 `scripts/TraditionalProbeGI.py`，例如增加：

```python
"gridCounts": uint3(12, 8, 12),
"gridMin": float3(-0.25, 0.03, -0.25),
"gridMax": float3(0.25, 0.52, 0.25),
```

范围使用世界坐标。这组数值仅示范接近当前 Cornell 尺寸的配置，不能直接用于其他场景。网格每轴至少 2，最多 32。默认范围从场景包围盒向内缩 5%，不会识别实体内部，也不会自动把探针移动到空处。采样位置超出范围时使用边界探针。

修改网格、样本数或反弹数后，原缓存会不匹配。修改外部贴图、模型或灯光脚本后，强制 bake，并通过 `-Revision 2` 等给资产设置新版本；重新 load 时使用相同 Revision。缓存检查包含主场景路径、修改时间和设置，不是完整外部资产哈希。

## 已实现的光照分工

- 探针提供漫反射的环境、自发光面照明与多次反射贡献。
- 解析光源在可见表面仍计算直接光，在探针路径中计算经其他表面反射后的光。
- 屏幕直接可见的发光面单独输出自身 emission。
- 实时图没有无限时域累积。开关探针可以直接观察实际单帧贡献。

Cornell 主要使用发光面照明，因此关闭探针后房间大部分变黑、发光面保留，是这套分工的预期结果，不能把关闭图当作完整“直接光渲染器”。

## 第一版的限制

这是静态漫反射近似，不提供镜面间接反射或正确透射。SH 只有低频方向信息；有限采样有噪声，距离矩权重能缓解跨墙混光，但有限角分辨率和实体内探针仍会造成误差。增大采样数能减少 Monte Carlo 噪声，不能独自解决这些结构性问题。

相机移动和窗口尺寸变化不要求重新烘焙。运行时修改灯光、材质或几何后，插件会清掉失效数据，提示再次点击 Bake，不再要求退出程序。动态物体和连续动画不是本版支持范围；烘焙前请暂停动画，否则变化会不断使正在烘焙的数据失效。

## 实现入口

| 文件 | 用途 |
| --- | --- |
| `Source/RenderPasses/TraditionalProbeGI/TraditionalProbeGI.cpp` | 参数、场景初始化、缓存读写、分批烘焙与实时派发 |
| `TraditionalProbeGI.rt.slang`（同目录） | `bakeProbe()`、`sampleProbeIrradiance()`、`rayGen()` 以及材质/求交辅助逻辑 |
| `ProbeSH.slang`（同目录） | 固定顺序的 SH 基函数与余弦卷积系数 |
| `scripts/TraditionalProbeGI.py` | VBufferRT → TraditionalProbeGI → ToneMapper |
| `scripts/TraditionalProbeGIValidation.py` | 固定场景、离屏捕获、PathTracer 参考与失败时退出 |
| `tests/probe_gi/run_validation.py` | 在独立进程中执行完整集成验收 |
| `tests/probe_gi/check_results.py` | 无第三方包的 SH 数学、缓存和 HDR 检查 |
| `tests/probe_gi/interactive_script.py` | 同一进程切场景、手动 Bake、改参、取消和错误恢复验收 |

## 构建与复验

重新配置使用 [本地运行说明](C:/Users/Admin/Desktop/实时GI/Falcor/LOCAL-RUN.md) 中的工具链参数。已有构建目录时可单独构建新插件：

```powershell
Set-Location F:\
& '.\tools\.packman\cmake\bin\cmake.exe' --build build/windows-vs2022 `
    --config Release --target TraditionalProbeGI --parallel 8

& '.\tools\.packman\python\python.exe' '.\tests\probe_gi\run_validation.py'

# 交互控制流程复验：同进程切换场景，调用与 UI 按钮相同的接口
$env:FALCOR_MEDIA_FOLDERS = 'F:\media'
& '.\build\windows-vs2022\bin\Release\Mogwai.exe' --device-type vulkan `
    --headless --deferred --script 'F:\tests\probe_gi\interactive_script.py' `
    --width 320 --height 240 --logfile 'F:\build\probe-interactive.log'
```

验收会重新烘焙默认 Cornell 缓存，依次测试独立加载、移动相机、关闭探针对照、2048 spp PathTracer 参考和错误缓存。输出在 `build/probe-validation/`，日志在 `build/probe-*.log`。`results.json` 记录图像数值，`integration.json` 只在整个流程成功后生成。该目录和缓存位于已有 Git 忽略范围内。

参考图与探针不是相同的估计器：PathTracer 使用完整材质与更精细的可见性，而探针只重建漫反射低频光照。因此参考用于观察近似误差，不以逐像素相等作为通过条件。保存/加载一致性比较的是相同探针算法的两次运行。

## 本轮结果

Cornell / Vulkan / Release 已通过实际烘焙、独立加载、相机移动、探针开关及 6 类错误缓存检查。384 探针的文本缓存约 117 KiB；保存前/加载后的 HDR 最大差异为 0，所有像素有限。与 2048 spp PathTracer 参考的线性 RGB RMSE 为 0.104725。完整记录见开发契约末尾。

交互扩展也已通过同进程 Cornell → Room → Cornell 切换、手动 Bake/取消/改参/加载、非法参数和保存失败恢复检查；默认启动保持等待，不自动烘焙。测试使用与面板按钮共用的控制接口。

## 探针调试显示

展开 **Probes → Debugging → Enable debug**。调试默认关闭，不重新 Bake，不改变缓存；生产光照的遮挡修正由独立的 Distance visibility 开关控制。

针对墙上斑块和墙边漏光，推荐这样操作：

1. 等待 Bake 完成，或点击 **Load matching cache** 加载已有结果。
2. 开启 **Pick surface (right click)**，在有问题的墙面右键点击一次。选中的是世界空间表面位置，之后可以用左键拖动视角绕着观察；右键点击背景或 **Clear selection** 清除选择。点击时请避开面板。右键在 6DoF 相机中原本用于翻滚，开启选点时由探针通道接管，关闭选点或 debug 后恢复原绑定。
3. 打开 **X-ray overlays**、**Only selected cell probes**、**Show probe IDs** 和 **Show contribution links**。查看这个位置对应的八个探针：**绿线表示可见，红线表示被遮挡，黄线表示 Normal + View bias 偏移**。线宽随最终插值权重增加；被可见性拒绝的探针仍画细线，原三线性权重为零的连线不画。黄色标记是原始表面位置。
4. 面板逐项显示探针 ID、位置、实际插值权重，以及 `weighted E`（该探针对选中法线的辐照度贡献，已乘权重，尚未对总和取非负）。通常权重和为 1；所有权重极小时和小于 1，避免放大遮挡残余。可比较 tri、V 和最终 w；距离矩是估计，Blocked 的探针不一定严格为零。
5. 调整 **Normal bias / View bias** 可实时观察偏移、八探针和可见性的变化；无须重新烘焙。`clamped: yes` 表示偏移后的采样位置在网格外，采样坐标被夹到了网格边缘。

**Surface view** 的基础模式如下；新增三种距离可见性模式见文首：

| 模式 | 内容 |
| --- | --- |
| Normal lighting | 原有合成光照；可叠加探针诊断 |
| Irradiance (no albedo) | 未乘材质颜色、未除以 π、未乘 Probe intensity 的探针辐照度；便于检查斑块 |
| Diffuse albedo | 漫反射反射率，排除材质颜色因素 |
| World normal | 世界空间着色法线映射到 RGB，检查法线突变 |
| Probe cell | 以不同颜色标记参与插值的网格单元 |
| Grid clamp mask | 网格外采样为洋红色，网格内为暗灰色 |

非 Normal 模式优先于旧的 **Probe lighting only**。纯辐照度诊断直接读取已完成的探针数据，不受 Enable probes 开关影响；尚未完成 Bake 时为黑色。显示仍经过原来的 ToneMapper，检查原始数值可查看 `Probes.color` 的 HDR 输出。

**Show probe spheres** 显示探针位置和方向光照，**Show grid bounds** 显示蓝色体积边界。关闭 X-ray 后叠加内容被场景表面遮挡；开启后可看墙后探针。球大小由 **Sphere radius / spacing** 控制，表示最小网格间距的比例。球是用于诊断的屏幕空间球形标记；为了可见性，屏幕尺寸有上下限，不能据此判断探针是否精确落在几何体内。

右下角的 **Selected probe direction sphere** 放大显示 **Selected probe ID** 的 SH 重建，黄色描边标记该探针。选择表面时默认挑权重最大的探针，也可手动输入八个 ID 中的任一个。默认显示方向辐照度；勾选 **Sphere shows radiance** 切换到未经余弦卷积的 L2 SH 辐亮度。**Highlight negative SH (magenta)** 把重建的负值标洋红，帮助检查 SH 截断误差；未勾选时负值取零显示。**Sphere exposure (EV)** 只调整球显示亮度。

方向球按当前相机朝向展示对应世界方向，移动相机可观察不同方向；它不是原始烘焙 cubemap。未烘焙时球为灰色占位。编号较密时推荐只显示选中单元的探针。

遮挡检测从 Normal bias 偏移位置发射带小 epsilon 的 alpha-test 阴影射线，只在主动拾取或调试参数刷新时执行。它用于检查连线是否被挡，**不会修改生产插值权重，也不等于完整的探针有效性检测**。修改场景、探针网格或重置烘焙会清除旧选择；网格边界无效时暂停调试绘制，修正后恢复。调试会增加绘制成本，主动拾取时有一次少量 GPU 数据同步读回。

脚本接口与 GUI 共用控制器，例如：

```python
p = TraditionalProbeGI.getPass("Probes")
p.configureDebug({"enabled": True, "xray": True, "onlyContributors": True,
                  "showIds": True, "pickEnabled": True})
p.pickSurface(float2(0.5, 0.5))  # 归一化视口坐标，左上角为 (0,0)
renderFrame()
print(p.debugInfo)  # 世界位置、8 个探针、权重、可见性与贡献
p.configureDebug({"view": 1})  # 0..5 对应上表
p.configureDebug({"enabled": False})
```

`tests/probe_gi/debug_script.py` 用 headless Vulkan 验证实际着色器、拾取、遮挡、锚点和场景切换；`check_debug_results.py` 检查 HDR 数值和调试关闭后的输出一致性。图像和结果位于 `build/probe-debug-validation/`。

## 缓存保存与异常提示

### 保存和恢复调试选点

选点不包含在 `Save Config` 中。右键选中表面并等待调试数据显示后，通过 **File → Load Script** 打开 `F:/scripts/SaveProbeSelection.py`，将世界坐标、法线、normalBias 和 viewBias 保存到 `F:/build/probe-selection.json`。再次保存会覆盖上次选点。旧文件缺少 viewBias 时恢复为 0；相机不保存在该文件中，view bias 使用恢复时的当前相机。

重启后先加载同一个场景、相应 Probe 缓存（或完成 Bake），再通过 **File → Load Script** 打开 `F:/scripts/LoadProbeSelection.py`。它恢复固定世界位置并启用调试连线，下一帧刷新距离和权重。脚本不保存相机、不自动 Bake、不退出程序。改变分辨率或重新 Bake 会清除当前选点，因此应在烘焙后恢复。

缓存需要与当前场景、网格、样本数、反弹数和 Scene revision 匹配。`cannot open` 表示文件打不开，`metadata mismatch` 表示参数不匹配，`truncated file at SH coefficient ...` 表示文件内容不完整；它们是不同问题。

已修复 Room 场景中异常路径导致缓存写到一半的问题：旧版先清空正式缓存，再逐项检查系数，碰到非有限值会留下半截文件。现在先在内存中校验完整数据，再写同目录临时文件，成功后替换正式缓存；失败会保留旧文件。原有 v1 有效缓存仍兼容，已经截断的缓存需要重新 Bake，不能补零当作有效结果。

烘焙会检测 NaN/Inf 路径，使用确定性的备用种子最多重试 8 次。恢复成功时，面板及日志仍显示异常尝试数量；如果有样本始终无法恢复，本次烘焙不标记 Ready，也不覆盖缓存。该保护不意味着异常材质或几何已被修复。状态文字会自动换行，便于读完整错误原因。

本次 Room 验证定位到探针 378、样本 1974（均从 0 编号）的一次异常，重试恢复后成功保存，并在独立进程加载，HDR 最大差异为 0。原始截断缓存和日志保存在 `build/probe-cache-repair/`，验证脚本为 `tests/probe_gi/run_cache_repair_validation.py`。

Room/Arcade 的入口可用，但本轮没有对它们执行完整数值验收。当前结果仍可见局部块状变化与偏暗，不应视为生产级探针方案。

探针结果：

![Cornell 传统探针结果](C:/Users/Admin/Desktop/实时GI/Falcor/build/probe-validation/load.Display.dst.0.png)

相同相机的 PathTracer 参考：

![Cornell 路径追踪参考](C:/Users/Admin/Desktop/实时GI/Falcor/build/probe-validation/reference.Display.dst.0.png)
