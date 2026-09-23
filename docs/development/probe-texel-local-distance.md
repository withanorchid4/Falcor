# Texel 内独立距离采样（2026-09-23，实施前约定）

> 后续按用户要求增加运行时双线性读取，默认 Bilinear 并保留 Point 切换，见 [距离矩双线性读取](probe-distance-bilinear.md)。本文烘焙与缓存实现保持有效，原点读取的测试数值作为历史记录。

目标：识别距离图高频遮挡边界。按用户要求替换方向余弦滤波：每个内部 texel 独立在自己的八面体 UV 方格内均匀随机取样，发最近交点射线，等权平均 d/D 与 (d/D)^2。这里定义的是 UV 面积均匀平均，不声称是立体角均匀平均；同一 texel 内仍可包含多个表面。没有跨 texel 角滤波、双线性、mip 或历史滤波。运行时和 P/Q 调试均用同一个整数 texel Load。保留 SH 插值、法线偏移、切比雪夫和射线参考模式。

## 实施

- 距离采样与 SH 路径完全分离：SH 仍每 Probe 默认 2048；新增 distanceSamplesPerTexel，默认 16，可调 1..2048；距离分辨率 4..128，默认14。去掉 Angular sharpness UI，旧脚本 distanceExponent 仅告警并忽略，不再序列化。射线只查询最近几何，不计算光照或反弹，沿用双面和 alpha test。距离截断到 D，MISS 计 D。
- 在现有 RT 程序中新增距离烘焙分支和 RW atlas，每线程负责一个 texel。随机种子由 Probe/texel/样本索引决定，改变分帧批次不改变采样集合。先完成 SH，再分批烘焙距离；每次最多 8192 texel、65536 距离射线，单 texel 每批最多16。两阶段均完成才 Ready/保存。取消和改参清空两阶段进度，UI/API 区分两种样本单位。
- 保留 atlas 一圈布局但不读取边界；边界与空槽为 (1,1)，不再计算或混合邻居。移除旧距离射线缓冲、方向混合 ComputePass 和线性 sampler。
- 缓存升为 version 3，记录 texel_local_uv_point、分辨率、每 texel 样本数、范围与尺寸。拒绝旧版本并要求重烘焙。自动文件名加 -texel-local，保留旧缓存。继续完整性/有限数校验和原子保存。
- 调试说明标明 texel-local mean / point lookup。增加每邻居查询 texel 坐标到 debugInfo，便于验证同 texel 不同方向读值完全相同。

## 验证

编译插件及实际 D3D12 shader；使用独立测试缓存与头less进程，不操作当前用户窗口。验证128分辨率烘焙、同 texel 点采样不插值、平面解析距离范围、SH样本数不改变距离样本、分批一致性、取消与改参、version 3 重新加载及旧版本拒绝。程序占用旧 DLL 时将新 DLL 编译到备用目录。测试结果另记，未执行的验证不声称通过。

## 验证结果

- Release C++ 与 D3D12 RT shader 编译通过。用户进程关闭后，已构建到正式 `build/windows-vs2022/bin/Release/plugins/TraditionalProbeGI.dll`。
- `tests/probe_gi/texel_local_distance.py`：8 Probe、128×128、每 texel 4条独立距离射线。已知墙面距离0.48，靠近+X方向的texel均值0.4800552，落在该texel角范围内的解析距离区间。
- 生产查询读取值与缓存对应texel还原值最大差5.75e-8（浮点乘法）；同texel两个不同方向的读取值完全相同。
- 改变SH样本数2→3、每帧批次2→1，距离矩最大差6.0e-8；烘焙中改变批次的结果与原始基线最大差0。取消不保存半成品；拒绝version 2；version 3独立进程重载的选点均值一致。
- 原 `ray_visibility.py` 回归通过：最近交点、遮挡归零、MISS、端点和世界坐标选点恢复保持正确，结果 `build/probe-ray-validation/0da664cf/`。
- 新测试记录：`build/probe-texel-local-validation/results.json`、`load.json`。未重新烘焙用户Room场景，未声称消除了所有漏光；跨表面边界仍可能落在一个texel内部，那里仍是局部距离分布的均值/方差。
