# WickedEngine 逐项对齐实验

2026-09-24。实施前记录方案。沿用快照 `20260924-104702-ae8fb0`，通过 headless 脚本逐项重放，每完成一项检查画面后再进行下一项。

## 不变条件

- 内部距离图 14×14，原网格、相机、材质、SH、normal/view bias 不变。
- 每个 Probe 一次切比雪夫；关闭稀疏复用、额外 smooth 插值。
- 保留原快照及之前各档缓存，实验输出到独立目录。
- 不把强滤波消除暗块但增加漏光判为成功。

## 顺序

1. 去掉强方向滤波实验档，指数改为 WickedEngine 的 64。
2. 距离上限由 1.5×单元对角线改为 1.5×最大轴间距。
3. 运行时权重下限对齐：取消可见性 0.05 下限，改为朝向×可见性乘积下限 0.01；取消三线性每轴下限。
4. 检查生成阶段剩余差异，包括方向权重截止值 1e-4、命中距离减 0.01。每项独立检查。

位置重定位会改变 Probe 及 SH 内容，持续历史混合属于动态更新；不能与以上固定 Probe 的距离矩实验混为同一变量。分辨率、查询 bias、背面抑制保持用户约束，不盲目复制。

## 验证

每阶段输出最终 HDR/PNG、同一批选点的八 Probe 数据、配置与构建指纹。核对 SH 不变、缓存合法、14×14/bias 保持。与指数50、强滤波指数5和同SH射线可见性参考比较。方差、m2、mu² 使用相同物理范围展示。

## 实施与结果

五项按顺序逐项执行，每次看完 GPU 输出再继续下一项。基准 normalBias=0.05（按最小间距缩放）、viewBias=0；保持快照实际值。atlas 仍为 320×320 RGBA32F，384 Probe，1.5625 MiB，2048 距离射线/Probe。

| 累计阶段 | 平墙显示RGB相对射线参考MAE | 原A/B折角处 m2 斜率差 | Probe375 A/B 原始可见性 | 画面判断 |
| --- | ---: | ---: | --- | --- |
| 1. 指数64 | 0.080532 | 0.010362 | 0.9756 / 0.8086 | 星形硬边明显 |
| 2. 最大轴距离上限 | 0.079363 | 0.004700 | 0.8887 / 0.5888 | 局部形状变化，硬边未消失 |
| 3. Wicked权重下限 | 0.079360 | 0.004700 | 0.8887 / 0.5888 | 与上一项几乎相同 |
| 4. 方向截止1e-4 | 0.079333 | 0.004700 | 0.8882 / 0.5863 | 影响很小，硬边仍在 |
| 5. 命中距离减0.01 | 0.071368 | 0.004732 | 0.6659 / 0.2571 | 部分明暗边界更强，未解决 |

第二项使用现有 `distanceRangeScale` 表达同样的物理上限：本场景系数为1.0412237，使 `scale*length(spacing)=1.5*max(spacing)`。距离上限由1.565894降为约1.086963。这是此网格下的等价系数，不是可跨场景照抄的常量。最终MAE下降不等于硬边消失；参考是同SH、同bias、射线可见性后端，不是完整PathTracer真值。

距离矩图显示，缩短距离上限确实减弱了m2折角，但并未消除双线性插值的斜率变化。第五项降低mu后，可见性对相邻点的差异反而更大。以上只是本快照的结论，不能说明WickedEngine完整实现必然有相同画面。

### 代码与默认行为

- 默认角度指数及DDGI预设从50改为64；原强滤波25/10/5仅保留历史实验材料，不作为当前默认。
- 新增 `wickedWeights`（运行时开关），UI位于 Distance visibility → WickedEngine weight floors。仅在DDGI距离矩模式生效，射线后端仍严格0/1；保留wrap²+0.2，不剔除背面。
- 新增 `distanceWeightCutoff` 和 `distanceHitBias` 烘焙参数，UI可独立调整，默认均为0。没有把失败的后续候选自动变成默认修复。
- 使用非零新烘焙参数的缓存保存为v5，包含两个参数并校验；v3/v4默认参数继续兼容。SH、图尺寸、运行时切比雪夫次数不增加。
- 查询点normal/view bias未对齐；没有接入Probe重定位、动态历史混合、16×16或半精度存储。这是固定Probe的五项对照，不是完整移植。

### 实际验证

Release编译成功，五项GPU烘焙/渲染、六点权重公式核对、距离矩合法性、CPU矩重建与GPU读数对照均通过。五组SH相对原参考差为0，原快照缓存哈希未改变。v5缓存重载、保存快照再重放、Wicked开关在射线后端的开关对照、旧v4/p50回归的HDR最大误差均为0。新参数不匹配的缓存被正确拒绝。

### 查看与重跑

- `build/probe-wicked-alignment/comparison.png`：八张整帧对照。
- `build/probe-wicked-alignment/moments/left-m2-mu2.png`：同范围矩对照；另外有方差、可见性及连续曲线。
- Mogwai Load Script：`scripts/LoadWickedProbeAlignment.py`，默认加载第一项p64；编辑开头STAGE为range/weights/cutoff/hitbias查看对应累计阶段，不重新烘焙。
- GPU脚本：`tests/probe_gi/wicked_alignment.py`，通过环境变量PROBE_WICKED_STAGE选择一个阶段。各阶段依次运行并检查，不并行跑GPU。
- 离线分析：`analyze_ddgi_moments.py --sweep build/probe-wicked-alignment` 后运行 `analyze_wicked_alignment.py`。
- 回归脚本：`wicked_regression.py`；数据见 `regression.json`、`metrics.json`、`result.json`。

参考源码：WickedEngine `ddgi_updateCS.hlsl`、`ShaderInterop_DDGI.h`、`wiScene.cpp`（2026-09-24核对master）。
