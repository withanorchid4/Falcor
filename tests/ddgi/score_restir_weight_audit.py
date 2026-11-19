from pathlib import Path
import sys,json
import numpy as np
R=Path(__file__).resolve().parents[2];D=R/'build/restir-weight-audit';O=R/'docs/2026-11-18_DDGI-ReSTIR-weight-audit';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR
from PIL import Image,ImageDraw,ImageFont

def read(name,n):return OpenEXR.File(str(D/(name+'-'+str(n)+'.Accumulate.output.0.exr'))).channels()['RGB'].pixels
ref=read('fg',131072);mask=np.any(ref>1e-8,axis=2)
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
metrics={}
for name in ['fg','uniform','legacy-temporal','legacy-spatial','legacy-both','fixed-temporal','fixed-spatial','fixed-both']:
 metrics[name]={}
 for n in [16,64,256,1024,4096,16384,32768]:
  if not (D/(name+'-'+str(n)+'.Accumulate.output.0.exr')).exists():continue
  a=read(name,n);assert np.isfinite(a).all()
  metrics[name][str(n)]={'mse':mse(a,ref),'mean_ratio':float(a[mask].mean()/ref[mask].mean())}
result={'reference':'same cosine FG 131072 frames, frozen identical probes, no NRD','resolution':[640,360],'reference_65536_vs_131072_mse':mse(read('fg',65536),ref),'metrics':metrics}
(O/'summary.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v.get('32768') for k,v in metrics.items()},indent=2))
sys.path.insert(0,str(R/'build/convergence-python'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
for ax,keys,title in zip(axes,[['uniform','legacy-temporal','fixed-temporal','legacy-spatial','fixed-spatial'],['fg','uniform','legacy-both','fixed-both']],['Separate temporal / spatial reuse','Combined reuse']):
 for name in keys:
  d=metrics[name];ax.loglog([int(n) for n in d],[d[n]['mse'] for n in d],'.-',label=name)
 ax.set_title(title);ax.set_xlabel('Frames / new candidates per coarse pixel');ax.set_ylabel('Linear HDR MSE vs long-run original FG');ax.grid(True,which='both',alpha=.2);ax.legend()
fig.suptitle('Frozen probes | half resolution | jitter ON | full-resolution integration OFF')
fig.savefig(O/'convergence.png',dpi=180);plt.close(fig)
def display(a):
 x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return Image.fromarray(np.uint8(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255+.5))
panel=Image.new('RGB',(1920,400),(24,26,31));draw=ImageDraw.Draw(panel)
for i,(name,a) in enumerate([('Original FG reference',ref),('Legacy ReSTIR',read('legacy-both',32768)),('Corrected ReSTIR',read('fixed-both',32768))]):
 panel.paste(display(a),(i*640,40));draw.text((i*640+10,8),name,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24),fill='white')
panel.save(O/'comparison.png')

static={}
S=R/'build/restir-weight-audit-static-origin'
if (S/'complete.json').exists():
 sr=OpenEXR.File(str(S/'fg-131072.Accumulate.output.0.exr')).channels()['RGB'].pixels
 sm=np.any(sr>1e-8,axis=2)
 for name in ['uniform','legacy-temporal','fixed-temporal']:
  static[name]={}
  for n in [4096,16384,32768]:
   a=OpenEXR.File(str(S/(name+'-'+str(n)+'.Accumulate.output.0.exr'))).channels()['RGB'].pixels
   static[name][str(n)]=float(np.mean((a[sm].astype(float)-sr[sm])**2))
 result['static_origin_control']=static
 (O/'summary.json').write_text(json.dumps(result,indent=2))
rows=''
for name in metrics:
 v=metrics[name]['32768'];rows+=f"<tr><td>{name}</td><td>{v['mse']:.6g}</td><td>{v['mean_ratio']:.6f}</td></tr>"
srows=''
for name,v in static.items():srows+=f"<tr><td>{name}</td><td>{v['4096']:.6g}</td><td>{v['16384']:.6g}</td><td>{v['32768']:.6g}</td></tr>"
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>ReSTIR 复用权重审计</title>
<style>body{{background:#181b20;color:#ddd;font:17px/1.7 system-ui;max-width:1500px;margin:30px auto;padding:0 24px}}img{{width:100%}}a{{color:#9cf}}table{{border-collapse:collapse}}td,th{{padding:7px 14px;border:1px solid #555}}code{{color:#abd}}</style>
<h1>ReSTIR 复用权重审计</h1>
<p>旧实现确实有复用归一化问题。单纯延长累积不能消除它。修正后空间复用的长时间误差显著降低；时间复用仍存在强相关与较大残差，不能据此宣称整个实现严格无偏。</p>
<h2>实验条件与参考</h2><p>640×360 Lambert Cornell，半分辨率追踪、jitter 开启、全分辨率积分关闭、原 16 tap 重建、Accumulate 开启、无 NRD。各组先运行 8192 帧 probe 更新，再冻结；reservoir 与累积从空历史开始。每个有效粗像素每帧一个新候选。空间 2 pass × 4 邻居，半径 8，时间 M 上限 20。旧、新路径使用相同起始随机序列。</p>
<p>这里用同一冻结 probe 下的原始 cosine FG 131072 帧作为参考，专门隔离复用误差；不是 PT，也不是上一份 1080p 实验。参考 65536→131072 帧的 MSE 为 {result['reference_65536_vs_131072_mse']:.3g}。指标在非黑色场景像素上以线性 HDR RGB 计算。本次为单随机序列诊断，没有置信区间；原 FG 与自身长序列参考共享前缀，因此其误差稍有乐观。</p>
<h2>32768 帧结果</h2><table><tr><th>路径</th><th>MSE vs 原 FG 参考</th><th>平均 RGB / 参考</th></tr>{rows}</table>
<p>uniform 为与 ReSTIR 相同的 uniform hemisphere 候选，但不做时空复用。它收敛到原 FG，说明初始采样与积分没有整体 π 因子错误。legacy/fixed 分别是旧实现与本次修正；包含归一化和单侧 Jacobian 两项修改，未单独量化两者贡献。</p>
<img src="convergence.png"><p>曲线横轴是空历史开始后的帧数，纵轴是误差，均为对数坐标。fixed-both 的尾部仍有波动；一条曲线不足以把剩余误差全部判断为偏差或全部判断为方差。</p><img src="comparison.png">
<h2>发现与修改</h2><ol>
<li>旧路径先根据邻居当前选中的样本是否可见决定是否加入，并从 M 中剔除被拒绝者。这让参与归一化的来源集合依赖随机样本。即使保留所有 M，直接除以 ΣM 也不能处理来源支持域不同的问题。</li>
<li>修正路径按几何兼容性确定来源；不可见候选权重置零。选出最终样本后，再检查它从每个来源是否在半球内、能通过重连 Jacobian 检查且可见，据此计算归一化分母。存储的 M 仍是全部参与来源的候选数，不是最终样本可达来源的数量。</li>
<li>当前 target 是缓存 Li 的亮度，跨来源使用同一数值，因此支持域修正可写成 W = Σw / (target × Σ M_i I_i)。I_i 表示最终样本能否被来源 i 采到。若以后将 BRDF 加入 target，必须改为逐来源重新计算 target，不能继续照用这个简式。</li>
<li>命中面余弦由 abs(dot) 改为 max(dot,0)，避免允许从同一命中面的背面重连。</li></ol>
<p>精确枚举测试：当前来源支持 {{a,b}}，邻居支持 {{b,c}}，积分值 4；旧的按样本拒绝方式期望为 4.5，支持域修正为 4。测试脚本为 tests/ddgi/test_restir_support_weights.py。</p>
<h2>与本地 Lumen 对照</h2><p>检查 D:/Unreal/UnrealEngine/Engine/Shaders/Private/Lumen/LumenReSTIRGather.usf：初始 uniform 采样与 Li 亮度 target 相似；时间复用处 Jacobian 固定为 1（约第 720 行），空间才计算几何 Jacobian（约第 566 行）；空间使用短距离屏幕可见性检查（约第 907 行），归一化为简单 M 分母（约第 926 行）。我们的世界命中点重连、硬件可见性与它并非同一个估计器。不能用“与 Lumen 结构相似”证明无偏。</p>
<p>来源支持域/可见性校正也可参照 <a href="https://raw.githubusercontent.com/NVIDIA-RTX/RTXDI-Library/main/Include/Rtxdi/GI/SpatialResampling.hlsli">NVIDIA RTXDI 的 GI 空间复用实现</a>，其中会再次遍历来源，对最终选中样本计算来源 target 与可见性。此处按当前 Li target 独立实现了简化校正，并未移植其 shader。</p>
<h2>固定出发位置的时间复用对照</h2><p>关闭 jitter，其余流程相同；使用这组自己的原 FG 131072 帧参考，避免重建采样位置变化污染比较。</p><table><tr><th>路径</th><th>4096 帧 MSE</th><th>16384 帧 MSE</th><th>32768 帧 MSE</th></tr>{srows}</table>
<p>固定出发位置时，旧、新时间复用几乎一致；MSE 从 4096 帧的 1.50e-6 降到 32768 帧的 1.96e-7，接近 1/N，但仍约为 uniform 的 12.5 倍。这支持“时间样本相关会降低有效采样量”的解释。开启 jitter 后误差更高，说明跨位置重连还会放大问题；本次单序列不能完全分离其剩余偏差和相关方差。</p><h2>适用范围</h2><p>新选项 restirBiasCorrection 默认开启，UI 名称 Source visibility correction；关闭可复现旧权重。ReSTIR 总开关仍默认关闭，全分辨率积分仍关闭。本次未测新增反向可见性射线的 GPU 开销。空间校正使用来源存储的主表面法线，Lambert 平面场景成立；一般法线贴图材质还需区分几何/着色法线。命中点缓存光照的方向相关性、DDGI view bias、极端 Jacobian 限制和长寿命历史样本仍需考虑，不能声称普适无偏。</p>
<p>复现：tests/ddgi/restir_weight_audit.py、restir_weight_audit_static_origin.py、score_restir_weight_audit.py；原始 EXR 和运行记录位于 build/restir-weight-audit*。旧报告保留，不覆盖历史数据。</p></html>'''
(O/'report.html').write_text(html,encoding='utf-8')
