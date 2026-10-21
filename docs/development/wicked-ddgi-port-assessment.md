# WickedEngine DDGI 移植评估

2026-09-24。仅评估，尚未开始新增渲染Pass。

## 目标与结构

新增独立 `WickedDDGI` 插件及同名 Render Graph，加入 `scripts/GIPreview.py` 的算法列表。复用 Falcor 的场景、TLAS、相机可见性、材质读取、灯光和ToneMapper；通过适配层移植 WickedEngine 的DDGI算法。已有 TraditionalProbeGI 继续作为静态基线。

上游代码依赖 globals.hlsli、raytracingHF.hlsli、lightingHF.hlsli、bindless场景布局、SH工具和CPU调度，不能原样复制shader就完成移植。必须固定上游commit、保留许可证并记录每个适配差异。

## 核心工作

1. 建立独立Probe状态、射线结果、距离图、SH及历史资源，确定上一帧读取/当前帧写入的时序，避免跨dispatch或跨Probe读写混用。
2. 移植Fibonacci方向及旋转、最近命中、背面距离乘0.9、MISS处理和光照求值。硬件路径的FORCE_OPAQUE行为需保留为可核对选项。
3. 距离矩采用cos^64、权重截止1e-4、HIT减0.01、最大轴间距×1.5及98%历史混合；生成完整八面体边框，使用硬件双线性。
4. 移植radiance更新、L1 RGB SH投影、原来的光照历史估计，以及命中点查询上一帧Probe形成的多次反弹反馈。不能以现有三次反弹离线烘焙代替后仍称完整移植。
5. 移植P/Q使用、朝向混合、权重下限与压制、偏置、重定位的射线避墙部分。体素辅助脱困是独立依赖，应明确缺失状态。
6. 提供更新/冻结/重置、射线数、分辨率、朝向和重定位开关、矩与权重诊断，接入无UI脚本重放。

首个核心版本可使用固定每Probe射线预算，暂缓自适应ray allocation；这属于调度简化，必须记录。可用冻结后的距离矩隔离调度噪声，但不能据简化版结果宣称上游原版是否存在问题。

## 测试设计

- 同一房间、相机、材质与曝光；保存确定性旋转种子，捕获固定帧数和收敛趋势，不只看单帧。
- 主比较保持用户14×14预算；16×16原始分辨率仅作为独立诊断对照，不更改原方案预算。
- 原始行为对照和受控预算对照分别记录。Wicked默认朝向混合为0.01且带normal bias，不能悄悄保留旧wrap/bias后宣称原算法；也不能将原始参数下无硬边直接解释为距离矩已修复。
- 对照开启/关闭朝向抑制、重定位、背面距离修正，检查若硬边消失是否仅来自权重抑制或位置变化。
- 导出m2、mu²、方差、可见性及8 Probe归一化权重。先固定SH比较可见性链路，再比较完整动态GI，避免光照表示变化掩盖硬边。
- 移植数学内核使用相同合成射线输入对照；采样覆盖平墙、拐角、薄墙、HIT/MISS边界、Probe在实体内。记录缺失的体素脱困等路径。
- 若要断言“WickedEngine原工程也有/没有此问题”，仍需在固定commit的原工程内加载同一场景做交叉验证；移植版单独不足以证明。

## 工作量估算

以下为熟悉Falcor/图形渲染的一名工程师有效工作量，不是当前助手会话的交付时间承诺。包含实现、调试和验证，尚未经过编译原型测量。

| 工作 | 人日估算 |
| --- | ---: |
| 固定上游版本、算法适配与独立Pass资源框架 | 0.5–1 |
| 射线求交/光照、上一帧反馈与SH | 1–2 |
| 距离图、历史、边框与运行时查询 | 0.5–1 |
| 射线重定位、交互控制和场景状态处理 | 0.5–1 |
| 同视角复现、数值/图像对照、问题排查 | 1–2 |

核心可比较版本总体约4–7人日；第一张能跑的画面可能1–2人日，但不能作为可靠比较完成。若补齐体素辅助脱困、自适应射线分配及原引擎交叉验证，预计另加2–4人日，合计约6–11人日。范围最大的不确定性是材质/灯光语义适配、历史反馈稳定性及原引擎场景一致性。

建议按核心可比较版本立项。主框架改动小，算法插件工作量中等偏大。第一阶段里程碑是可重复的固定场景动态DDGI与矩诊断；结果未必能消除硬边，但能更可靠地区分动态更新、背面规则、重定位和矩表示本身的影响。

## 核对源码

- https://github.com/turanszkij/WickedEngine/blob/master/WickedEngine/shaders/ddgi_raytraceCS.hlsl
- https://github.com/turanszkij/WickedEngine/blob/master/WickedEngine/shaders/ddgi_updateCS.hlsl
- https://github.com/turanszkij/WickedEngine/blob/master/WickedEngine/shaders/ShaderInterop_DDGI.h
- https://github.com/turanszkij/WickedEngine/blob/master/WickedEngine/shaders/ddgi_rayallocationCS.hlsl
- https://github.com/turanszkij/WickedEngine/blob/master/WickedEngine/wiScene.h
- https://github.com/turanszkij/WickedEngine/blob/master/LICENSE.txt

Falcor接入点：`Source/RenderPasses/CMakeLists.txt`、`scripts/GIPreview.py`；现有快照代码需要支持新Pass，不能直接假定现有TraditionalProbeGI专用接口可无改动复用。
