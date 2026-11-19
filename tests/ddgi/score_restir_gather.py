"""Validate and visualize the optional spatiotemporal reservoir gather."""
from pathlib import Path
import sys,json,hashlib,re
import numpy as np
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'build/final-gather-python'))
import OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
D=R/'build/restir-gather-comparison';S=R/'build/restir-gather-smoke';B=R/'build/highres-1080p-split-rerun'
O=R/'docs/2026-11-18_DDGI-ReSTIR-gather';O.mkdir(exist_ok=True)
assert not (D/'failure.txt').exists() and not (S/'failure.txt').exists()
info=json.loads((D/'complete.json').read_text());assert info['stage']=='complete' and 'integrated_stats' in info
def load(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels;assert np.isfinite(a).all(),p;return np.ascontiguousarray(a)
def read(tag):
 p=D/(tag+'.Accumulate.output.0.exr');assert p.stat().st_mtime>=info['started'];return load(p)
def smoke(tag,ch):return load(S/(tag+'.'+ch+'.0.exr'))
validation={}
for tag in ['static','moving-0','moving-7','final']:
 a=smoke(tag,'DDGI.restirDebug');m=a[:,:,0]>0;assert m.any()
 validation[tag]={'temporal_M':float(a[:,:,0][m].mean()),'spatial_M':float(a[:,:,1][m].mean())}
 assert validation[tag]['temporal_M']>2
 if tag!='final':assert np.max(abs(smoke(tag,'DDGI.color')-smoke(tag,'Reconstruct.color')))<1e-6
for tag in ['integration-on','integration-off','spatial-off','temporal-off','restir-off','restir-on','full','half','fg-off','fg-on','all-on']:
 assert np.max(abs(smoke(tag+'-reset','Accumulate.output')-smoke(tag+'-reset','Reconstruct.color')))<1e-6
ref=load(B/'reference-65536spp.exr');mask=np.load(B/'surface-mask.npy')
params=json.loads((R/'docs/2026-11-18_DDGI-1080p/summary.json').read_text())['flip_parameters']
body=(R/'Source/RenderPasses/FLIPPass/flip.hlsli').read_text().split('static const float3 MagmaMap[] = {',1)[1].split('};',1)[0]
magma=np.array([[float(c) for c in v.split(',')] for v in re.findall(r'float3\(([^)]+)\)',body)],np.float32)
assert magma.shape==(256,3)
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
def display(a):
 x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 return Image.fromarray(np.uint8(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255+.5))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',28)
def panel(items,file):
 w,h=items[0][1].size;out=Image.new('RGB',(w*len(items),h+50),(23,26,31));draw=ImageDraw.Draw(out)
 for i,(label,img) in enumerate(items):draw.text((i*w+12,9),label,font=font,fill='white');out.paste(img,(i*w,50))
 out.save(O/file)
labels={'off':'Original half FG','restir':'ReSTIR + original reconstruction','integrated':'ReSTIR + full-resolution integration'}
material=R/'build/restir-gather-material-smoke'
assert (material/'result.json').exists() and not (material/'failure.txt').exists()
for tag in ['half','full']: load(material/(tag+'.Reconstruct.color.0.exr'))
validation['standard_material_smoke_and_light_reset']=True
result={'capture':info,'validation':validation,'flip_parameters':params,'metrics':{}}
images={};errors={}
for name in labels:
 a=read(name+'-16384');prev=read(name+'-8192');err=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 mean=None;m2=None;raw=[]
 for i in range(16):
  v=read(name+'-raw-'+str(i));raw.append(mse(v,ref));v=v[mask].astype(np.float64)
  if mean is None:mean=v.copy();m2=np.zeros_like(mean)
  else:delta=v-mean;mean+=delta/(i+1);m2+=delta*(v-mean)
 events=json.loads((D/(name+'-timing.json')).read_text())['events'];prefix='/onFrameRender/RenderGraphExe::execute()'
 metric={'mse':mse(a,ref),'hdr_flip':float(err[mask].mean()),'mse_8192':mse(prev,ref),'tail_difference_mse':mse(a,prev),
 'mean_luminance':float(np.mean(a[mask]@np.array([.2126,.7152,.0722]))),'raw_mse_16_mean':float(np.mean(raw)),
 'raw_temporal_variance_16':float(np.mean(m2/16)),'gpu_frame_ms':events[prefix+'/gpu_time']['stats']['mean'],
 'passes':{k:events[prefix+'/'+k+'/gpu_time']['stats']['mean'] for k in ['Visibility','DDGI','Reconstruct','Accumulate','Display','DDGI/ProbeUpdate','DDGI/PrimaryShading','DDGI/HalfGather','DDGI/ReSTIRInitial','DDGI/ReSTIRTemporal','DDGI/ReSTIRSpatial','DDGI/ReSTIRIntegrate'] if prefix+'/'+k+'/gpu_time' in events},
 'checkpoint_mse':{str(n):mse(read(name+'-'+str(n)),ref) for n in [1,8,32,128,1024,8192,16384]}}
 result['metrics'][name]=metric;print(name,json.dumps(metric),flush=True)
 images[name]=display(a);images[name].save(O/(name+'.png'))
 rgb=np.uint8(np.clip(magma[np.uint8(np.clip(err,0,1)*255+.5)],0,1)*255+.5);rgb[~mask]=(23,26,31)
 errors[name]=Image.fromarray(rgb);errors[name].save(O/(name+'-hdr-flip.png'))
panel([(labels[n],images[n]) for n in labels],'comparison.png')
panel([(labels[n]+' / HDR-FLIP 0-1',errors[n]) for n in labels],'errors.png')
panel([(labels[n]+' / Accumulate OFF',display(read(n+'-raw-0'))) for n in labels],'raw-comparison.png')
panel([(labels[n]+' / 32 accumulated frames',display(read(n+'-32'))) for n in labels],'32-comparison.png')
display(ref).save(O/'pt-reference.png')
rows=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.6f}</td><td>{v['raw_mse_16_mean']:.7g}</td><td>{v['gpu_frame_ms']:.3f}</td></tr>" for k,v in result['metrics'].items())
passrows=''.join('<tr><td>'+k+'</td>'+''.join(f"<td>{result['metrics'][n]['passes'].get(k,0):.3f}</td>" for n in labels)+'</tr>' for k in ['Visibility','DDGI/ProbeUpdate','DDGI/PrimaryShading','DDGI/HalfGather','DDGI/ReSTIRInitial','DDGI/ReSTIRTemporal','DDGI/ReSTIRSpatial','DDGI/ReSTIRIntegrate','Reconstruct','Accumulate','Display'])
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>DDGI ReSTIR Gather 对比</title>
<style>body{{background:#171a1f;color:#ddd;font:17px/1.7 system-ui;max-width:1700px;margin:32px auto;padding:0 20px}}img{{width:100%}}a{{color:#8bd}}table{{border-collapse:collapse}}td,th{{border:1px solid #555;padding:8px}}code{{color:#bdf}}</style>
<h1>DDGI Final Gather：时间／空间 reservoir 复用</h1>
<p>入口：DDGI → Final gather → ReSTIR gather (experimental)，默认关闭。开启后 Temporal reuse、Spatial reuse 默认开启；Full-resolution integration 默认关闭。Accumulate 仍默认开启，可独立关闭；NRD 未启用。</p>
<p><strong>重建是独立选项：</strong>默认在半分辨率位置对选中的 reservoir 样本着色，再沿用 4×4 深度／法线引导重建（混合解调后的间接光，再乘当前像素反照率）。可选全分辨率积分会读取邻域 reservoir，在当前像素重算方向、BRDF、几何变换和可见性，再混合这些贡献。它不是直接混合邻居最终 RGB，也不是 ReSTIR 的必要步骤。</p>
<p><strong>本场景结果：</strong>ReSTIR＋原重建的单帧 MSE 比原 FG 低约 12%，但 16384 帧累计 MSE 约为原 FG 的 3.33 倍，GPU 1.15→1.83 ms。可选全分辨率积分单帧 MSE 低约 54%，但长累积 MSE 约为原 FG 的 6.92 倍，GPU 约 3.03 ms。本次接入没有提高静态累计精度，因此保留为默认关闭的实验路径，不替换原 FG。</p>
<h2>测试条件与指标</h2><p>1920×1080、Lambert Cornell、同一顶灯点光源。半分辨率 960×540；三组均开启相同的八帧采样相位 jitter。预热 2560 帧，先旁路 Accumulate 采集 16 帧，再各累计 16384 帧。PT 复用同场景 65536 spp 未降噪参考。显示统一 +3EV/ACES/sRGB。时间历史上限 20 个有效候选，空间 2 轮×4 邻居、半径 8 个粗像素；可选全分辨率积分为 16 样本、kernel size=3。GPU 耗时为 511 个区间均值。</p>
<table><tr><th>方案</th><th>16384 帧 MSE</th><th>HDR-FLIP</th><th>未累积单帧 MSE（16 帧平均）</th><th>GPU ms</th></tr>{rows}</table>
<p>这是接入验证，不把 16384 帧直接称为充分收敛。8192→16384 帧检查、单帧时间方差和每个 checkpoint 的误差见 <a href="summary.json">完整数据</a>。历史复用会造成样本相关；单帧更平滑不等于 Accumulate 收敛更快。图像残余误差包含采样误差、DDGI 近似和复用／重建偏差。</p>
<h2>16384 帧结果</h2><a href="comparison.png"><img src="comparison.png"></a><p><a href="pt-reference.png">PT reference 原图</a></p>
<h2>HDR-FLIP 热力图</h2><p>共用固定 [0,1] Magma 色标：暗紫误差小，红橙黄误差大；深蓝灰为统计 mask 外区域，不是各图独立归一化。</p><a href="errors.png"><img src="errors.png"></a>
<h2>关闭 Accumulate 的单帧</h2><a href="raw-comparison.png"><img src="raw-comparison.png"></a>
<h2>32 帧累积</h2><a href="32-comparison.png"><img src="32-comparison.png"></a>
<h2>Pass 组织</h2><p>Visibility → DDGI：ProbeUpdate → PrimaryShading → ReSTIRInitial → ReSTIRTemporal → ReSTIRSpatial（两轮 ping-pong）→ ReSTIRIntegrate → Reconstruct → Accumulate → Display。默认 Integrate 在半分辨率只对自身 reservoir 着色；开启全分辨率积分后按全分辨率 dispatch，Reconstruct 退化为直接合成。关闭 ReSTIR 则使用原来的 HalfGather。</p>
<table><tr><th>GPU 子阶段 ms</th><th>原 FG</th><th>ReSTIR＋原重建</th><th>ReSTIR＋全分辨率积分</th></tr>{passrows}</table>
<h2>与本地 Lumen 的对应关系</h2><p>参考文件为 D:/Unreal/UnrealEngine/Engine/Shaders/Private/Lumen/LumenReSTIRGather.usf 及对应 cpp。已具备均匀半球初始采样、实际命中样本 reservoir、时间重投影与 3×3 历史匹配、空间重采样及 Jacobian、可选全分辨率 spiral 积分。空间两轮×4 邻居、全分辨率 16 样本与所读 UE 默认阶段数量一致；半径和几何阈值有 Falcor 场景适配。</p>
<p>这不是 UE 渲染器的逐行移植。命中点光照来自 Falcor 材质＋直接光＋DDGI，替代 Lumen Surface Cache；使用 Falcor RNG 而非 UE 蓝噪声。可见性使用硬件阴影射线而非 Lumen 的短屏幕空间检测，增加成本。时间复用也使用重连接 Jacobian；最终积分使用 Falcor BRDF 而非 UE 的粗糙镜面近似和 tonemap weighting，尖锐镜面保留独立 FG。未增加 Lumen 的后置双边／时间降噪，继续保留用户选择的 Accumulate。</p>
<p>每个 reservoir 保存命中位置（miss 为方向）、命中法线、辐射亮度、target、W、源表面位置／法线和 M；普通时间复用不重追整条历史着色路径。四个 80 字节结构缓冲，1080p 半分辨率共约 158.2 MiB，初始缓冲在空间阶段复用为 ping-pong。下一帧接收时间阶段历史，不把空间阶段结果反馈回历史。</p>
<h2>验证与限制</h2><p>481×271 奇数尺寸下实际执行通过；验证了全／半分辨率、FG／ReSTIR／时间／空间／全分辨率积分开关的累积重置，及移动镜头时 reservoir 历史继续有效。半分辨率边界采样与重建做了 clamp。原材质 Cornell 的两种积分路径也通过运行与非有限数检查，灯光关闭后会清空历史（不是其他材质的画质评估）。相机移动通过 motion vectors 重投影；灯光、材质、几何变化会保守清空历史，尚未实现动态物体的完整历史运输。</p>
<p>复用在方向变化时近似保持命中点辐射亮度，镜面材质会有局限；极端 Jacobian [0.1,10] 外拒绝和样本接受判定也可能带来偏差，不宣称无偏。被拒绝的邻居不计入合并 M，修正了初版额外压暗的问题。此版主要验证 Lambert Cornell，不能从这组数据推断复杂动态场景性能或画质。</p></html>'''
(O/'report.html').write_text(html,encoding='utf-8');(O/'summary.json').write_text(json.dumps(result,indent=2))
paths=['Source/RenderPasses/RTXGIDDGI/'+n for n in ['RTXGIDDGI.h','RTXGIDDGI.cpp','RTXGIDDGI.rt.slang','ReSTIRGather.slang','DDGIReconstruct.cs.slang']]+['scripts/DDGIAccumulated.py','tests/ddgi/restir_gather_smoke.py','tests/ddgi/restir_gather_material_smoke.py','tests/ddgi/restir_gather_comparison.py','tests/ddgi/score_restir_gather.py']
(O/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((R/p).read_bytes()).hexdigest() for p in paths},indent=2))
