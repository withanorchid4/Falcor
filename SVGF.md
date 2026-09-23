# PathTracer + SVGF

双击 `Run-SVGF.cmd`，默认以 Vulkan 打开 Room。也可以运行：

```powershell
.\Run-Falcor.ps1 -Renderer SVGF -Scene Cornell
```

这个启动入口会暂停场景时间，便于观察静态降噪。相机仍可移动。运行中手动加载图不会暂停时间；若 `Frames since reset` 一直为 1，请排查场景动画，优先暂停时钟。关闭 Scene Settings → Animate Scene 也会停止更新，但可能改变 FBX 的节点变换，因此本启动器采用暂停时钟的方式。

已经在 Mogwai 中时：File → Load Script（Ctrl+O），选择项目 `scripts/PathTracerSVGF.py`，再在 Active Graph 选择 `PathTracerSVGF`。加载脚本不主动加载场景，继续使用当前场景和相机。

## 三种输出

| Output | 含义 |
|---|---|
| `ToneMapperSVGF.dst` | 默认：SVGF 时空降噪后的画面 |
| `ToneMapperRaw.dst` | 同帧 PathTracer 原始结果，用于直接比较 |
| `ToneMapperReference.dst` | 普通无限帧累积，静止时用作参考 |

SVGF 直接读取当帧线性 HDR，不需要等 Reference 累积，也不应在它前面串接普通 AccumulatePass。三个 ToneMapper 初始曝光一致；手动修改时请保持一致以便比较。

## 参数

- PathTracer → Samples/pixel：默认 1，先体验，再尝试 4 或 8。没有默认关闭焦散或限制亮度。
- SVGF → Enable SVGF：关闭后直通原始 HDR。
- Demodulate diffuse albedo：本图默认关闭，因为输入含有镜面/透射，不能全部按漫反射颜色去调制。关闭可避免玻璃发黑或反射染色，但会损失部分纹理细节；不是 NRD 式信号分离。
- Reset history：手动清历史；突然跳视角、切换图后看到残影时使用。
- Frames since reset：清历史后执行的帧数，不是每个像素的有效样本数；官方每像素历史长度最多 32。
- Iterations：默认 4，增加会扩大多尺度空间滤波范围、增加耗时，也可能损失细节。
- For Color：默认 10，越大越允许混合亮度不同的邻居。
- For Normal：默认 128，越大越拒绝法线不同的邻居。
- Alpha：默认 0.05，增大更快响应新光照，但噪声也可能增加。
- Moments Alpha：默认 0.2，控制亮度统计量的时间响应。
- Feedback：默认 1，选择反馈至下一帧的滤波层级；建议初期保持默认。

Reference 的 Auto Reset 与 SVGF 独立。如果 Frames accumulated 持续为 1，应排查参考累积的重置来源，不能据此判断 SVGF 没有工作。Auto Reset 关闭时，移动相机后必须 Reset 参考分支。

## 实现与限制

复用 Falcor 的 SVGF 时间重投影、方差估计、à-trous 保边缘滤波。当前 Vulkan 后端无法创建官方示例所用的 GBufferRaster（缺少 ROV），因此改用 GBufferRT，并在 SVGF 打包阶段生成缺少的表面位置/法线变化率。添加历史清理按钮与场景/参数变更时的清理逻辑。原 PathTracer、普通 PathTracer 脚本和探针算法未改动。

该版本把完整颜色作为一个信号处理，不能像 NRD 示例一样分别处理漫反射、镜面反射、玻璃透射。镜子、玻璃、突然显露区域、高能量 firefly 仍可能有噪声、模糊或拖影。它是有偏的实时预览，不能代替未降噪的高采样 GI 参考图。

设计与实际验证记录见 `docs/development/path-tracer-svgf.md`。

Room 验证中发现原始 PathTracer 的个别帧含 NaN，普通 Reference 累积会保留这些异常。本次扩展了 SVGF 的非有限输入与历史保护，但没有修复路径追踪源头。严谨评测前需另外解决原始输出的有限性问题。
