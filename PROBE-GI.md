# 传统光照探针：使用与结果

这是规则网格 + 9 项 RGB 球谐的静态漫反射光照探针实现。先烘焙，再从文件加载并实时采样。开发顺序与算法约定见 [开发契约](C:/Users/Admin/Desktop/实时GI/Falcor/docs/development/traditional-probes.md)。

## 启动

在 Falcor 根目录双击 `Run-ProbeGI.cmd`。默认打开 Cornell：如果有匹配缓存就加载，没有则开始烘焙。首次画面只有直接解析光和表面自发光，探针完成后才加入完整探针照明。

```powershell
# 强制重新烘焙，完成后自动保存并继续显示
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

窗口内展开 `Probes` Pass，可看到烘焙进度，并操作 `Enable probes`、`Probe lighting only`、`Probe intensity`、`Re-bake and save`。勾选只看探针贡献时，直接光、可见发光面和环境背景不会混入该调试图。

启动器默认 Vulkan，沿用 F: 映射和原有 UTF-8 修复。每次命令新开一个窗口，不要让多个烘焙进程写同一个缓存文件。

## 数据与参数

默认 8×6×8，共 384 个探针，每个探针 2048 样本、最多 3 次反射继续，每帧每探针追踪 16 条路径，128 个渲染帧完成烘焙。这不是“128 秒”：实际时间取决于场景、设备和首次着色器编译。

烘焙结果保存为 `build/probes/cornell.shprobe`、`room.shprobe` 或 `arcade.shprobe`。缓存是带版本与元数据的文本文件，保存平均入射辐亮度 SH。完成后只在 GPU 上插值与卷积，不会继续追踪探针路径，也不逐帧读回 CPU。相机可见性和解析光源阴影仍使用光追。

修改 `scripts/TraditionalProbeGI.py` 中的参数即可改变网格。例如可为场景手动增加：

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

这是静态漫反射近似，不提供镜面间接反射或正确透射。SH 只有低频方向信息；有限采样有噪声，普通三线性插值会跨墙混光，实体内探针也会污染结果。增大采样数能减少 Monte Carlo 噪声，不能解决这些结构性问题。

相机移动和窗口尺寸变化不要求重新烘焙。运行时若修改灯光、材质或几何，插件会拒绝继续使用已经失效的数据，提示重启并烘焙。动态物体和连续动画不是本版支持范围。

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

## 构建与复验

重新配置使用 [本地运行说明](C:/Users/Admin/Desktop/实时GI/Falcor/LOCAL-RUN.md) 中的工具链参数。已有构建目录时可单独构建新插件：

```powershell
Set-Location F:\
& '.\tools\.packman\cmake\bin\cmake.exe' --build build/windows-vs2022 `
    --config Release --target TraditionalProbeGI --parallel 8

& '.\tools\.packman\python\python.exe' '.\tests\probe_gi\run_validation.py'
```

验收会重新烘焙默认 Cornell 缓存，依次测试独立加载、移动相机、关闭探针对照、2048 spp PathTracer 参考和错误缓存。输出在 `build/probe-validation/`，日志在 `build/probe-*.log`。`results.json` 记录图像数值，`integration.json` 只在整个流程成功后生成。该目录和缓存位于已有 Git 忽略范围内。

参考图与探针不是相同的估计器：PathTracer 使用完整材质与更精细的可见性，而探针只重建漫反射低频光照。因此参考用于观察近似误差，不以逐像素相等作为通过条件。保存/加载一致性比较的是相同探针算法的两次运行。

## 本轮结果

Cornell / Vulkan / Release 已通过实际烘焙、独立加载、相机移动、探针开关及 6 类错误缓存检查。384 探针的文本缓存约 117 KiB；保存前/加载后的 HDR 最大差异为 0，所有像素有限。与 2048 spp PathTracer 参考的线性 RGB RMSE 为 0.104725。完整记录见开发契约末尾。

Room/Arcade 的入口可用，但本轮没有对它们执行完整数值验收。当前结果仍可见局部块状变化与偏暗，不应视为生产级探针方案。

探针结果：

![Cornell 传统探针结果](C:/Users/Admin/Desktop/实时GI/Falcor/build/probe-validation/load.Display.dst.0.png)

相同相机的 PathTracer 参考：

![Cornell 路径追踪参考](C:/Users/Admin/Desktop/实时GI/Falcor/build/probe-validation/reference.Display.dst.0.png)
