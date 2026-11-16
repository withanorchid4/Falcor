# Cornell 场景与灯光配置

启动入口选择 `Cornell + DDGI`，现在加载 NVIDIA RTXGI-DDGI 1.3.7 自带的 `cornell.glb`。模型来自构建时取得的 RTXGI 依赖；如果依赖目录不存在，会查找已下载的官方示例目录。原来的 `media/test_scenes/cornell_box.pyscene` 保留。

默认相机与官方相同：位置 `(0.1,1,4)`，朝向 `-Z`，垂直视场 45°。已保存的启动相机仍优先于场景默认相机。

## 调整光源

运行时打开 **Scene Settings → Lights**：

- **Sun**：`Active` 开关、`Color` 颜色、`Intensity` 强度、`Direction` 光线传播方向。
- **Ceiling Point**：`Active` 开关、`Color` 颜色、`Intensity` 强度、`World Position` 世界位置。

默认只有白色 Sun 开启，方向 `(0.6,-0.435,-0.816)`，强度 1。顶部点光源放在 `(0,1.9,0)`，默认关闭；启用后使用白色、强度 1。官方原配置的顶部点光源 power 为 0，这里用独立开关表达关闭状态，便于直接勾选开启。关闭两盏灯后，黑色天空下画面为黑色；DDGI 的历史照明需要少量帧衰减，也可点 Reset history。

运行时调整作用于当前会话。要修改下次启动的默认值，编辑同目录的 **CornellRTXGI.json**：

| 配置字段 | 含义 |
|---|---|
| `directionalLight.enabled` / `ceilingPointLight.enabled` | 是否开启 |
| `color` | 线性 RGB 颜色，三个非负数 |
| `intensity` | 非负标量，实际 RGB 强度为 color × intensity |
| `directionalLight.direction` | 方向光传播方向，非零向量，加载时归一化 |
| `ceilingPointLight.position` | 世界位置 |
| `camera` | 默认相机 |
| `ddgi` | Cornell 启动预设的探针布局、射线数及偏移 |
| `display.exposureStops` | ACES 曲线前的曝光档位，默认 +1，匹配官方 |

例如把方向光的 `enabled` 改为 `false`、点光源的改为 `true`，重启后就是顶部点光源照明。也可通过 `CORNELL_RTXGI_CONFIG` 指定另一份完整配置文件。

Cornell 的 DDGI 预设为 9×9×9、中心 `(0,1,0)`、间距 0.3。Normal/View bias 配置使用世界距离，加载时转换为现有 DDGI 界面使用的间距比例。其余场景仍使用各自原来的启动参数。

## 与官方画面的关系

几何、默认相机、方向光输入及探针网格已对齐。Falcor 仍使用自己的材质、RTXDI/NRD 和显示流程，没有复制官方示例的错误 sRGB 转换，也没有加入其 RTAO。点光源沿用 Falcor 的距离平方反比衰减；官方示例还带半径窗口和近距离钳制，相同数值不保证点光源照度完全相同。DDGI 的最小 relocation 距离和部分阈值也仍沿用当前接入实现。

自动验证脚本：`tests/ddgi/cornell_lighting.py`，检查脚本：`tests/ddgi/check_cornell_lighting.py`。覆盖方向光、点光源、全部关闭、运行时开灯并改变位置与颜色。
