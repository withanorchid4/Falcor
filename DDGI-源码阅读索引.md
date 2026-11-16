# DDGI 关键环节与源码阅读索引

基于本地源码核对，日期：2026-11-15。范围是 `RTXGIDDGI` 通道的普通 DDGI 路径（`useWRC=false`），最后附 WRC 扩展入口。

路径均相对项目根目录：`C:/Users/Admin/Desktop/实时GI/Falcor`。行号对应当前工作区，后续改动后可按函数名搜索。

## 1. 先看一帧的总流程

- **入口：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp:694`，`RTXGIDDGI::execute()`。
- 创建或重建程序、分配资源、清理历史，随后上传 volume 参数。
- 开启探针更新时，先执行探针射线，再对 ray data 加 UAV barrier，最后调用 `updateProbes()`。
- 探针更新结束后执行 `mRender`，读取相机可见表面并查询 DDGI。冻结探针时仍然执行这一步。
- **阅读重点：** 找到 `mOptions.update`、`mOptions.useWRC`、`OriginalTrace`、`SDKUpdate`，理解哪些工作每帧执行、哪些可以冻结。

```text
上次完成的 irradiance / distance / probe data
                  ↓ 在命中点查询，提供多次反弹反馈
traceProbes → ray data（每条射线的 radiance 和距离）
                  ↓ UAV barrier
updateProbes → irradiance 混合 → distance 混合 → relocation → classification
                  ↓
render → 从 VBuffer 读取表面 → 查询 8 个邻近探针 → 合成间接光
```

## 2. 探针网格与 GPU 数据如何组织

- **位置：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp:275`，`allocateResources()`。
- 自动体积以场景包围盒中心为中心，半尺寸为场景 extent 的 `0.55`，即总体积各轴长度扩到原来的 110%。
- 探针间距为 `(gridMax - gridMin) / (counts - 1)`。探针数量和覆盖范围共同决定空间采样密度。
- 当前布局是右手系、Y 向上；Texture2DArray 的每个 layer 对应一个 XZ 平面。

| 资源 | 存储内容 | 当前分配方式 |
| --- | --- | --- |
| `mpRayData` | 本轮每条探针射线的 radiance 与距离 | 每层宽为 rays/probe，高为 X×Z |
| `mpIrradiance` | 按方向存储的探针 irradiance | 每探针 8×8 tile，内部有效区 6×6 |
| `mpDistance` | 按方向过滤的距离一阶、二阶矩 | 每探针 16×16 tile，内部有效区 14×14 |
| `mpProbeData` | 探针重定位偏移和活动状态 | 每探针一个 texel |
| `mpVolume` | 网格、偏置、混合等参数 | 一个 128 字节 packed volume 描述 |

- **参数上传：** 同文件 `:576`，`uploadConstants()`；资源绑定看 `:613`，`bindRayProgram()`。
- **阅读重点：** irradiance 是方向分布，不是每个 probe 只存一个 RGB；distance 存统计矩，用于之后的可见性估计。

## 3. 如何绑定光追 shader

- **位置：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp:238`，`buildRayProgram()`；`:264`，`createPrograms()`。
- 这里构建 ray tracing program 和 shader binding table，绑定 raygen、miss、hit group。
- **阅读重点：** 把 raygen entry 与 `RTXGIDDGI.rt.slang` 中的 `traceProbes()`、`render()` 对应起来；跟踪 probe ray 和 shadow ray 使用的 miss / hit group。

## 4. 探针如何生成射线并处理命中

- **位置：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang:302`，`traceProbes()`。
- dispatch 三个维度分别是每探针射线数、每 XZ 平面探针数、Y 平面数。
- 计算逻辑探针索引、滚动索引，读取分类状态；inactive probe 跳过非固定射线。
- `DDGIGetProbeWorldPosition()` 取得包含 relocation 偏移的位置；`DDGIGetProbeRayDirection()` 生成射线方向。
- 调用 DXR `TraceRay()`，保留背面命中，用于重定位和分类。
- **closest-hit：** 同文件 `:466`，`probeTriangleClosestHit()`，只保存 instance、primitive、重心坐标、命中距离和背面标志。着色在 `TraceRay()` 返回后继续执行。
- miss 写入零 radiance：本实现让环境光在表面直接光估计中采样，探针场存储几何散射后的光。
- 背面射线写入背面命中；启用 relocation / classification 时，前面的固定射线仅提供几何信息，不参与该处光照估计。
- **SDK 射线工具：** `build/windows-vs2022/_deps/rtxgi_ddgi-src/rtxgi-sdk/shaders/ddgi/include/ProbeRayCommon.hlsl:113`，`DDGIGetProbeRayDirection()`；同文件的 `DDGIStoreProbeRay*()` 定义 ray data 的写入编码。

## 5. 命中点光照与多次反弹反馈

- **位置：** `RTXGIDDGI.rt.slang` 的 `traceProbes()` 后半段。
- 加载命中表面和材质，调用 `evaluateDirect(..., true, ...)` 计算漫反射直接光。
- **直接光入口：** 同文件 `:281`，`evaluateDirect()`；内部合计解析灯、发光网格、环境光三个类别。
- **阴影入口：** 同文件 `:172`，`traceShadow()`；普通路径和 inline 路径由 `DDGI_INLINE_SHADOW` 控制，可在此对照。
- 有有效历史时，查询上一轮探针 irradiance，再增加反馈项：`min(diffuseAlbedo, 0.9) × irradiance / π`。
- **因果关系：** 上一轮的间接光在命中表面再次反射，形成跨更新迭代的多次反弹；albedo 上限用于限制反馈能量。
- 最后把本条射线的 radiance 与命中距离写入 ray data。全部射线追踪完成后才开始修改探针 atlas。

## 6. 射线数据如何积分到探针贴图

- **CPU 调度：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp:658`，`updateProbes()`。
- **本地包装：** `Source/RenderPasses/RTXGIDDGI/ProbeBlending.cs.slang`。
- **真正算法：** `build/windows-vs2022/_deps/rtxgi_ddgi-src/rtxgi-sdk/shaders/ddgi/ProbeBlendingCS.hlsl`，搜索 `DDGIProbeBlendingCS`。
- 同一套 kernel 通过 `RTXGI_DDGI_BLEND_RADIANCE` 编译成 irradiance 与 distance 两个版本。CPU 依次 dispatch 它们。
- irradiance 分支将射线 radiance 按方向权重积分；distance 分支生成方向相关的距离统计矩。
- **重点搜索：** `RTXGI_DDGI_BLEND_RADIANCE`、`hysteresis`、`probeIrradianceEncodingGamma`。同时查看八面体方向映射和 tile 边界处理。
- 历史混合平衡稳定性和响应速度；hysteresis 越高，越依赖历史。该文件约 `:525` 开始可看到大光照变化时降低 hysteresis 的逻辑。

## 7. 重定位与分类怎样改善探针有效性

- **调度顺序：** `updateProbes()` 中先完成两种 blending，再 relocation，最后 classification；阶段之间设置 UAV barrier。
- **重定位：** `Source/RenderPasses/RTXGIDDGI/ProbeRelocation.cs.slang` include SDK 的 `build/windows-vs2022/_deps/rtxgi_ddgi-src/rtxgi-sdk/shaders/ddgi/ProbeRelocationCS.hlsl:93`，入口 `DDGIProbeRelocationCS()`。
- 读取射线的前后表面距离，尝试把陷入几何体或靠表面过近的 probe 移到更合适的位置，偏移写回 probe data。
- **分类：** `Source/RenderPasses/RTXGIDDGI/ProbeClassification.cs.slang` include SDK 的 `build/windows-vs2022/_deps/rtxgi_ddgi-src/rtxgi-sdk/shaders/ddgi/ProbeClassificationCS.hlsl:93`，入口 `DDGIProbeClassificationCS()`。
- 根据几何命中信息标记 active / inactive。该状态同时影响后续射线更新和屏幕插值；inactive probe 不贡献 irradiance。

## 8. 表面点如何查询 8 个 probe：最值得细读的一段

- **项目封装：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang:290`，`queryIrradiance()`。
- 先计算 volume 边界渐隐权重，再计算法线/视线偏置，调用 SDK 查询函数。
- **核心实现：** `build/windows-vs2022/_deps/rtxgi_ddgi-src/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl:65`，`DDGIGetVolumeIrradiance()`。
- 按以下顺序阅读函数：
  1. 用偏置后的世界位置定位网格单元，确定 8 个相邻 probe。
  2. 跳过 inactive probe，获取重定位后的 probe 位置。
  3. 计算三线性权重，以及表面朝向的 wrap shading 权重。
  4. 沿 probe 到表面点的方向读取 distance atlas，得到距离均值与二阶矩。
  5. 用距离方差和表面点距离计算 Chebyshev 可见性权重；超过平均距离时衰减，并用三次方加强对比。
  6. 可见性权重保留 `0.05` 下限，再压低很小的组合权重，最后乘三线性权重。
  7. 沿查询法线方向采样 irradiance atlas，解码后加权累积。
  8. 除以累计权重，恢复线性 irradiance，并乘 `2π` 完成该存储约定下的积分尺度恢复。
- **阅读重点：** 此处遮挡估计是连续权重；inactive 是明确跳过。判断漏光或明暗分界时，要同时检查 bias、距离矩、方向权重、网格单元切换、分类和 volume 边缘渐隐。

## 9. 最终像素如何得到间接光

- **位置：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang:402`，`render()`。
- 通过 `gVBuffer[pixel]` 获得已经可见的表面，恢复位置、法线和材质。
- 间接光为 `diffuseAlbedo × queryIrradiance(...) × intensity / π`，再与直接光、发光项合成。
- `gIndirectOnly` 控制仅显示间接光；`gUseRTXDI` 可使用外部直接光结果。探针射线仍保留自身的直接光估计。
- **阅读重点：** `render()` 虽然声明为 raygen，但这里的可见表面来源是 VBuffer。

## 10. WRC 扩展在哪里接入

- **CPU：** `Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp:457`，`traceWithWrc()`；由 `execute()` 的 `useWRC` 分支选择。
- **记录命中：** `Source/RenderPasses/RTXGIDDGI/WorldRadianceCache.rt.slang`，`traceWRC()`。
- **共享键与代表点着色：** `Source/RenderPasses/RTXGIDDGI/WorldRadianceCache.slang`，`wrcKey()`、`wrcShadeHit()`。
- **去重、活动列表、着色和 gather：** `Source/RenderPasses/RTXGIDDGI/WorldRadianceCache.cs.slang`。
- WRC 最终同样写回 DDGI ray data，随后复用第 6～9 点的探针更新与查询链路。

## 建议阅读顺序

1. `execute()`：建立一帧的数据流。
2. `traceProbes()`：看一条射线如何产生 radiance 和距离。
3. `updateProbes()` → SDK `ProbeBlendingCS.hlsl`：看射线如何变成探针方向贴图。
4. `queryIrradiance()` → SDK `Irradiance.hlsl`：看 8 个候选 probe 如何筛选、加权和归一化。
5. `render()`：看 irradiance 如何转成最终像素的漫反射间接光。
6. 最后读 relocation、classification 和 WRC。

SDK 版本来源见 `cmake/rtxgi-ddgi.cmake`：RTXGI-DDGI v1.3.7，固定 commit `c233266e95931231961f35c842c78e7c4bdc50cf`。上述 SDK 路径是本机已存在的源码缓存；Release 目录中的 `shaders/RTXGI/` 是运行时 shader 副本，阅读优先使用 `_deps/rtxgi_ddgi-src`。
