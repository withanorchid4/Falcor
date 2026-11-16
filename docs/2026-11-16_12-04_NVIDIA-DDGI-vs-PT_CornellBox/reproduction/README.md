# 复现本次对比

渲染来源为 NVIDIA RTXGI-DDGI 1.3.7 Test Harness，评分使用 NVIDIA flip-evaluator 1.7。所有路径沿用本机 F: 映射，F: 指向 `C:/Users/Admin/Desktop/实时GI/Falcor`。配置快照包含绝对路径；迁移电脑时需要一起修改。

`Run-Captures.ps1` 顺序运行 DDGI、PT-A 和 PT-B，避免并行争用 GPU。它依赖已编译的 `F:/build/official-ddgi/build/samples/bin/d3d12/Release/TestHarness-Evaluation.exe`，以及保留在 `build/official-ddgi/evaluation/2026-11-16_12-04_NVIDIA-DDGI-vs-PT_CornellBox/` 的测试副本。重复运行会更新该临时目录的原始采集文件，正式 EXR/报告不会被采集脚本覆盖。

测试副本复制了官方 `samples/test-harness/shaders`，并通过目录联接引用官方 `data`、`include` 和 `rtxgi-sdk`。这三个联接都必须存在。PT-A 和 PT-B 分别使用本目录的 `PathTraceRGS-pt-a.hlsl` 和 `PathTraceRGS-pt-b.hlsl`；DDGI 副本使用 `PathTraceRGS-ddgi.hlsl`，其中的 PT 分支在 DDGI 模式下不执行。其它着色器保持官方原样。

重新编译采集程序时，将 `main.cpp.evaluation`、`Direct3D12.cpp.evaluation`、`Window.cpp.evaluation` 临时复制到官方源码 `samples/test-harness/src/` 对应文件，再执行：

```powershell
& 'C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe' --build F:/build/official-ddgi/build --config Release --target TestHarness-D3D12 --parallel 8
```

编译成功后另存为 `TestHarness-Evaluation.exe`，再恢复原源码和原 `TestHarness-D3D12.exe`。本目录保存了修改前的三个源码文件；原可执行文件备份为测试工作目录下的 `TestHarness-D3D12.original.exe`。本次已经完成恢复，见 `source-audit.json`。修改前的 Direct3D12.cpp 已包含此前用于选中 NVIDIA 显卡的 VendorId 筛选。

采集补丁只在 `GI_EVAL_DIR` 环境变量存在时启用。`GI_EVAL_START` 指定第一张正式采集帧，`GI_EVAL_COUNT` 指定数量，`GI_EVAL_END` 限定退出帧。DDGI 为 65537/32/65568；两份 PT 为 32769/1/32769。官方 PT 的累积帧计数使最后得到恰好 32768 spp，已读取 accumulation 的 alpha 验证。

`.raw` 文件前 16 字节为四个 uint32：宽、高、DXGI 格式、每行字节数；后接连续原始纹理行。DDGI 为 float16 RGBA；PT accumulation 为 float32 RGBA，RGB 除以 alpha 才是 radiance。mask 来自 GBufferB.w >= 0。

离线评分命令：

```powershell
python -X utf8 F:/build/official-ddgi/evaluate_cornell.py
```

本目录保留相同脚本。它读取 `F:/build/official-ddgi/evaluation-current.json`、已采集 raw 与工作目录中的 `flip-parameters.json`。依赖位于 `F:/build/official-ddgi/python-libs`：flip-evaluator 1.7、OpenEXR 3.5.4、Pillow 13，以及 Matplotlib 3.11.2 的 Magma LUT；NumPy 使用本机 2.5.4。评分会重新生成 EXR、两张 PNG、CSV 和 JSON。

HDR-FLIP 的曝光参数由 PT 可见场景矩形 x=241..675、y=53..486 自动估计，再冻结。该矩形全部是有效表面；不让画面外围的大片黑色背景主导曝光范围。实际评分仍计算完整 960×540 画面，再应用 mask。显示图单独采用相同的 +3 EV，并未改变评分输入。

`capture.patch` 是采集补丁，`pt-*.patch` 是 PT 信号和种子补丁，`CMakeCache.txt` 是构建设置，`*-gpu-timing.csv` 是未经筛选的官方 GPU 时间戳记录。正式 `timing.csv` 仅取无读回的帧 14350–16370，避免逐帧导出干扰计时。PT 早期检查点、DDGI 收敛检查点及运行日志保留在工作目录，正式结论和局限记录在上一级报告中。
