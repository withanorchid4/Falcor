# 独立 Surfel GI

移植自 [W298/SurfelGI](https://github.com/W298/SurfelGI/tree/8361942f7d799632b32d37356b8057814456a8a2)（固定提交 `8361942f`），保留 `LICENSE.W298`（MIT）。
这是基于 GIBS 2021 思路的实验实现，不是 EA 官方 GIBS。

启动 `Run-Falcor.cmd`，选择 `SurfelGI` 和场景。也可以在 Mogwai 的 Active Graph 中选择 `SurfelGI`。
默认开启 Falcor AccumulatePass，可在 Accumulate 面板开关。移动相机会重置屏幕累积，但表面缓存继续更新。

## 渲染组织

`GBufferRT → Surfel → Lighting → Accumulate → Display`

Surfel 内部依次执行：计数准备、几何跟随和网格计数、网格偏移分配、网格列表构建、路径追踪、光照与深度积分、表面生成、屏幕查询。
最终像素直接插值 surfel；没有额外的屏幕 final gather、NRD 或 ReSTIR。
主可见性、材质与灯光来自当前 Falcor；不修改共享场景的材质。

## 默认配置

- 容量 32768 个 surfel；固定 64³ 相机中心网格。
- 网格大小在载入场景时根据场景范围和相机位置估算，支持手工 cellSize。
- 每个可见 surfel 请求 4–16 条起始路径；总起始路径缓冲上限 524288。
- 起始路径可包含多次场景追踪及阴影射线，不能把上述预算等同于总 BVH 射线数。
- 默认显式追踪 3 跳后尝试查询缓存，缓存缺失最多追踪 6 跳；用于探索的 sleeping surfel 对应 6/12 跳。
- 默认 targetArea=2048；这是原项目半径公式的参数，不等于实际覆盖的像素数。
- 缓存保留 Multiscale Mean Estimator；邻居 irradiance sharing 默认关闭。
- 原版 ray guiding 的离散概率与立体角 PDF 不一致，入口禁用，使用正确归一化的均匀半球采样。

## 主要修正

- 按 `Li*cos(theta)/(pi*pdf)` 缓存 E/pi，Lambert 合成只乘一次 albedo。
- 修正多灯采样漏掉最后一盏灯、ByteAddressBuffer 元素索引未乘 4、未初始化射线数据和随机数状态。
- 移除错误的 roulette 失败后仍添加缓存贡献的分支；改为显式跳数加末端缓存。
- 统一环境查询方向；恢复 alpha test；使用当前 Falcor 材质接口和主表面法线修正。
- 不再在 setScene 中改写场景所有材质。
- 每帧重建前清空网格；可见 surfel 使用原子标记续期。
- 每 tile 随机选一个生成候选，避免无效像素提前退出后其他线程执行组同步。
- 不在生成/追踪过程中销毁其他线程正在查询的 surfel；由更新阶段按寿命回收。
- 原子分配失败不再把空闲计数减成负数；后台 sleeping surfel 至多占用前半池容量，优先保证屏幕表面覆盖。
- 新建/复用 surfel 的深度矩初始化为搜索半径，而非零距离遮挡；修正深度方向坐标的整数除法。
- 邻居光照读取独立历史缓冲，避免同一 dispatch 中读到部分更新结果。
- 参数和显示模式修改通知 Accumulate 重置；保留 alpha test 和双面射线命中。
- 复用项目 GBufferRT，不使用上游辅助 GBuffer/VBuffer。

## 验证与限制

`tests/ddgi/surfel_unit_environment.py` 检查单位环境光下反照率 0.5 的 Lambert 平面。
`tests/ddgi/surfel_validation.py` 对 CornellLambert 和 SponzaLambert 保存预热后累积结果及 GPU 计时。
`tests/ddgi/report_surfel_validation.py` 生成 MSE、HDR-FLIP、收敛曲线和热力图。
`tests/ddgi/surfel_preview_check.py` 验证启动器使用的图集、图切换、材质不变、默认累积与缓存重置。

新机器需要重新配置 CMake 并编译 Release 的 `Surfel` 插件；仅同步 Python 脚本不会生成 DLL。

该路径针对漫反射缓存；本轮验证使用 Lambert 场景。没有实现完整镜面/透射 GI、GIBS 2024 的 probe 回退或分级无限范围网格。
缓存覆盖、深度近似和插值仍可能导致细小黑点、边界偏差或漏光。长时间 Accumulate 能降低随机噪声，不能消除这些系统误差。

## 全分辨率查询优化

查询单独使用 48 字节紧凑结构，保留 float 精度；每帧在积分/生成之后整理数据。
16×16 线程组内所有有效像素属于同一格子时，共享加载前 128 个候选，尾部继续全局遍历；跨格子组回退到全局路径。
不截断候选，不改变距离/法线/深度可见性权重。无效线程参加所有组同步后才退出。
默认 queryCompact=True、queryShared=True、queryMark=True。前两个开关保留用于性能对照。
queryMark=False 与 lockSurfel=True 仅用于冻结缓存消融；正常运行必须保留可见标记以维护寿命。
测试脚本：tests/ddgi/surfel_optimization.py，报告脚本：tests/ddgi/report_surfel_optimization.py。
