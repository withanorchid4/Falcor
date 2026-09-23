# 基础方差相加实验（2026-09-24，实施前约定）

按用户要求，将运行时切比雪夫使用的方差从 `max(m2-mean*mean, varianceFloor)` 改为 `max(m2-mean*mean, 0) + varianceBase`，默认 varianceBase=1e-6，仍为归一化距离的平方单位。不是去除全部保护，也不是每个 texel 的存储数据增加偏移；先按原方式读取/插值距离矩，再在计算可见性时加一次基础方差。

- 所有生产/选点检查共用 probeChebyshev，保留 visibilityPower 和 d<=mean 的可见性1行为。正的基础方差保证分母非零。
- UI 改名 Base variance (normalized)；新配置键 varianceBase，保留旧 varianceFloor 键作为兼容别名（新键优先），语义为相加，不再序列化旧名。取值范围沿用1e-8..0.01，默认1e-6。
- 调试 variance 继续显示距离矩本身的原始非负方差；面板另行显示基础方差的归一化值和世界单位值，避免把测得方差和计算用方差混淆。
- 不改 bake、缓存格式、normal/view bias、采样次数；不需要重新烘焙。零方差处与原先1e-6下限效果相同，不能预先宣称修复墙面边界。
- 验证：Release编译，隔离D3D12验证零方差、d=mean、d<mean、d>mean、小于/等于/大于基础方差的正方差，Point/Bilinear共用同一公式，旧配置兼容和缓存不变。通过后部署正式DLL；若用户程序占用则保留备用构建，不结束用户进程。

## 实测结果

Release C++ 和 D3D12 shader 编译通过。`tests/probe_gi/base_variance.py` 的128项GPU/CPU对照通过，最大可见性误差2.69e-6；测试中与旧下限公式的最大差异0.1713，确认实际采用相加而非max。零方差及d=mean未产生NaN，旧属性别名、新属性优先级和缓存不变检查通过。结果在 `build/probe-base-variance-validation/results.json`。

已将新DLL部署到正式plugins目录，源文件与目标SHA-256一致。包括先前normal/view bias修改，无需再运行旧bias更新脚本。没有更改或重新烘焙用户缓存，尚未确认用户墙面伪影是否改善。未提交git。
