# 复现本次实验

运行目录：`F:\build\gi-evaluation\2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox`；独立程序：`F:\build\gi-evaluation\2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox\runtime/Mogwai.exe`。原产品源码和部署文件未修改。`source-record.json` 保存实际 shader 与二进制 SHA-256，`source/` 保存 DDGI、PT、材质 shader 和 DDGI host 源码快照；`git-status.txt` 与 `working-tree.patch` 记录实验时已有改动。独立运行目录共用未修改 DLL 与依赖；PT shader 独立复制。

本次测量补丁只在 `addToPathContribution` 中排除 `vertexIndex == 1` 的贡献。PT 的后续路径继续正常跟踪，关闭 NRD demodulation 后读取漫反射 AOV；同时保留完整间接光输出用于核查。`PathTracer.slang.original`、`PathTracer.slang.evaluation` 和 `pt-indirect.patch` 保存补丁。它们不是产品修复。

固定状态文件为 `F:/build/gi-evaluation-current.json`。以下命令会重跑本次工作目录；另做新实验时先建立新状态与结果目录，避免覆盖。

```powershell
python -X utf8 "F:\build\gi-evaluation\2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox/run.py"
python -X utf8 "F:\build\gi-evaluation\2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox/control.py"
python -X utf8 "F:\build\gi-evaluation\2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox/score.py"
python -X utf8 "F:\build\gi-evaluation\2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox/finalize.py"
```

`run.py` 依次运行当前材质 DDGI、PT A、PT B。`control.py` 运行 Lambert PT A/B；Lambert DDGI 使用同一 capture.py，环境设置 `GI_CASE=ddgi`、`GI_OUT=lambert-ddgi`、`GI_SCENE=F:\build\gi-evaluation\2026-11-16_20-17_Falcor-DDGI-vs-PT_CornellBox/lambert.pyscene`。所有运行均设置 `FALCOR_DEVMODE=0`、`FALCOR_MEDIA_FOLDERS=F:/media`、`GI_SMOKE=0`，命令为 `Mogwai.exe --device-type d3d12 --headless --deferred --script capture.py --width 960 --height 540 --logfile <log>`，工作目录 runtime。capture.py 使用快照 scene.json，而非用户正在编辑的灯光配置。

PT 8 spp/帧 × 4096 帧，fixedSeed=frame，第二序列加 104729；Default 后端审计为 GI_CASE=pt-default、GI_PT_TRACE=Default、GI_PT_FRAMES=512。审计结果见 audit.json。采集与计时详情见 captures/。

评分依赖 Python、NumPy 2.5.4，以及 `F:/build/official-ddgi/python-libs` 的 OpenEXR 3.5.4、flip-evaluator 1.7、Pillow 13；Magma 色表读取 matplotlib 数据文件。冻结的 FLIP 曝光取此前官方实验，不随候选改变。默认产品场景与显示配置未被改写。
