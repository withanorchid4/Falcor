# 本地运行

体验 SVGF 时空降噪可双击 `Run-SVGF.cmd`，或运行 `Run-Falcor.cmd -Renderer SVGF`。详见 [SVGF 使用说明](C:/Users/Admin/Desktop/实时GI/Falcor/SVGF.md)。

算法开发、渲染图配置和探针 GI 扩展请参阅 [Falcor 使用与 GI 算法开发指南](C:/Users/Admin/Desktop/实时GI/Falcor/DEVELOPMENT-GUIDE.zh-CN.md)。

运行新增的传统光照探针请双击 `Run-ProbeGI.cmd`，详见 [光照探针使用说明](C:/Users/Admin/Desktop/实时GI/Falcor/PROBE-GI.md)。

本工程的示例入口是 Mogwai。首次构建使用 Visual Studio 2022、MSVC 14.38.33130 和 Windows SDK 10.0.22621.0，配置为 Release。

## 打开场景

在文件资源管理器中双击 `Run-Falcor.cmd`，默认使用 Vulkan 后端打开灰白室内场景和 PathTracer 渲染管线。

也可以在本目录的 PowerShell 中选择场景：

```powershell
.\Run-Falcor.cmd -Scene Room
.\Run-Falcor.cmd -Scene Cornell
.\Run-Falcor.cmd -Scene Arcade
```

每条命令会新开一个窗口，通常一次运行一个即可。场景首次加载需要编译着色器。保持相机静止时，路径追踪结果会通过逐帧累积变得更清晰；相机移动后会重新累积。

在默认第一人称相机模式下，W/A/S/D 移动，Q/E 升降，按住鼠标左键拖动调整视角，Shift 加速，Ctrl 减速。操作时将鼠标放在场景画面中，避免输入被 UI 控件占用。

## 路径和依赖

官方 Packman 引导脚本在本机中文目录下出现路径编码问题，因此启动脚本使用 `subst` 将本工程临时映射为 `F:`。文件仍保存在原来的 Falcor 目录，没有复制或移动。该映射可能在注销或重启后消失；再次启动时会自动恢复。如果 F: 已被其他用途占用，脚本会报错，不会覆盖它。

运行时，Falcor 会将部分路径还原为原始中文路径。为此，`Source/Mogwai/Mogwai.manifest` 为 Mogwai 进程启用 UTF-8 编码，避免 Slang 无法打开着色器文件；这不会修改系统编码设置。

本机首次使用默认 D3D12 后端时创建设备失败，日志包含实验性功能初始化失败提示。当前改用可初始化设备的 Vulkan 后端，未修改系统开发者设置。后续若需要单独排查 D3D12，可运行 `Run-Falcor.cmd -Device d3d12`。

依赖缓存：`tools/.packman/cache-ascii/`。示例场景：`media/`。编译输出：`build/windows-vs2022/bin/Release/`。它们均已由上游 `.gitignore` 排除。

程序日志保存在 `build/windows-vs2022/preview-Room.log` 等文件中，编译日志为同目录下的 `build-release.log`。

## 重新编译

确保 F: 指向本工程（启动脚本可以创建该映射），在 PowerShell 中运行：

```powershell
Set-Location F:\
$env:PM_PACKAGES_ROOT = 'F:\tools\.packman\cache-ascii'
& '.\tools\.packman\cmake\bin\cmake.exe' --preset windows-vs2022 -T 'host=x64,version=14.38.33130' '-DCMAKE_SYSTEM_VERSION=10.0.22621.0'
& '.\tools\.packman\cmake\bin\cmake.exe' --build build/windows-vs2022 --config Release --target Mogwai --parallel 8
```

无需单独安装 CUDA 或 OptiX 即可运行这里的硬件光线路径追踪示例。DLSS SDK 随项目依赖下载；默认启动的 PathTracer 管线没有开启 DLSS。
