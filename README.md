![](docs/images/teaser.png)

# Falcor

Falcor is a real-time rendering framework supporting DirectX 12 and Vulkan. It aims to improve productivity of research and prototype projects.

Features include:
* Abstracting many common graphics operations, such as shader compilation, model loading, and scene rendering
* Raytracing support
* Python scripting support
* Render graph system to build modular renderers
* Common rendering techniques such as post-processing effects
* Unbiased path tracer
* Advanced variance reduction techniques like ReSTIR PT Enhanced
* Integration of various RTX SDKs such as DLSS, RTXDI and NRD

## Prerequisites
- Windows 10 version 20H2 (October 2020 Update) or newer, OS build revision .789 or newer
- Visual Studio 2022
- [Windows 10 SDK (10.0.19041.0) for Windows 10, version 2004](https://developer.microsoft.com/en-us/windows/downloads/windows-10-sdk/)
- A GPU which supports DirectX Raytracing, such as the NVIDIA Titan V or GeForce RTX
- NVIDIA driver 535 or newer

Optional:
- Windows 10 Graphics Tools. To run DirectX 12 applications with the debug layer enabled, you must install this. There are two ways to install it:
    - Click the Windows button and type `Optional Features`, in the window that opens click `Add a feature` and select `Graphics Tools`.
    - Download an offline package from [here](https://docs.microsoft.com/en-us/windows-hardware/test/hlk/windows-hardware-lab-kit#supplemental-content-for-graphics-media-and-mean-time-between-failures-mtbf-tests). Choose a ZIP file that matches the OS version you are using (not the SDK version used for building Falcor). The ZIP includes a document which explains how to install the graphics tools.
- CUDA, OptiX (see below)

## Building Falcor
Falcor uses the [CMake](https://cmake.org) build system. Additional information on how to use Falcor with CMake is available in the [CMake](docs/development/cmake.md) development documentation page.

### Visual Studio
If you are working with Visual Studio 2022, you can set up a native Visual Studio solution by running `setup_vs2022.bat` after cloning this repository. The solution files are written to `build/windows-vs2022` and the binary output is located in `build/windows-vs2022/bin`.

### Visual Studio Code
If you are working with Visual Studio Code, run `setup.bat` after cloning this repository. This will setup a VS Code workspace in the `.vscode` folder with sensible defaults (only if `.vscode` does not exist yet). When opening the project folder in VS Code, it will prompt to install recommended extensions. We recommend you do, but at least make sure that _CMake Tools_ is installed. To build Falcor, you can select the configure preset by executing the _CMake: Select Configure Preset_ action (Ctrl+Shift+P). Choose the _Windows Ninja/MSVC_ preset. Then simply hit _Build_ (or press F7) to build the project. The binary output is located in `build/windows-ninja-msvc/bin`.

Warning: Do not start VS Code from _Git Bash_, it will modify the `PATH` environment variable to an incompatible format, leading to issues with CMake.

### Linux
Falcor has experimental support for Ubuntu 22.04. To build Falcor on Linux, run `setup.sh` after cloning this repository. You also need to install some system library headers using:

```
sudo apt install xorg-dev libgtk-3-dev
```

You can use the same instructions for building Falcor as described in the _Visual Studio Code_ section above, simply choose the _Linux/GCC_ preset.

### Configure Presets
Falcor uses _CMake Presets_ stored in `CMakePresets.json` to provide a set of commonly used build configurations. You can get the full list of available configure presets running `cmake --list-presets`:

```
$ cmake --list-presets
Available configure presets:

  "windows-vs2022"           - Windows VS2022
  "windows-ninja-msvc"       - Windows Ninja/MSVC
  "linux-clang"              - Linux Ninja/Clang
  "linux-gcc"                - Linux Ninja/GCC
```

Use `cmake --preset <preset name>` to generate the build tree for a given preset. The build tree is written to the `build/<preset name>` folder and the binary output files are in `build/<preset name>/bin`.

An existing build tree can be compiled using `cmake --build build/<preset name>`.

## Falcor In Python
For more information on how to use Falcor as a Python module see [Falcor In Python](docs/falcor-in-python.md).

## Microsoft DirectX 12 Agility SDK
Falcor uses the [Microsoft DirectX 12 Agility SDK](https://devblogs.microsoft.com/directx/directx12agility/) to get access to the latest DirectX 12 features. Applications can enable the Agility SDK by putting `FALCOR_EXPORT_D3D12_AGILITY_SDK` in the main `.cpp` file. `Mogwai`, `FalcorTest` and `RenderGraphEditor` have the Agility SDK enabled by default.

## NSight Aftermath
To enable NSight Aftermath support, head over to https://developer.nvidia.com/nsight-aftermath and download the latest version of Aftermath (this build is tested against version 2023.1).
Extract the content of the zip file into `external/packman/aftermath`.

## CUDA
To enable CUDA support, download and install [CUDA 11.6.2](https://developer.nvidia.com/cuda-11-6-2-download-archive) or later and reconfigure the build.

See the `CudaInterop` sample application located in `Source/Samples/CudaInterop` for an example of how to use CUDA.

## OptiX
If you want to use Falcor's OptiX functionality (specifically the `OptixDenoiser` render pass) download the [OptiX SDK](https://developer.nvidia.com/designworks/optix/download) (Falcor is currently tested against OptiX version 8.0) After running the installer, link or copy the OptiX SDK folder into `external/packman/optix` (i.e., file `external/packman/optix/include/optix.h` should exist).

Note: You also need CUDA installed to compile the `OptixDenoiser` render pass, see above for details.

## NVIDIA RTX SDKs
Falcor ships with the following NVIDIA RTX SDKs:

- DLSS (https://github.com/NVIDIA/DLSS)
- RTXDI (https://github.com/NVIDIAGameWorks/RTXDI)
- NRD (https://github.com/NVIDIAGameWorks/RayTracingDenoiser)

Note that these SDKs are not under the same license as Falcor, see [LICENSE.md](LICENSE.md) for details.

## DDGI 探针分批更新

DDGI 面板的 `Batch probe updates` 默认关闭，关闭时每帧更新全部探针。开启后可用 `Probes per frame` 设置每帧探针上限，默认 1024；Python 属性为 `batchProbeUpdates`、`probesPerFrame`。预算包含非活跃探针，后者被选中时只发固定的分类/重定位射线。

实现参考 NVIDIA 官方 UE4 插件的 round-robin 策略，追踪、混合、重定位和分类使用同一批次，其他探针保留历史。为按更新轮数处理初始化权重，一轮末尾不跨界：Sponza 的 10648 个探针按 10 批 1024 加 1 批 408 更新，11 帧覆盖一轮。更改开关或预算会清空历史；关闭 `Update probes` 则暂停轮换。保持相同 hysteresis 会使分批模式对光照变化响应更慢。

该选项适用于 DDGI（含 FG/WRC），不影响独立 LumenWorldCache。构建时 `cmake/ddgi-probe-batch.cmake` 在输出目录生成 SDK 着色器的批次检查版本，不修改下载的 NVIDIA SDK。更新源码后须重新编译 Release。测试脚本为 `tests/ddgi/probe_batch_smoke.py` 和 `tests/ddgi/sponza_probe_batch_comparison.py`。

做固定射线预算实验时，可设置 Python 属性 `wrapProbeBatches=True`：在网格末尾回绕并补足本帧预算，不留短尾批。默认仍为 False；切换时清空探针历史。`tests/ddgi/probe_wrap_smoke.py` 验证回绕，`tests/ddgi/sponza_seven_accumulated.py` 比较全量、800 和 1274 probes/frame 的原生 DDGI 与半分辨率 FG，并加入 WorldCache 对照。图像从空缓存起连续 Accumulate，通过连续两次累积翻倍的颜色和指标稳定性检查后结束。

诊断属性 `primaryShadingNormalCorrection` 默认 True，遵循 GBuffer 的法线修正策略。设为 False 仅禁用 DDGI/FG 主命中材质求值的修正，不改变 GBuffer 法线或次级命中。`tests/ddgi/sponza_primary_normal_ab.py` 用于隔离验证该策略，不应将关闭组当作正常质量基线。

## 在新机器配置额外场景资源

Sponza 和 EmeraldSquare 的模型、贴图不包含在 Git 中。原版和 Lambert 版共用资源，可在仓库根目录用 **Python 3.9+** 下载（不需要额外 Python 包）：

```powershell
# 首次配置：安装 VS2022 C++ 工具后，拉取 Packman 依赖并生成工程。
.\setup_vs2022.bat
# 默认下载两套场景；会校验文件并跳过完整资源。
.\Download-SceneAssets.ps1
# git pull 不会更新 DLL，需要编译启动器使用的 Release 目录。
& .\tools\.packman\cmake\bin\cmake.exe --build build/windows-vs2022 --config Release
.\Run-Falcor.ps1
```

可单独使用 `-Scene Sponza` 或 `-Scene EmeraldSquare`；`-VerifyOnly` 仅检查完整性、不下载。首次下载约 50 MiB + 589 MiB，资源解压后约 1.5 GiB，另保留 EmeraldSquare 压缩包缓存。中断后重跑会跳过已完成且校验通过的文件，未完成的单文件重新下载。缺失或校验不符的资源会被恢复为固定版本，请勿直接修改受管理的模型和贴图。

若 NVIDIA 下载受网络限制，可从 [官方页面](https://developer.nvidia.com/orca/nvidia-emerald-square) 下载压缩包，然后运行：

```powershell
.\Download-SceneAssets.ps1 -Scene EmeraldSquare -EmeraldArchive 'D:\Downloads\EmeraldSquare_v4_1.zip'
```

脚本使用 `scripts/scene-assets.json` 固定版本及 SHA-256。Sponza 来自 Khronos glTF-Sample-Assets 的 `f0920f5b32d172a30efe3f9257e965918831e6ea` 版本，保留 Crytek 许可说明与上游 README；EmeraldSquare 保留 NVIDIA 的 CC BY-NC-SA 3.0 许可及署名。资源许可独立于本项目代码许可。下载结果分别放到 `media/Sponza/` 和 `media/ORCA_EmeraldSquare/`。`media` 由 Packman 管理，通常是符号链接，脚本不会替换它。其他内置场景仍由 Packman 依赖提供。

## Emerald Square 城市 GI 场景

运行 `Run-Falcor.ps1`，Scene 选择 `EmeraldSquare` 或 `EmeraldSquareLambert`，Renderer 选择 `DDGI`。进入后可在 Final gather 中开关 FG、选择半／全分辨率，也可从 Active Graph 切到 `LumenWorldCache` 或 `PTReference`。默认保持 ReSTIR 关闭、Accumulate 开启。

资源来自 [NVIDIA ORCA Emerald Square](https://developer.nvidia.com/orca/nvidia-emerald-square)，作者 Nicholas Hull、Kate Anderson、Nir Benty，许可为 **CC BY-NC-SA 3.0**；植被由 SpeedTree 提供。下载官方 `EmeraldSquare_v4_1.zip`，解压到 `media/ORCA_EmeraldSquare/`，使 `EmeraldSquare_v4_1/EmeraldSquare_Day.pyscene` 位于其下。约 589 MiB 下载、1.44 GiB 解压；资源及纹理不提交到 Git。已验证压缩包 SHA-256：`a63d08531c8a3245b722a2407b57385b191064090487ef3fee3c4e796b41e2f6`。

接入的是官方白天版，保留相机、方向光、点光源和 HDR 天空，关闭相机与灯光动画。Lambert 版替换全部表面为 `PBRTDiffuseMaterial`，保留底色、法线、双面设置与 alpha 裁剪；金属和玻璃转为纯漫反射，取消镜面、透射和表面自发光。因此它是供 GI 对比使用的材质变体，不是原始场景外观的完整复现。各渲染图使用相同固定曝光。

场景导入后约 997 万实例化三角形，范围约 230×113×230 米。初始 DDGI 使用覆盖全城的 **32×16×32** 单体积、每探针 256 条射线，间距约 **7.74×8×7.74 米**。这是能运行的大场景预览配置，并非已调优的质量基准；不会自动提高街道和室内的探针密度。正式比较前需检查探针覆盖、泄漏与收敛，不能沿用 Sponza 的质量结论。

## Resources

- [Falcor](https://github.com/NVIDIAGameWorks/Falcor): Falcor's GitHub page.
- [Documentation](./docs/index.md): Additional information and tutorials.
    - [Getting Started](./docs/getting-started.md)
    - [Render Graph Tutorials](./docs/tutorials/index.md)
- [Rendering Resources](https://benedikt-bitterli.me/resources) A collection of scenes loadable in Falcor (pbrt-v4 format).
- [ORCA](https://developer.nvidia.com/orca): A collection of scenes and assets optimized for Falcor.
- [Slang](https://github.com/shader-slang/slang): Falcor's shading language and compiler.

## Citation
If you use Falcor in a research project leading to a publication, please cite the project.
The BibTeX entry is

```bibtex
@Misc{Kallweit22,
   author =      {Simon Kallweit and Petrik Clarberg and Craig Kolb and Tom{'a}{\v s} Davidovi{\v c} and Kai-Hwa Yao and Theresa Foley and Yong He and Lifan Wu and Lucy Chen and Tomas Akenine-M{\"o}ller and Chris Wyman and Cyril Crassin and Nir Benty},
   title =       {The {Falcor} Rendering Framework},
   year =        {2022},
   month =       {8},
   url =         {https://github.com/NVIDIAGameWorks/Falcor},
   note =        {\url{https://github.com/NVIDIAGameWorks/Falcor}}
}
```
