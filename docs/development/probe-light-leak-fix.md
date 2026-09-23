# Probe 剩余漏光排查与修复（2026-09-24）

## 基线

提交 `4eab70b3` 已保存此前的距离矩、诊断、快照重放和背面抑制实现。
使用快照 `20260924-021543-642825`，开启 normalHemisphere，另用双房间隔墙场景检查正面却被隔墙挡住的 Probe。

## 实施顺序

1. 根据已有 GPU 全画面数据，找出剩余漏光最强的实际 Probe 和查询位置，比较 Q/P、d、mean、variance、实际命中距离与权重，避免把直接光或材质反射误认成 Probe 漏光。
2. 针对命中距离与距离矩不一致的来源，先在独立烘焙/运行目录做距离统计对照。尝试减少远距离离群样本的影响，或保留方向局部几何信息；如失败，保留结果后转向其他方案。
3. 同时检查错误漏光和错误遮挡，以射线可见性为几何参考（不当作完整光照 ground truth）。不能仅通过把所有 Probe 光照变黑来通过验证。
4. 保持旧缓存可读取；任何改变烘焙语义的正式方案必须有独立缓存标识/元数据与版本校验，用户旧缓存不得被覆盖。
5. 每像素仍优先维持 8 个邻居、每 Probe 一次 Chebyshev，不采用 4 次概率计算后插值。正式增加的成本需要明确说明。
6. 验证原始视角、第二视角、双房间遮挡和开放可见场景；确定有效方案后更新代码、文档，编译并用脚本重放。

本阶段变更留在工作区；用户要求的 commit 已先完成。

## 实验观察与采用方向

- 墙角 Probe 383：d≈.4616，实际 hit≈.4594，原 angular14 mean≈1.1882，V=1。这种漏光不能靠降低方差修复。
- angular32 / 8192 rays / exponent256 仍保留宽亮边，不采用。
- texelLocal64/128、每 texel32 rays：128 明显优于64，但交界处仍有窄亮边。
- 128 配合 viewBias .05（本房间约2.6cm）消除了可见的宽亮边；.02 仍有少量锯齿。1e-8 基础方差相对1e-6改善很小，因此优先保留原1e-6基础值。
- 不修改 SH 光照算法，不增加运行时纹理读取/射线。代价是距离 atlas 和烘焙时间：384 probes 的128 atlas约103MiB，32样本/texel约2.01亿距离射线。不是无成本修复。

正式接入计划：提供 **Leak-resistant preset** 按钮，并将预览脚本的默认距离设置改为 texelLocal128 / 32 rays，normalBias=.05、viewBias=.05、normalHemisphere=true、Bilinear、varianceBase=1e-6。旧显式图配置和两种烘焙模式保持可用。新配置需要新距离缓存。

为避免新质量预设覆盖旧 texel-local 缓存，自动 texel-local 文件名增加 `-r<resolution>-s<samples>`。若新文件不存在，可校验并读取旧无参数后缀文件；新 Bake 总是写带参数的新路径。显式 cacheFile 路径遵从原行为。安装验证好的新缓存到新自动路径，保留旧 angular 和 texel-local 文件。

## 验证与安装结果

最终 `1e-6` 配置已通过离屏 D3D12 验证，输出位于 `build/probe-leak-validation/`。新方案与相同 bias、相同 SH 的射线可见性参考之间，全画面线性 RGB 平均绝对误差：原视角 `4.449e-6`，第二视角 `7.707e-6`，隔墙场景 `7.471e-6`。这些数值衡量距离矩可见性近似，不代表与 PathTracer 的光照误差。

`first-comparison.png`、`second-comparison.png`、`fixture-comparison.png` 已检查：宽亮边明显消退。旧图采用旧 bias，因此 metrics.json 中旧图对新射线参考的差异包含 bias 改动；只用它描述整体方案效果，不归因于单一参数。

开放地面平均 RGB 为 `0.264586`，相对射线参考 MAE `0.000202879`；九个地面位置的 36 个有三线性贡献的可见 Probe，其可见性均为 1。隔墙场景新旧 SH 系数逐项一致，排除了改变烘焙照明而使场景变黑的情况。移动相机检查保持有限权重、Ready 状态和缓存不变。旧缓存回退、参数不匹配拒绝、新 Bake 不覆盖旧文件均通过实际加载/烘焙测试。

已安装 DLL SHA256：`6377c4f232bdca0a331f44df9edd49f0b0e97aa16c7a05a2dd77a87f1db10294`。原插件备份在 `build/probe-leak-fix-staging/previous-TraditionalProbeGI.dll`。

Room 新缓存安装到 `build/probes/grey_and_white_room-9e2df5c8ed1ac29-texel-local-r128-s32.shprobe`，SHA256 `c8769fbf2b6b6a762edfb9a53000acaa32e0e73f0c980f4858e9596de8bf323f`。旧缓存和原问题快照保持不变。

`tests/probe_gi/leak_installed_smoke.py` 用生产目录的 Mogwai、默认预览图和自动缓存路径成功加载，无烘焙派发；恢复问题视角后的 HDR 与已验证新方案最大绝对差为 **0**。记录在 `build/probe-leak-installed/`。Python 编译检查及 `git diff --check` 通过。

限制：128 分辨率的内存与烘焙成本较高；view bias 会随相机变化，仍可能在薄几何或其他方向上误判。矩方法不能保证所有场景严格不漏光，本次结果不能代替新场景验证。本轮只提交了开工前检查点，后续修改保留未提交供审阅。
