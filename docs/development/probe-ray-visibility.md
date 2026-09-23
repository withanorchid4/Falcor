# Probe 实时射线可见性与距离对照

> 当前 stored mean 已改为 texel 内独立采样的均值、整数点读取；下文方向滤波和 version 2 的描述及数值属于早期版本。见 [当前距离采样方案](probe-texel-local-distance.md)。实时射线参考的语义保持不变。

2026-09-23，实施前约定。

目标：让距离矩误判可见性的情形可直接定位，并提供整幅画面的射线遮挡参考。保持既有 SH 烘焙和 version 2 缓存，不修改 PathTracer / NRD。

## 实施方案

1. `Distance visibility` 增加 `Visibility method`：`Distance moments`（默认）与 `Ray traced (debug)`。保留总开关 `Enable distance visibility`（改名为更准确的 `Enable visibility`）和方向权重开关；总开关关闭仍为原三线性插值。Python 属性 `visibilityMode` 为 `moments` / `rayTraced`，切换即时更新权重和选点检查，不作缓存失效或重新 Bake。
2. 射线模式从 Probe 出发，朝法线偏移后的 Q 发一条有限线段遮挡射线。起点不另加偏移，与烘焙第一段射线一致；TMin=0，TMax=|Q-Probe|−epsilon，epsilon=max(1e-6,minSpacing×1e-4)，排除端点自遮挡。三线性为零的邻居跳过射线。硬可见性 0/1 乘原三线性和方向权重，再按既有方式归一化；所有邻居被遮挡时输出零 Probe 光照。每像素最多 8 条额外射线，非实时性能目标。
3. Pick/Refresh 时，从各邻近 Probe 朝 Q 以及原始选点 P 分别求最近交点。求距离不能用 ACCEPT_FIRST_HIT_AND_END_SEARCH；复用烘焙 scatter hit groups，增加 distanceOnly payload 标志，ClosestHit 在材质着色前只返回 RayTCurrent，Miss 不计算环境光。沿用烘焙的双面/alpha-test/几何支持；玻璃仍作为几何遮挡，不做折射或多反弹。射线长度 max(距离图范围, 点距离+epsilon)，未命中显示 MISS（API 距离 -1），不能把最大距离假装成 hit。
4. 每个邻居显示两组世界单位距离：Q/P 各自方向的双线性采样距离均值、Probe 到点距离、最近 hit 距离；保留方差，并同时显示 moment V、ray V、实际采用的 V 和最终 w。Q 为生产采样，P 为排查 normal bias 的参考；均值是方向滤波后的统计量，不是单个 texel 原始射线。红/绿线改用 Probe→Q 的最近交点判断，与新参考方向一致，颜色不等同于距离矩 V。
5. 新数据只扩展调试缓冲区与 Python debugInfo，不写缓存。模式和 UI 参数可由 saveConfig 序列化。保留原 debugInfo 的 visibility 为距离矩 V，增加 appliedVisibility、rayVisibility、queryHitDistance、surfaceHitDistance、surfaceDistance、surfaceMeanDistance、surfaceVariance，负 hit 距离代表 MISS。
6. 为恢复固定世界坐标的旧选点、确保相机移动后仍能比较完全相同的点，增加 Python `inspectSurfacePoint(position, normal)`。验证有限位置及非零法线，复用现有选点检查路径；UI 仍使用右键 Pick。该接口只接受调用者已知的表面点，不自行把任意坐标投射到表面。

## 验证

2026-09-23 选点保存辅助脚本约定：使用现有 debugInfo / inspectSurfacePoint API，保存原始表面世界坐标、法线和 normalBias 到 build/probe-selection.json；恢复须在相同场景加载并完成缓存加载或烘焙后执行。不保存相机，不退出程序，不自动 Bake。无有效选点时拒绝覆盖文件。通过 File → Load Script 手动调用。

构建 TraditionalProbeGI；实际 GPU 场景验证：隔墙射线命中距离符合解析几何，受遮挡邻居在射线模式权重为零，可见邻居保留权重；Pick 显示 P/Q 及缓存均值；MISS 与端点情况不误标为命中；模式往返不改变缓存、样本数与 Ready，支持旧脚本无新属性。使用 Room 用户案例检查 342/343 距离。保存会话和相机后更新插件，加载原缓存展示 UI。只在有新失败时增加验证。

## 实测结果

- Release 插件和 D3D12 Shader 编译通过。
- `tests/probe_gi/ray_visibility.py` 通过：隔墙最近交点与解析几何最大误差 `2.10e-7`；24 个受遮挡邻居检测全部得到零权重；可见且有三线性权重的邻居仍有贡献。开放平面 MISS、表面端点容差以及相同世界选点恢复通过。
- 模式切换不改变缓存、Ready 或样本数；从距离矩切到射线再切回，HDR 最大差值为 0，所有输出有限。最终结果位于 `build/probe-ray-validation/2855015f/`。
- 原 Room 选点 `(4.5134568,0.1098647,-0.0126955)`，恢复原法线和 normalBias：

| Probe | Q 缓存均值 | Q 点距离 | Q 最近 HIT | P 缓存均值 | P 点距离 | P 最近 HIT | 距离矩 w → 射线 w |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 342 | 0.712334 | 0.578981 | 0.525730 | 0.728652 | 0.560440 | 0.542387 | 0.039662 → 0 |
| 343 | 0.637881 | 0.533512 | 0.484442 | 0.660645 | 0.513330 | 0.496795 | 0.046270 → 0 |

两者均为缓存 V=1、射线 V=0；P/Q 两个方向均在到达点前命中几何。该结果确认距离矩在本例误判可见性，不单凭此结果区分方向滤波、采样或缓存内容问题。未改变原用户缓存（SHA-256 一致）。结果及对比图位于 `build/probe-ray-room/`。
