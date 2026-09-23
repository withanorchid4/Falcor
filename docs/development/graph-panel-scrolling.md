# Graphs 面板滚动修复

2026-09-23，实施前记录。

原因：Mogwai 的 Graphs 窗口默认 300×600，经 Gui DPI 缩放后可能超出渲染窗口。ImGui 按整个面板高度计算滚动范围，不会把屏幕外的面板底部当成额外可滚动内容，因此 Probes 展开后，Display 等控件可能始终不可见。GUI 优先接收鼠标事件，此问题不是 Probe 抢占滚轮。

方案：仅在 MogwaiSettings::renderGraphs 内对 Graphs 设置 ImGui 尺寸约束，按当前实际显示尺寸、面板位置计算可用高度；处理窗口缩小或面板拖出边缘后的可见位置。保留手动拖动和缩放、现有滚轮机制，不修改 GI、缓存或其他工具窗口。约束使用 ImGui 的屏幕单位，不重复乘 DPI。

验证：构建 Mogwai；保存当前场景相机配置后重启；展开 Probes，滚动到 Debugging 和 Display；检查面板底边留在可见区域。测试前后保持现有烘焙缓存。

实测：Windows Release Mogwai 构建通过。相同房间、相机及 2048 samples/probe 缓存下，展开 Probes 后滚轮可到达 Debugging / Display；继续展开 Display 可滚到曝光与 Tonemapping 参数。面板底边留有可见间距。`build/probes` 下缓存文件 SHA-256 检查全部不变。
