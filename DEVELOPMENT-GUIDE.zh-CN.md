# Falcor 使用与 GI 算法开发指南

新增：仓库现已提供 `TraditionalProbeGI`，可直接按 [传统光照探针使用说明](C:/Users/Admin/Desktop/实时GI/Falcor/PROBE-GI.md) 烘焙和加载。本文后续 `MyGI`、`ProbeBakePass` 等仍是讲解扩展方法的示例名称。

本文针对当前本地 Falcor 9.0 源码及 Windows 配置编写。项目位于 `C:\Users\Admin\Desktop\实时GI\Falcor`，上游基线为 `759aad03`，本地启动与 UTF-8 路径修复提交为 `392d9d44`。

已完成的能力：Mogwai Release 构建、Vulkan 后端启动、灰白室内场景加载。本文中的 `MyGI`、`ProbeBakePass` 等名称是开发示例，目前没有在仓库中实现。下面的创建命令供开发时执行，编写本文时没有执行，也没有新增或编译这些示例插件。

## 1. 项目由哪些部分组成

Falcor 是本地渲染研究框架。通常把新算法写成 RenderPass 插件，用 Python 将它与现成的场景可见性、累积、后处理模块连接，再通过 Mogwai 运行。

| 部分 | 职责 | 常用位置 |
| --- | --- | --- |
| Mogwai | 窗口、场景加载、交互、运行渲染图 | `Source/Mogwai/` |
| Falcor 核心 | GPU 资源、着色器编译、场景、材质和渲染图 | `Source/Falcor/` |
| RenderPass | 一个算法阶段，声明输入输出并执行 GPU 工作 | `Source/RenderPasses/` |
| Slang 着色器 | 光追、计算、光栅化阶段的 GPU 代码 | 各 Pass 下的 `.slang` 文件 |
| Python 脚本 | 创建 Pass、设置参数、连接输入输出 | `scripts/` |
| 场景 | 几何、材质、灯光、相机及场景脚本 | `media/` |

一个算法可以只有一个 Pass，也可以由采样、更新、滤波、重建等多个 Pass 组成。Python 在这里主要负责配置和调度；大量逐像素计算应放在 GPU 着色器中。

## 2. 本地运行

### 2.1 使用已有启动脚本

在 Falcor 根目录双击 `Run-Falcor.cmd`，或在 PowerShell 中运行：

```powershell
.\Run-Falcor.cmd -Scene Room
# 也可以单独选择下面任意一个场景
.\Run-Falcor.cmd -Scene Cornell
.\Run-Falcor.cmd -Scene Arcade
```

每次执行都会新开窗口，通常只保留一个。当前脚本固定加载 `scripts/PathTracer.py`，默认使用 Vulkan。

| 场景 | 本地文件 | 适合观察的现象 |
| --- | --- | --- |
| Room | `media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene` | 室内间接光、接触处、明暗过渡 |
| Cornell | `media/test_scenes/cornell_box.pyscene` | 颜色渗透、间接反弹、能量是否合理 |
| Arcade | `media/Arcade/Arcade.pyscene` | 更复杂的材质、遮挡和整体性能 |

这些场景可以用于早期验证。测试探针漏光时，还应增加可控的小场景，例如薄墙隔开的明暗房间、小窗入光、靠墙移动的物体；一般场景不能覆盖所有失败情况。

默认第一人称相机模式中，W/A/S/D 移动，Q/E 升降，按住鼠标左键拖动改变视角。相机静止后，路径追踪结果会逐帧累积；移动后重新累积。F5 重载着色器，F12 截取显示画面。

### 2.2 F: 映射和图形后端

当前构建通过 `subst` 将项目目录映射为 `F:`，用于绕开部分工具对中文路径的处理问题。文件仍保存在原目录。启动脚本会创建映射，也会检查 F: 是否被其他位置占用。

后续示例都假定 F: 已正确指向本仓库。可以先运行已有启动脚本，再关闭 Mogwai，继续开发。已有 F: 时不要随意覆盖它。

本机已成功使用 Vulkan。首次使用 D3D12 时创建设备失败，尚未完成排查；`-Device d3d12` 只是可选入口，不代表当前环境已经验证可用。Mogwai 的 UTF-8 manifest 修复应保留。

### 2.3 运行其他渲染管线

在 PowerShell 中直接指定脚本，比修改默认启动器更方便：

```powershell
Set-Location F:\
$env:FALCOR_MEDIA_FOLDERS = 'F:\media'
& '.\build\windows-vs2022\bin\Release\Mogwai.exe' `
    --device-type vulkan `
    --script 'F:\scripts\MinimalPathTracer.py' `
    --scene 'F:\media\test_scenes\cornell_box.pyscene' `
    --width 1280 --height 720
```

将 `--script` 换为自己的脚本即可。也可以在 Mogwai 的 `File → Load Script` / `Load Scene` 中加载脚本或场景。渲染图和场景是两个独立输入：换算法不要求换场景。

### 2.4 重新编译

修改 C++ 前先关闭 Mogwai，避免插件 DLL 被占用。使用已经成功构建的工具链配置：

```powershell
Set-Location F:\
$env:PM_PACKAGES_ROOT = 'F:\tools\.packman\cache-ascii'
& '.\tools\.packman\cmake\bin\cmake.exe' --preset windows-vs2022 `
    -T 'host=x64,version=14.38.33130' '-DCMAKE_SYSTEM_VERSION=10.0.22621.0'
& '.\tools\.packman\cmake\bin\cmake.exe' --build build/windows-vs2022 `
    --config Release --target Mogwai --parallel 8
```

新增插件、修改 CMake 时需要重新配置。普通 C++ 修改一般只需后面的构建命令。顶层 CMake 将插件目标设为 Mogwai 的依赖，因此构建 Mogwai 会带上已注册的插件。

着色器通过 `target_copy_shaders()` 复制到运行目录。修改源码后，稳妥做法是先构建对应插件以同步着色器，再启动程序或按 F5；只按 F5 不保证读取到尚未复制的新文件。C++ 修改需要重新构建并重启。

## 3. 读懂当前渲染管线

`scripts/PathTracer.py` 连接了下面的流程：

```text
VBufferRT ── vbuffer / viewW / mvec ──> PathTracer
                                          │ color（线性 HDR）
                                          ▼
                                    AccumulatePass
                                          │ output
                                          ▼
                                      ToneMapper
                                          │ dst
                                          ▼
                                        显示
```

- `VBufferRT` 生成相机可见性等信息；`vbuffer` 是打包的命中信息，不能直接当作世界坐标或法线读取。
- `PathTracer` 计算光照。当前脚本选择 `tracePassMode='MinimalPayload'`。
- `AccumulatePass` 累积多个渲染帧，降低随机噪声。
- `ToneMapper` 把 HDR 结果转换为适合显示的图像。数值误差比较通常应放在它之前。

Python 中 `createPass("PathTracer", {...})` 指定注册的插件类；`g.addPass(pass, "PT")` 中的 `PT` 是图内实例名；`g.addEdge("PT.color", "Accum.input")` 中的端口名由 C++ 的 `reflect()` 声明。类名、实例名、端口名是三个不同概念。

`g.markOutput()` 标记需要保留和暴露的结果。调试新算法时可以额外标记法线、间接光、探针权重等纹理输出，再在界面选择显示。额外输出可能影响资源生命周期，性能测量前应恢复正式配置。

### 光追着色器在哪里

当前 PathTracer 使用 `Source/RenderPasses/PathTracer/TracePassMinimalPayload.rt.slang`：

| 阶段 | 入口 | 职责 |
| --- | --- | --- |
| RayGen | `rayGen` | 按像素进入路径调度器 |
| Closest Hit | `scatterTriangleClosestHit` | 将三角形命中信息和距离写入 payload |
| Any Hit | `scatterTriangleAnyHit` | Alpha Test，忽略应透过的交点 |
| Miss | `scatterMiss` | 保留默认的未命中状态 |
| Intersection | `curveIntersection` 等 | 曲线、SDF 等自定义几何求交 |

MinimalPayload 模式把主要路径状态放在 RayGen 侧，命中后的光照处理进入 `PathTracer.slang` 的 `handleHit()` / `handleMiss()`。不能只看 Closest Hit 就认为算法没有计算材质或环境光。三角形求交通常由光追硬件完成，无需自己实现三角形 Intersection Shader。

理解入口和绑定关系，可以先看 `Source/Samples/HelloDXR/HelloDXR.rt.slang` 与相应 `.cpp`；理解一个可接入渲染图的追踪器，优先看 `MinimalPathTracer`。**MinimalPathTracer 是独立插件，MinimalPayload 是完整 PathTracer 的一种模式，两者不同。**

## 4. 新增算法：两种起点

### 4.1 空模板：适合计算 Pass、滤波或探针采样

在已建立 F: 映射后，调用仓库自带生成器：

```powershell
Set-Location F:\
& '.\tools\.packman\python\python.exe' '.\tools\make_new_render_pass.py' MyGI
```

它会创建 `Source/RenderPasses/MyGI/` 下的 `.h`、`.cpp`、`CMakeLists.txt`，替换模板中的类名，并在 `Source/RenderPasses/CMakeLists.txt` 注册子目录。已有同名目录时会拒绝覆盖。

模板只有插件框架，没有着色器，也没有可显示的输出。需要补齐以下工作：

| 方法或位置 | 需要做的事 |
| --- | --- |
| 构造函数 | 读取 `Properties`，初始化算法参数和计算程序 |
| `getProperties()` | 返回可保存的配置，方便复现实验 |
| `reflect()` | 声明输入、输出、格式、尺寸和必要的资源绑定能力 |
| `compile()` | 处理依赖输出分辨率的资源初始化或重建 |
| `setScene()` | 保存场景；需要场景时建立程序、绑定和相关状态 |
| `execute()` | 读取输入、绑定资源、上传参数、派发计算或光追 |
| `renderUI()` | 暴露调试参数，并在参数变化后使历史数据失效 |
| `registerPlugin()` | 将 C++ 类注册给插件系统；生成器已经提供 |

当前模板采用 `ref<Device>`、`ref<Scene>`、`Properties` 等 API。部分旧教程仍写 `SharedPtr`、`Dictionary`、`add_renderpass()`，复制代码时应以当前模板和可编译的插件为准。

新增 `MyGI.cs.slang` 后，CMake 应包含它并设置复制规则，例如：

```cmake
add_plugin(MyGI)
target_sources(MyGI PRIVATE MyGI.cpp MyGI.h MyGI.cs.slang)
target_copy_shaders(MyGI RenderPasses/MyGI)
target_source_group(MyGI "RenderPasses")
```

计算 Pass 的完整实现可参考 `Source/RenderPasses/Utils/Composite/Composite.cpp`：通过 `ComputePass::create()` 建立程序，用 `getRootVar()` 按名字绑定常量和纹理，再调用 `execute()`。复制接口时也要带上资源声明、尺寸设置和着色器线程布局，不能只复制派发语句。

### 4.2 复制 MinimalPathTracer：适合修改射线采样和路径估计

如果目标是新增一种 GI 追踪算法，这个起点能保留已经完整连接的场景、材质、随机采样和 SBT 绑定。

下面与空模板路线二选一；不要先创建同名 MyGI 再执行。命令只复制明确列出的四个源文件，保留原文件中的许可证说明，并更新构建入口：

```powershell
Set-Location F:\
$newPassName = 'MyGI'
$newPassDir = Join-Path 'Source\RenderPasses' $newPassName
if (Test-Path -LiteralPath $newPassDir) { throw 'MyGI already exists.' }
New-Item -ItemType Directory -Path $newPassDir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($fileName in @('CMakeLists.txt', 'MinimalPathTracer.h',
                       'MinimalPathTracer.cpp', 'MinimalPathTracer.rt.slang')) {
    $sourceFile = Join-Path 'Source\RenderPasses\MinimalPathTracer' $fileName
    $targetFile = Join-Path $newPassDir $fileName.Replace('MinimalPathTracer', $newPassName)
    $contents = [System.IO.File]::ReadAllText((Resolve-Path $sourceFile).Path)
    $contents = $contents.Replace('MinimalPathTracer', $newPassName)
    [System.IO.File]::WriteAllText((Join-Path (Get-Location).Path $targetFile), $contents, $utf8)
}
Add-Content -Path 'Source\RenderPasses\CMakeLists.txt' `
    -Value "`nadd_subdirectory(MyGI)" -Encoding ASCII
```

全名替换会同步修改类名、插件名、CMake 目标及 C++ 中的着色器路径。刚复制完成时 MyGI 仍是原来的 MinimalPathTracer 算法，应先验证结果一致，再修改估计器。

重点阅读生成的 `MyGI.cpp`：

1. `reflect()` 使用通道列表声明 `vbuffer`、可选 `viewW` 和 `color`。
2. `setScene()` 创建 `ProgramDesc`，添加场景模块、着色器、payload 和递归深度设置，建立 `RtBindingTable`。
3. `prepareVars()` 配置随机采样器及材质类型等程序绑定。
4. `execute()` 绑定每帧输入输出，并调用 `mpScene->raytrace(...)`。

光追版 `MyGI.rt.slang` 的 RayGen、Miss、Hit Group 必须与 C++ 注册的入口名一致。修改 payload、射线类型或几何支持时，还要同步检查 payload 大小、SBT 索引及最大递归深度。路径反弹次数不等于 TraceRay 调用栈递归深度，不能直接把两者互换。

MinimalPathTracer 对部分材质和场景更新有局限，例如透射与嵌套介质；从它派生的算法也会继承这些限制。先用静态、不透明、漫反射场景验证。

## 5. 把 MyGI 接入渲染图

对上面的 MinimalPathTracer 复制路线，可创建 `scripts/MyGI.py`：

```python
from falcor import *

def render_graph_MyGI():
    g = RenderGraph("MyGI")
    g.addPass(createPass("VBufferRT", {
        "samplePattern": "Stratified", "sampleCount": 16
    }), "Visibility")
    g.addPass(createPass("MyGI", {"maxBounces": 3}), "GI")
    g.addPass(createPass("AccumulatePass", {
        "enabled": True, "precisionMode": "Single"
    }), "Accum")
    g.addPass(createPass("ToneMapper", {
        "autoExposure": False, "exposureCompensation": 0.0
    }), "Display")
    g.addEdge("Visibility.vbuffer", "GI.vbuffer")
    g.addEdge("Visibility.viewW", "GI.viewW")
    g.addEdge("GI.color", "Accum.input")
    g.addEdge("Accum.output", "Display.src")
    g.markOutput("Display.dst")
    return g

MyGI = render_graph_MyGI()
try:
    m.addGraph(MyGI)
except NameError:
    pass
```

重新配置并构建 Mogwai，然后将第 2.3 节启动命令中的脚本换为 `F:\scripts\MyGI.py`。

这段脚本假定你保留了 MinimalPathTracer 的参数和输入输出。如果选择空模板路线，必须先实现相同接口，或同步修改图的连线。当前插件发现流程使用构建生成的 `plugins.json`；不要直接照搬旧教程里手动加载 DLL 的代码。

第一次运行先确认：插件能创建、场景能加载、输出不是黑图、静止时能累积、相机移动后结果正常重置。之后每次只改变一个算法步骤，并与原始 MinimalPathTracer 使用相同参数比较。

## 6. 探针烘焙与实时采样如何组织

这部分是建议的扩展设计，仓库尚未提供这些自定义 Pass。

```text
烘焙：场景 + 探针布局 → ProbeBakePass → 球谐/方向数据与可见性 → 保存

实时：相机可见性 + 材质 + 读取的探针数据 → ProbeSamplePass
                                                   │ 间接光
                                   直接光 ─────────┤
                                                   ▼
                                                 合成 → 显示
```

### 6.1 烘焙阶段

烘焙的发射原点是探针位置，方向来自球面采样；不依赖当前相机的逐像素 VBuffer。可以借鉴现有追踪器的场景与材质处理，但需要改写 RayGen 初始化、路径起点和输出布局，不能只把相机位置改成探针位置。

建议先实现规则网格、静态场景、漫反射间接光，并分开处理：

1. **采样**：按照探针索引和样本索引发射射线，估计方向入射辐亮度。
2. **投影或滤波**：将方向样本归约成每个探针的系数，避免多个线程无同步写同一系数。
3. **存储**：将 GPU 结果读回并保存；明确同步和文件格式，避免在实时帧内重复读回。

若采用三阶带数、最高次数为 2 的实球谐（常写作 L2 SH），每个颜色通道有 9 个系数，即每个探针 27 个标量。先约定存储的是入射辐亮度系数，还是已与余弦核卷积后的辐照度系数。对 Lambert 漫反射，使用辐照度时出射辐亮度为 `albedo / π × irradiance`；不要重复卷积或重复乘反照率。

烘焙文件至少保存：格式版本、探针原点/间距/数量、坐标约定、SH 基函数顺序及归一化约定、数据语义、样本数、反弹限制、场景及灯光标识。只存一块 float 数组会让后续难以判断数据是否匹配当前场景。

### 6.2 实时阶段

由屏幕可见点得到世界坐标、法线和材质，在附近探针之间插值，得到漫反射间接光。可以从已有 GBuffer Pass 获取所需属性，或复用 Falcor 的 VBuffer 解码逻辑；输入端口必须与所选 Pass 的实际输出一致。

规则网格的八邻域三线性插值适合作为第一版。它不能自动解决薄墙漏光；后续可增加距离矩、可见性权重、法线相关权重及探针位置调整。先输出探针位置、选中索引和权重等调试视图，再判断最终光照。

明确约定直接光与间接光的分工。表面点的直接光、探针估计的间接光、背景/自发光分别处理，避免环境或灯光贡献被重复计算。相机移动通常无需重烘焙静态探针；灯光、材质或几何变化则可能使烘焙数据失效。

### 6.3 从离线烘焙扩展到实时更新

实时更新可以每帧更新部分探针，将结果保存在跨帧 GPU 资源中；把更新成本和屏幕采样成本分开计时。历史资源需要明确重置条件，不能指望渲染图的临时纹理自动保存正确历史。

第一版建议按以下顺序推进：单探针方向采样可视化 → 单探针 SH 重建 → 网格探针插值 → 数据保存/加载 → 漏光处理 → 分帧更新。镜面间接光通常需要比低阶 SH 更丰富的方向信息，应作为后续独立问题处理。

## 7. 结果验证和性能比较

固定场景、相机、分辨率、材质、灯光、反弹限制以及随机采样设置。先关闭去噪、自动曝光等会改变对比结果的功能，使用收敛后的 PathTracer 结果作为参考近似，并说明参考自身的采样与路径截断误差。

| 目标 | 检查方式 |
| --- | --- |
| 能量与颜色 | Cornell 场景；黑暗区域、颜色渗透和曝光一致性 |
| 稳定性 | 静止、移动相机、参数切换、切换场景、改变分辨率 |
| 漏光 | 薄墙、小窗、相邻明暗房间；观察探针权重和可见性 |
| 误差 | 比较 ToneMapper 之前的线性 HDR；可接入 ErrorMeasurePass |
| 感知差异 | 可查看 FLIPPass，保持输入与显示变换约定一致 |
| 性能 | Release 构建，预热着色器；分别记录各 Pass 的 GPU 时间和显存 |

探针方案同时报告烘焙耗时、文件体积、常驻显存、每帧更新成本和采样成本。实时算法应关闭无限逐帧平均，或明确说明所用的时域滤波，避免用静止累积后的质量代表运动时的实时效果。

### 保存输出

F12 适合展示截图。保存数值比较用的图像时，可在图脚本中额外加入 `g.markOutput("Accum.output")`，保留线性浮点输出，然后使用 Mogwai 的 FrameCapture。以第 5 节的实例命名为例，在已经渲染到所需收敛程度后，于 Mogwai Python 控制台执行：

```python
from pathlib import Path
Path("F:/build/experiments").mkdir(parents=True, exist_ok=True)
m.frameCapture.outputDir = "F:/build/experiments"
m.frameCapture.baseFilename = "MyGI-reference"
m.frameCapture.capture()
```

FrameCapture 按图输出及资源格式保存结果。确认保存的是 `Accum.output` 而不是仅有显示用的 `Display.dst`，并检查输出格式及数值范围。未收敛的一帧截图不能代替参考图。

## 8. 常见问题

| 现象 | 优先检查 |
| --- | --- |
| `createPass()` 找不到 MyGI | CMake 子目录是否注册、是否重新配置/构建、插件类名是否一致 |
| 图连线失败 | `reflect()` 声明的端口名、格式、尺寸与可选输入要求 |
| 黑图 | 是否加载场景、是否 `markOutput`、输出是否绑定和写入、着色器是否报错 |
| 修改 shader 没变化 | 运行时读取的是哪份文件、复制规则是否执行、是否重载或重启 |
| 编译时 DLL 无法写入 | Mogwai 或其他加载插件的程序是否仍在运行 |
| 参数改完出现旧图残影 | 是否通知下游重置累积，同时清空算法自己的历史状态 |
| 场景换了却沿用旧探针 | `setScene()` 和烘焙数据的匹配检查是否实现 |
| 中文目录加载失败 | F: 映射、Mogwai UTF-8 manifest、实际执行的构建版本 |
| D3D12 初始化失败 | 先用本机已验证的 Vulkan；独立查看设备初始化日志 |

参数刷新可参考 `MinimalPathTracer::execute()` 中的 `kRenderPassRefreshFlags` 与 `RenderOptionsChanged`。发出该标记不能替代重置自己维护的探针历史或采样计数。

## 9. Git 与实验记录

当前仓库已保留上游历史，并配置作者 `vector <1056765423@qq.com>`。开始开发时可以建立算法分支：

```powershell
git switch -c experiment/my-gi
git status
```

建议提交算法源码、渲染图脚本、配置和简短实验说明。`build/`、`media/`、Packman 缓存已有忽略规则；大型烘焙数据和参考图若另存到新目录，应先明确存储与忽略策略。每次实验记录 Git commit、场景、相机、关键参数和测量条件。

## 10. 进一步阅读

- [本地运行说明](C:/Users/Admin/Desktop/实时GI/Falcor/LOCAL-RUN.md)：本机启动器和工具链。
- [RenderPass 模板](C:/Users/Admin/Desktop/实时GI/Falcor/Source/RenderPasses/RenderPassTemplate/RenderPassTemplate.h)：当前 C++ 插件接口。
- [MinimalPathTracer.cpp](C:/Users/Admin/Desktop/实时GI/Falcor/Source/RenderPasses/MinimalPathTracer/MinimalPathTracer.cpp)：资源声明、场景初始化与光追派发。
- [MinimalPathTracer.rt.slang](C:/Users/Admin/Desktop/实时GI/Falcor/Source/RenderPasses/MinimalPathTracer/MinimalPathTracer.rt.slang)：较紧凑的路径追踪实现。
- [TracePassMinimalPayload.rt.slang](C:/Users/Admin/Desktop/实时GI/Falcor/Source/RenderPasses/PathTracer/TracePassMinimalPayload.rt.slang)：当前完整 PathTracer 的调度与入口。
- [PathTracer.slang](C:/Users/Admin/Desktop/实时GI/Falcor/Source/RenderPasses/PathTracer/PathTracer.slang)：完整路径追踪的主要光照处理。
- [Python 脚本文档](C:/Users/Admin/Desktop/实时GI/Falcor/docs/usage/scripting.md)：渲染图、场景与结果捕获接口。
- [官方教程目录](C:/Users/Admin/Desktop/实时GI/Falcor/docs/tutorials/index.md)：理解框架概念；具体 API 以当前源码为准。
