# 恢复方向加权距离矩（2026-09-24，实施前约定）

## 依据与范围

核对 NVIDIA RTXGI-DDGI `ProbeBlendingCS.hlsl`：距离矩更新用 `max(dot(texelDirection, rayDirection),0)^probeDistanceExponent` 汇总同一 Probe 的多条射线距离与距离平方，再归一化。一个射线样本可影响多个方向 texel。官方还含动态历史混合、边界更新等逻辑；本次只恢复静态烘焙的角度加权滤波，不引入动态 hysteresis、relocation/classification 或额外高斯模糊。

来源：https://github.com/NVIDIAGameWorks/RTXGI-DDGI/blob/main/rtxgi-sdk/shaders/ddgi/ProbeBlendingCS.hlsl

## 实施约定

- 新增烘焙模式 `distanceBakeMode`: `texelLocal` / `angular`。插件缺省仍 texelLocal 以兼容旧配置；预览脚本显式使用 angular，便于本次实验。UI 可切回旧模式，修改需 Bake/Load 对应缓存。
- angular 恢复 Angular sharpness，默认50，范围1..256。独立距离射线预算 `distanceRaysPerProbe` 默认2048，范围1..65536；不复用/改动 SH 样本，避免两种烘焙设置相互干扰。每 Probe 均匀球面方向样本由 Probe ID、绝对样本序号确定，每批最多16条，最近交点/MISS/距离范围沿用现有规则。
- RT 阶段每条射线只追踪一次，写入 Probe×16 的临时 direction/distance 缓冲；ComputePass 把这些射线汇入同 Probe 的所有内部 texel，以 texel 中心方向计算角权重，累积一阶/二阶加权平均与总权重。权重和不超过1e-20时沿用(1,1)空数据并清零累计权重，避免极小权重归一化不稳定。分块每次最多8192 texel，整轮完成后才开始下一批射线；运行中改分帧参数不改变该轮样本集合。
- 保留独立 texel 原路径和 version3缓存；angular 缓存用 version4、方法 angular_cosine，并记录 ray预算/指数；自动文件后缀-angular，保留-texel-local文件。错模式/指数拒绝加载，禁止把两种不同统计数据默认为同一种。
- runtime 点/双线性读取、八面体边界折叠、SH、normal/view bias、基础方差1e-6均保持。角混合只在Bake阶段增加工作，Ready之后无新增运行时纹理采样或切比雪夫次数。
- 更新使用文档/状态显示，明确每Probe射线与每texel射线的区别。先写开发文档，再实现，最后编译/测试，未请求不commit。

## 验证

Release及headless D3D12：小场景真正烘焙角模式，CPU重建均匀球面样本和解析墙面交点，对比多个texel的加权一二阶矩；跨texel贡献证据、批次一致性（包含半轮改批次）、新缓存fresh-process加载/参数拒绝、旧version3模式可加载、取消不覆盖；验证正常GI渲染数值有限。无UI自动化，不覆盖用户缓存。

## 实测结果

- Release C++ / D3D12 RT及Compute shader通过。`tests/probe_gi/angular_distance.py` 实际完成8 Probe、32²距离图、64条距离射线/Probe的小场景烘焙；48个texel的一二阶矩对照CPU角权重和解析墙面距离，最大误差1.75e-7；全部被检texel都受到多条射线影响。
- 半轮处理中将每帧样本16改为3，最终全部距离矩与基线最大差3.88e-7。错指数/错模式拒绝加载，取消不覆盖完整缓存，旧version3 texelLocal缓存加载通过。
- 独立新进程直接加载version4成功。EXR完整RGB有限，160×120图像最大值7.783。记录位于 `build/probe-angular-validation/results.json`、`load.json`、`render-check.json`。
- 已部署正式 `plugins/TraditionalProbeGI.dll`，与备用构建SHA-256一致；预览脚本默认angular。没有重新烘焙用户Room缓存，没有操作用户窗口，尚未确认该墙面突变是否改善。未提交git。
