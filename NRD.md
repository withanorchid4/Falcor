# 官方 PathTracer + NRD

双击统一入口 `Run-Falcor.cmd`，在 **Active Graph** 中选择 `PathTracerNRD`；同一窗口也能切换普通 PathTracer 和 TraditionalProbeGI。`Run-NRD.cmd` 保留为初始选择 NRD 的快捷入口。其他场景可用 `Run-Falcor.cmd -Renderer NRD -Scene Cornell`，也可以从程序的场景加载入口换场景。

组合脚本 `scripts/GIPreview.py` 加载基于官方示例的 `scripts/PathTracerNRD.py`。按用户要求，PathTracer 默认改为 8 spp（上游示例为 1 spp）；其余参数与连线沿用官方配置，包括 Halton 32 相机采样、NRD 降噪、DLSS 启用且使用 Balanced 配置。启动时暂停场景时钟，方便静态观察，相机仍可移动。

## 显示结果

- Active Graph：`PathTracerNRD`。
- Output → `ToneMapperNRD.dst`：NRD 降噪经过 DLSS 重建及色调映射后的结果，默认输出。
- Output → `ToneMapperReference.dst`：相同 PathTracer 输入经过普通累积后的参考结果。
- `AccumulatePass` 只控制参考分支；`ToneMapper*` 只控制曝光与显示。

NRD 使用多个 Pass：`NRDDiffuseSpecular` 处理漫反射与粗糙镜面；`NRDDeltaReflection` 和 `NRDDeltaTransmission` 处理理想反射、透射；另外两个 NRD Pass 计算相应运动向量。先保持官方参数，仅调 PathTracer 的 Samples/pixel 对比噪声/耗时。普通累积的 Auto Reset 应在移动相机或换场景时保持开启。

官方示例对 NRD 输入采用 `maxIntensity=250`，并在 ModulateIllumination 中设置 `useResidualRadiance=False`。因此降噪与参考分支不是严格等能量的无偏对照；不能将所有亮点下降都归功于滤波。DLSS 默认开启，配合 Halton 抖动处理最终画面的时间抗锯齿与重建。若仅为诊断关闭 DLSS，应同时将 GBufferRT 的 Sample pattern 改为 Center，否则会直接看到逐帧采样抖动；Center 会失去这部分抗锯齿效果。

修改默认脚本不会覆盖已运行窗口里的参数；重新通过 `Run-NRD.cmd` 启动即生效。当前窗口也可手动勾选 `DLSS → Enable`，Profile 保持 Balanced。

此版本 NRDPass 只支持 D3D12。运行中的 Vulkan 进程不能通过加载脚本切换 API，需通过上述入口新开程序。系统不需要另装“DX12”；项目自带匹配的 Agility 616 正式版运行库。初始化诊断与验证记录见 `docs/development/path-tracer-nrd.md`。
