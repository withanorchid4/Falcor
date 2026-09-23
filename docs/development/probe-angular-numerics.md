# 角度距离矩保存失败排查（2026-09-24，实施前约定）

用户Room烘焙两次在atlas texel 324保存失败。当前校验严格要求归一化均值<=1，角度混合在每批将均值乘回累计权重再求平均。先补全失败时mean/secondMoment/weight/rawVariance日志，在独立缓存复现；未确认之前不放宽校验或把NaN替换为有效数据。

如果确认是有限浮点舍入使理论[0,1]的距离矩轻微越界，则在烘焙输出端仅修复浮点量级误差，不改变合法矩及烘焙分布。超出舍入容差、非有限数据仍拒绝保存。保留版本/缓存、运行时基础方差和bias；增加空方向/MISS与Room复现、重启加载及原角度公式回归验证。用户运行程序不停止；DLL被占用时输出备用构建与关闭后更新脚本。

## 复现与修复

隔离进程使用同一Room、384 Probe、SH2048、距离2048、分辨率14、指数50，复现相同texel324失败：mean=1.00000036，second=1.00000036，weight=30.7094421，rawVariance=-3.57627869e-7。严格mean<=1校验拒绝了多批加权累计造成的约3 ulp越界。

Compute输出端仅当两项都有限且位于[-2e-5,1+2e-5]才将两项限制到[0,1]。区间内原本合法的数据不变；非有限或大幅越界不修补，仍由原校验拒绝。未改切比雪夫基础方差，也未放宽缓存加载/保存校验。改动不改变缓存格式。

## 验证与交付

- 同款Room完整384 Probe、2048 SH / 2048距离样本重新烘焙通过，2560帧，缓存保存成功；texel324为(0.999999523,0.999999523)，全缓存通过原严格校验。SH中原有一次非有限路径尝试由既有重试机制恢复，与本次距离矩问题无关。
- 新进程Load成功，无烘焙；160×120 EXR全部RGB有限，最大6.22925。角度CPU/GPU数值与批次一致性等回归通过。
- 证据 `build/probe-angular-room-validation/reproduced-error.json`、`result.json`、`load.json`、`cache-render-check.json`。
- 修复Compute shader已复制正式运行目录且hash一致。诊断日志DLL/PDB编译到 `build/probe-angular-fix-staging`（用户进程占用原DLL/PDB）。关闭Mogwai后可运行 `build/Apply-ProbeAngular-Fix.cmd` 部署日志增强DLL。
- 默认angular缓存此前不存在，已复制验证过的Room缓存到 `build/probes/grey_and_white_room-9e2df5c8ed1ac29-angular.shprobe`，可用相同参数Load matching cache。未覆盖用户已有缓存或停止用户进程；未提交git。
