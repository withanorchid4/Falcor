# DDGI 距离矩与权重对照

2026-09-24，先记录计划，再实施。

## 范围

同步 NVIDIA RTXGI-DDGI 的静态距离矩重建和运行时权重数学，独立实现；不复制上游 shader。保留本项目 SH 光照、静态烘焙、已有射线序列和缓存格式，不宣称实现完整动态 DDGI。参考 [ProbeBlendingCS](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/ProbeBlendingCS.hlsl) 和 [Irradiance](https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl)。

保持 14×14 距离图、现有 normal/view bias 和 SH 烘焙参数。不加入 Probe relocation/classification，不恢复背面半球剔除，不启用 HIT/MISS 分离。稀疏调度仍与可见性方法独立。

## 实施

1. 复用现有 angular 烘焙：共享全方向射线，通过 `max(dot(texelDir, rayDir), 0)^50` 同时过滤距离和距离平方。不是对已经生成的图额外加高斯模糊。使用 2048 rays/probe 作为本项目静态预设，不称为官方推荐样本数。
2. 新增 `applyDDGIPreset()` 和 `DDGI-style preset (14)` 按钮：14×14、angular、指数 50、2048 rays/probe、距离范围 1.5 倍格子对角线、双线性、moments 后端、启用朝向和 DDGI 权重。保持查询 bias、SH 参数和稀疏开关。需手动 Bake/加载匹配缓存。
3. 新增运行时 `ddgiWeights`，默认 false，允许与旧版直接比较。moments 后端使用绝对矩差、不加基础方差，d<=mean 时显式返回1避免0/0；d>mean 时计算一次切比雪夫并立方，最低可见性0.05。朝向×可见性在0.2以下连续压低，再乘各轴最低0.001的三线性权重，按实际总权重归一化。
4. 射线后端保留严格0/1可见性，不能被0.05下限复活被遮挡 Probe；新 DDGI 权重规则仅对 moments 后端生效。选点与最终着色使用同一函数，报告原始矩概率与实际使用的可见性。
5. 旧快照默认继续旧规则；新参数序列化并可通过重放覆盖。新预设不覆盖现有默认脚本配置，先作为对照方案。

## 验证

编译插件并脚本运行固定快照 `20260924-104702-ae8fb0`。保留原快照和缓存，输出独立缓存/图片：原版、仅 angular（范围仍2）、angular+范围1.5、完整 DDGI 权重、射线参考。校验分辨率与 bias 没变、SH 烘焙结果一致、距离矩有限且范围合法；选点对照 CPU 权重公式；检查开关恢复、射线0/1和稀疏路径。比较画面及硬边附近数值，不把“更平滑”直接等同于“漏光修复”。

## 实施与验证结果

已编译安装 Release 插件；通过 `tests/probe_gi/ddgi_alignment.py` 的 GPU 检查及 `analyze_ddgi_alignment.py` 的离线图像检查。结果位于 `build/probe-ddgi-alignment/verified/`，包含 `comparison.png`、`edge-crops.png`、`result.json` 和 `metrics.json`。

- 保持 14×14，保持快照原值 normalBias=0.05、viewBias=0；预设另测任意 bias 与 sparse 设置不会被改动。
- 两次新烘焙的 SH 系数与原缓存完全相同；距离矩有限且满足缓存范围校验；原快照缓存哈希未变。
- DDGI 开关恢复、射线模式下开关 DDGI、DDGI 缓存重载的 HDR 差异均为0。
- 6 个选点 × 8 Probe 的 DDGI 原始可见性和最终归一化权重通过 CPU 公式对照；4×4 sparse 路径完成渲染。
- 原快照到本次 baseline 的 HDR 最大差为0.00022723，属于本轮重放的实际差异，不宣称逐位一致。
- 修正调试报告：射线模式中三线性权重为0的 Probe 不打射线，实际使用可见性报告0；不再把未使用的矩概率展示为射线结果。原始矩概率仍可单独查看。生产着色的零贡献没有变化。

Probe 375、像素 A=(520,417)、B=(521,417)：

| 方案 | A 最终权重 | B 最终权重 | A/B 显示 RGB 最大通道差 |
| --- | ---: | ---: | ---: |
| 原 texel-local，range=2 | 0.059026 | 0.000536 | 25/255 |
| Angular，range=2 | 0.060980 | 0.060253 | 0/255 |
| Angular，range=1.5 | 0.060866 | 0.058889 | 1/255 |
| Angular，range=1.5，DDGI 权重 | 0.060815 | 0.055505 | 2/255 |

这里的显示差值含8-bit PNG量化，不代表HDR差异为0。原 texel-local 为每 texel 32射线，即6272 rays/probe；angular 为共享2048 rays/probe，因此“仅 angular”表示切换距离矩生成模式，包含射线分布和总量变化，并非严格的相同射线预算实验。新预设总距离射线数为786432，atlas仍为320×320、RGBA32F、1.5625 MiB。

画面判断：特定 A/B 急变明显缓解，但整墙仍有星形暗块与墙角亮边。以同 SH、同相机的射线可见性图作为遮挡对照，显示RGB全图MAE分别为原版0.05475、angular范围2为0.06201、angular范围1.5为0.06177、完整DDGI权重为0.05992，不能把更平滑解读为整体遮挡准确性改善。该射线图只隔离可见性后端，不是完整 Path Tracer 真值。

DDGI预设作为可选对照保留，没有替换启动脚本的默认配置。本实验未使用动态hysteresis、RTXGI射线序列、irradiance纹理编码或Probe relocation/classification，结果属于本项目静态适配，不代表完整RTXGI的最终画质。

## 距离矩复核：滤波后折痕是否消失

使用 `tests/probe_gi/analyze_ddgi_moments.py` 读取本次三个缓存，复用原诊断 GPU 记录的逐像素 Probe ID、八面体 UV、位置和法线，按生产 shader 的折边双线性规则离线重建 `m2`、`mu^2`、`m2-mu^2`。这不是新 GPU 截帧，也没有重新烘焙或修改算法。固定 14×14、normalBias=0.05、viewBias=0；距离矩统一还原到世界单位平方，无 tone mapping，m2 和 mu² 使用相同线性 [0,1] 灰度范围。紫色表示该 Probe 不在像素的8个候选中。

重建结果与上一轮每种方案的 6 点×8 Probe GPU 记录对照，mean 最大误差小于 5.74e-7，variance 最大误差小于 3.92e-7。结果和图位于 `build/probe-ddgi-alignment/verified/moments/`：`left/upper/right-moments-comparison.png`、`probe375-line-comparison.png`、`result.json`。

**结论：滤波没有消除 m2 和 mu² 的斜率折痕。局部可见性急变的缓解，主要来自低方差区域被抬高，而不是插值斜率变连续。**

Probe 375 原 A/B 点的原始数值：

| 方案 | m2 A / B | mu² A / B | 方差 A / B | 原权重公式的原始 V A / B |
| --- | --- | --- | --- | --- |
| Texel-local，range=2 | 0.181671 / 0.162413 | 0.168930 / 0.162318 | 0.0127411 / 0.00009493 | 0.965943 / 0.008287 |
| Angular，range=2 | 0.205782 / 0.185981 | 0.180606 / 0.173674 | 0.0251768 / 0.0123073 | 1.000000 / 0.991486 |
| Angular，range=1.5 | 0.188822 / 0.177850 | 0.176682 / 0.171824 | 0.0121401 / 0.00602643 | 0.998005 / 0.967638 |

为隔离矩变化，图中的 V 对三种缓存统一使用原切比雪夫公式及基础方差，不包含新的 DDGI 最低权重或压缩；完整 DDGI 与 angular-range1.5 使用同一份矩，因此 m2/mu² 图完全相同。`result.json` 另记录无基础方差的 DDGI 原始概率。

沿同一平面上的连续位置线，texel 中心切换发生于 screen x=520.934603。其左右 m2 斜率（每屏幕像素世界单位平方）原版约为 -0.020657 / -0.000281，保持 range=2 的 angular 版约为 -0.021215 / -0.000645；相邻插值段仍有明显折角。range=1.5 版本约为 -0.011746 / -0.000479，幅度减小但折角仍在。这里只是斜率不连续，不是 m2/mu² 数值不连续。

因此不能仅以 A/B 权重变接近判定修复，更不能推论完整 DDGI 必然有同样问题。后续应同时检查矩的折痕、差值接近零时的敏感性、最终可见性与射线遮挡参考。让方差升高也可能让被遮挡 Probe 得到更高可见性；平滑与防漏光需要分别验证。
