# 距离矩双线性读取（2026-09-23，实施前约定）

按用户要求只改变运行时读取方式，保留每 texel 独立 UV 范围射线烘焙。增加 distanceBilinear 布尔属性，默认 true；Distance visibility 面板提供 Point/Bilinear 即时切换，不使缓存失效、不重新 Bake。生产可见性、P/Q 调试、距离图预览共用读取函数。

现有 atlas 边界为未使用的 (1,1)，因此不能直接用硬件线性采样器读取旧缓存。采用四次整数读取与 lerp：p=uv*resolution-0.5，取四个邻近texel的一阶和二阶矩，分别双线性插值；越过八面体边界的坐标通过 probeOctWrap 折叠回同一 Probe 的内部 texel。不访问 atlas 空边界或其他 Probe；插值矩后再求方差，不能插值最终可见性。

缓存 version 3、文件名和历史方法标识 texel_local_uv_point 保留兼容；标识只作为现有烘焙数据版本，不限制当前的运行时过滤方式。UI 清楚显示采样模式；Q texel 表示包含方向的 texel，不意味着 Bilinear 只读取该 texel。

验证：Release 编译、D3D12 shader；已有version 3缓存不重烘焙直接加载；GPU P/Q均值/方差与CPU四点插值对照，覆盖内部和八面体边缘/四角；Point/Bilinear往返不改缓存和烘焙状态。当前程序占用DLL则编译到备用目录，不操作用户窗口。

## 实测结果

- Release C++ / D3D12 shader通过；`tests/probe_gi/distance_bilinear.py` 240项查询对照通过，覆盖内部、四条边和四角。一阶矩还原的距离最大误差3.15e-6，方差最大误差1.79e-6（CPU/GPU浮点差异）。使用具有已知空间变化的独立测试矩，能检测误读padding或其他Probe。
- 已有version 3缓存直接加载，无烘焙。Point→Bilinear→Point恢复相同值；切换后Ready、SH/距离样本计数、缓存文件字节均未改变。
- 结果在 `build/probe-bilinear-validation/results.json`。用户程序关闭后已将验证过的DLL复制到正式运行目录，SHA-256一致。未操作用户界面或重新烘焙用户场景。
