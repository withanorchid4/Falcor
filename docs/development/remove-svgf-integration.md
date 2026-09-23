# 清理本地 SVGF 接入

2026-09-23，实施前记录。用户要求清理不再使用的 SVGF 逻辑。

1. 普通 PathTracer 恢复官方的 VBufferRT → PathTracer → AccumulatePass → ToneMapper 拓扑，只标记 ToneMapper.dst；保留显式 Auto Reset 和无限帧累积设置。移除 SVGF、额外 Raw/SVGF ToneMapper 与辅助 GBuffer 通道。
2. 删除本地新增的 SVGF 启动器、包装/迁移脚本、专用测试和使用/开发文档，移除统一入口及说明中的 SVGF 选项。
3. 将此前为接入新增的六处 SVGFPass 源码改动还原至仓库原始版本 759aad03；保留上游自带的插件、官方示例及官方测试，不扩大为删除第三方算法。构建目录中的旧截图和会话备份属于历史产物，不批量删除。
4. 复用统一图集成检查，验证 D3D12 下 PathTracer、官方 NRD 和 Probe 切换、Probe 烘焙状态保留及换场景。检查清理后的图输出和源码引用；本轮不改变 NRD 或 Probe 算法。

## 验证

统一图检查已通过，退出码 0，记录在 `build/gi-switch-validation/017c1da3/result.json`。普通 PathTracer 在 Cornell/Room 均只捕获 `ToneMapper.dst`，三图切换、探针烘焙暂停/继续、缓存保留及换场景检查通过。启动脚本语法通过，已拒绝移除的 `-Renderer SVGF`，活动脚本/启动说明中无残留 SVGF 引用。六个 SVGFPass 源文件与上游 759aad03 完全一致。

本次图清理无需重编译；已有未使用的插件二进制没有重建，后续构建会使用还原后的官方源码。运行中的旧图不会自动卸载，重新启动统一入口后生效。历史测试产物和备份保留。
