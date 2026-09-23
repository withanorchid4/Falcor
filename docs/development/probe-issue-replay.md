# Probe 问题快照与脚本复现（2026-09-24，实施前约定）

按用户要求，复现/验证使用命令行无窗口渲染，不使用 Computer Use。第一版聚焦已完成烘焙的静态 TraditionalProbeGI 标准图（Visibility / Probes / Display），不承担 PathTracer/NRD 历史状态复现。

## 流程

1. 用户在问题视角加载一次 SaveProbeSnapshot.py。保存独立目录：当前图导出、完整相机参数、分辨率、时钟时刻、Probe运行/烘焙参数、选点、缓存副本及SHA256、场景文件身份、环境光/常用材质/解析光参数、干净PNG/HDR数值及EXR。生成唯一目录，不覆盖已有案例。
2. 脚本需要 Probes.ready 且未baking，复制当前匹配的完整缓存；不触发Bake。临时关闭debug覆盖层和暂停时钟获取干净画面，finally恢复原状态和原图输出。选点数据另存，不自动控制GUI。
3. 命令行 replay_probe_snapshot.py <case-dir> 启动独立 `Mogwai --headless --deferred`，只重建快照的图，恢复相机/曝光/参数、读取快照缓存、渲染干净画面和选点数据后退出。每次输出唯一runs子目录，原始快照不变。通过明确参数可改运行参数或执行rebake到本次run的新缓存。
4. 比较PNG/HDR数组，输出并排图/差异图/数值误差和选点前后数据。场景/缓存哈希不匹配应拒绝继续，而非静默使用新数据。记录实际DLL/shader哈希，便于识别代码变化。

## 准确性与边界

- Falcor SaveConfig不包含完整镜头参数，也不会复制缓存；Scene.path常为导入的FBX，不是带材质调整的pyscene。快照单独记录相机镜头，若存在同名pyscene则使用该入口，回放后恢复当前公开材质/光源属性。
- 实现核验发现headless的SaveConfig会解引用空窗口（SampleApp::getConfig），因此不用该API：场景身份从已加载缓存头读取，图直接导出，其他状态显式保存。保存时临时将timeScale置0并恢复，避免依赖未公开的Clock.isPaused接口，也不改变用户播放/暂停状态。
- 第一版支持现有Room/静态标准材质工作流；不是通用场景资产归档。场景网格/纹理仍引用本地文件，需保持资产不变；不承诺捕获交互式纹理替换、几何编辑、动画历史、自定义材质内部数据或自动曝光历史。自动曝光启用时拒绝快照，要求固定曝光以保证可比性。
- 保存实际当前状态，参数覆盖必须显式记录在本次run。raw HDR用于数值比较，Display PNG用于视觉比较，不把任意亮度差异直接判定为修复成功。
- 先开发文档，再实现脚本；优先使用现有Python接口，不修改Falcor框架。验证：Room改变相机/FOV和bias后保存，在新进程无修改回放，对照图像/调试参数；参数覆盖与rebake路径；缓存/场景变更拒绝；用户进程及缓存不受影响。

## 实测结果及实现说明

- 已实现 `scripts/SaveProbeSnapshot.py`、`scripts/ReplayProbeSnapshot.py`、`scripts/probe_snapshot.py`、命令行 `scripts/replay_probe_snapshot.py` 和 PowerShell入口 `Replay-ProbeSnapshot.ps1`。无需C++重新编译。
- Falcor内置Python没有numpy，捕获端使用现有FrameCapture与随程序附带的FreeImage.dll，等待异步写盘完成；无需给用户程序装包。PNG、EXR与RGB float32 `.f32`保留。命令行对比使用Codex已有Python/numpy。
- `tests/probe_gi/snapshot_capture.py` 在Room设置不同相机位置、焦距31、frameHeight23.8、曝光0.5、normal/view bias=0.075/0.12、base variance=2e-6、环境强度17，保存后在独立进程重放。HDR与Display逐像素最大差、MAE、RMSE均为0，相机/缓存完全一致。最新案例 `build/probe-snapshot-validation/cases/20260924-015742-0f6352`。
- intensity=0.5覆盖测试产生预期非零差异，保持相机和缓存不变；显式rebake测试将低样本新缓存写入本次run，原始快照仍通过校验。`tests/probe_gi/snapshot_integrity.py` 验证图/缓存被修改、场景身份不匹配均拒绝；输入快照未被改动。
- PNG经过读取检查，输出为当前问题墙面视角。build身份记录实际运行的Mogwai插件和着色器，而非假定正式运行目录。
- 未操作用户窗口、未保存用户当前视角（需要用户主动运行Save脚本）；未commit。
