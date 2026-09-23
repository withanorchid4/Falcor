# Probe normal/view bias（2026-09-24，实施前约定）

## 目的和边界

在现有 normal bias 上增加可调 view bias，用于对比近墙距离矩误判。用户给出的公式为 `(0.2*N + 0.8*V) * minSpacing * 0.3`。它可能让查询点离开误判区域，但会同时改变查询距离、八面体 UV 和网格插值位置，不保证一个 texel 内 d 与 mean 始终保持同一大小关系，也不证明距离矩数据正确。保持每 Probe 一次切比雪夫、现有距离矩过滤和烘焙缓存不变。

## 实施约定

- 共用查询位置函数：`Q = P + minSpacing * (normalBias*N + viewBias*V)`；V 是从原始表面 P 指向当前相机位置的单位向量。相机与 P 重合时 V=0。组合向量不再归一化。normalBias 延续默认 0.05，viewBias 新增默认 0，旧配置视觉行为保持不变。
- UI 两个独立 0..1 系数；公式预设设为 normalBias=0.06、viewBias=0.24；恢复按钮设为 0.05、0。参数即时生效，无需重烘焙。属性序列化、configureDebug、configureVisibility 都接受新参数，并校验有限非负值（运行时范围 0..1）。
- 生产 GI、调试表面视图和选点检查共用 Q。P 保持原始点；SH 法线和朝向权重不变。黄色线段表示完整 normal+view 偏移，调试面板显示 P、Q 和系数。viewBias 非零且相机移动/切换时刷新已选世界点的检查；不因此清除烘焙。
- 保存选点附带 viewBias；旧选点文件缺省为 0。恢复使用当前相机，未保存相机的旧选点不承诺完全还原 view bias 结果。
- 不增加每像素射线，不加入截图中的深度检测/二分回退。较大 bias 仍可能穿过其他几何；view bias 会使查询结果随相机位置变化，需移动相机检查。

## 验证

Release C++ 编译及独立 headless D3D12 着色器运行。加载已有 v3 缓存，检查默认/纯 normal/纯 view/公式预设的 GPU Q 与 CPU 公式一致；相机移动后已选点自动刷新、零距离相机无 NaN；两种可见性模式共用 Q；回到旧 bias 后距离矩与权重恢复；配置序列化和无效输入验证；缓存字节、Ready 和采样计数不变。不操作用户正在运行的 GUI，DLL 占用时保留编译好的备用文件。

## 实测结果

- Release C++ 编译、隔离 headless D3D12 着色器运行通过。构建有共享中间目录警告和既有 shader 警告，无编译错误。
- `tests/probe_gi/normal_view_bias.py` 通过，GPU Q 对照误差最大 `1.82e-8`；相机移动自动刷新、相机与选点重合的零向量保护、两种可见性模式、配置往返和非法参数拒绝均通过。恢复旧参数后八个 Probe 的权重、均值和方差恢复，缓存字节与烘焙状态未变化。
- 结果 `build/probe-bias-validation/results.json`；备用 DLL 在 `build/probe-bias-staging/TraditionalProbeGI.dll`。正式 DLL 被用户正在运行的 Mogwai 占用，复制未成功；关闭程序后运行 `build/Apply-ProbeBias-Update.cmd` 替换并校验哈希。未关闭或操作用户窗口。
- 尚未验证用户截图中的墙面伪影是否改善，也未测量性能；功能验证不等于消除漏光。未提交 git。
