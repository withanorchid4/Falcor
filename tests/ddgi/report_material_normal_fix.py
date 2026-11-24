"""Summarize matched source variants; metrics use linear HDR before display mapping."""
from pathlib import Path
import sys,json,statistics
R=Path(__file__).resolve().parents[2];O=R/'build/material-normal-fix'
sys.path.insert(0,str(R/'build/final-gather-python'));sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR
read=lambda p:OpenEXR.File(str(p)).channels()['RGB'].pixels
fresh=O/'pt-current-pt-8192.Accumulate.output.0.exr'
ref=read(fresh if fresh.exists() else R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr');normal=read(O/'pt-current-pt-8192.Visibility.normW.0.exr' if fresh.exists() else R/'build/sponza-sharc-official-20261122/pt-512.Visibility.normW.0.exr');mask=(normal**2).sum(-1)>.5;lum=ref@np.array([.2126,.7152,.0722]);dark=mask&(lum<.05)
images=[]
for f in sorted(O.glob('*.Accumulate.output.*.exr')):
 a=read(f);assert np.isfinite(a).all(),f
 n=f.name.split('.Accumulate')[0];la=a@np.array([.2126,.7152,.0722]);row={'name':n,'mse':float(np.mean((a[mask].astype(float)-ref[mask])**2)),'dark_bias_percent':float(100*(la[dark].sum()/lum[dark].sum()-1)),'mean_bias_percent':float(100*(la[mask].sum()/lum[mask].sum()-1))}
 images.append(row);print('image',n,'MSE',round(row['mse'],8),'dark%',round(row['dark_bias_percent'],3),'all%',round(row['mean_bias_percent'],3))
timings=[]
for f in sorted(O.glob('*-timing.json')):
 if f.name.startswith('smoke'):continue
 events=json.loads(f.read_text())['events'];values={k:statistics.mean(v['records'][4:]) for k,v in events.items() if k.endswith('/gpu_time') and len(v['records'])>4}
 timings.append({'name':f.stem.removesuffix('-timing'),'gpu_ms':values})
groups={}
for mode in ['worldcache','sharc','ddgi']:
 for variant in ['before','after']:
  a=[x for x in timings if x['name'].startswith(variant+'-') and x['name'].endswith('-'+mode)]
  if not a:continue
  key=variant+'-'+mode;groups[key]={k:statistics.mean(x['gpu_ms'][k] for x in a) for k in a[0]['gpu_ms']}
  print('timing',key,len(a),round(groups[key]['/onFrameRender/RenderGraphExe::execute()/gpu_time'],4))
(O/'summary.json').write_text(json.dumps({'images':images,'timing_groups':groups,'timing_runs':timings,'reference_spp':65536,'dark_definition':'PT luminance < 0.05, valid GBuffer normal','resolution':[1920,1080]},indent=2))
if '--report' not in sys.argv:raise SystemExit
import shutil,html,hashlib,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
D=R/'docs/2026-11-23_Material-normal-fix';D.mkdir(exist_ok=True)
_,_,flip_params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
quality={};stability={};exposure=-float(np.log2(np.quantile(lum[mask],.99)))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
def display(a,extra=0):
 x=np.maximum(a*2**(exposure+extra),0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1);x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))
mode_names={'worldcache':'Lumen WorldCache','sharc':'SHaRC','ddgi':'DDGI + half FG'}
for mode in mode_names:
 arrays=[]
 for variant in ['before','after']:
  name=variant+'-0-'+mode+'-8192';a=read(O/(name+'.Accumulate.output.0.exr'));arrays.append(a)
  row=next(x.copy() for x in images if x['name']==name)
  f=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=flip_params.copy())[0][:,:,0];row['hdr_flip']=float(f[mask].mean());quality[variant+'-'+mode]=row
  earlier=read(O/(variant+'-0-'+mode+'-4096.Accumulate.output.0.exr'))
  stability[variant+'-'+mode]={'relative_rgb_rms_4096_to_8192':float(np.sqrt(np.mean((a[mask].astype(float)-earlier[mask])**2)/np.mean(a[mask].astype(float)**2)))}
  n=read(O/(name+'.Visibility.normW.0.exr'));assert np.array_equal(n,normal),(mode,variant,'GBuffer mismatch')
 for crop in [False,True]:
  w,h=(700,440) if crop else (640,360);panel=Image.new('RGB',(w*3,h+40),(23,26,31));draw=ImageDraw.Draw(panel)
  for i,(im,label) in enumerate(zip([ref,*arrays],['PT Reference','Before','After'])):
   png=display(im,2 if crop else 0);png=png.crop((440,640,1140,1080)) if crop else png.resize((w,h));panel.paste(png,(i*w,40));draw.text((i*w+10,7),mode_names[mode]+' / '+label,font=font,fill='white')
  panel.save(D/(mode+('-contact.png' if crop else '-comparison.png')))
props={}
for variant in ['before','after']:
 props[variant]={r['mode']:r['properties'] for r in json.loads((O/(variant+'-0-complete.json')).read_text())}
assert props['before']==props['after'],'Options changed between A/B'
summary=json.loads((O/'summary.json').read_text());summary.update(quality=quality,stability=stability,common_exposure_ev=exposure,flip_parameters=flip_params,options_identical=True,provenance=json.loads((O/'provenance.json').read_text()))
(D/'summary.json').write_text(json.dumps(summary,indent=2));(O/'final-summary.json').write_text(json.dumps(summary,indent=2))
rows='';gp='/onFrameRender/RenderGraphExe::execute()/gpu_time'
for mode in mode_names:
 b=quality['before-'+mode];a=quality['after-'+mode];tb=groups['before-'+mode][gp];ta=groups['after-'+mode][gp]
 rows+=f'<tr><td>{mode_names[mode]}</td><td>{b["dark_bias_percent"]:+.2f}% → {a["dark_bias_percent"]:+.2f}%</td><td>{b["mse"]:.8g} → {a["mse"]:.8g}</td><td>{b["hdr_flip"]:.5f} → {a["hdr_flip"]:.5f}</td><td>{tb:.3f} → {ta:.3f} ms ({100*(ta/tb-1):+.2f}%)</td></tr>'
pt=next(x['gpu_ms'][gp] for x in timings if x['name']=='pt-current-pt')
report='''<!doctype html><meta charset="utf-8"><title>材质法线一致性修复对比</title><style>body{font:16px/1.7 system-ui;max-width:1400px;margin:35px auto;padding:0 20px}img{max-width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}pre{background:#eee;padding:15px;overflow:auto}</style><h1>材质法线一致性修复 · 2026-11-23</h1><p>RTX 5070 / D3D12 Release，SponzaLambert，1920×1080，方向光强度 50。原图中的法线贴图、几何、材质和相机一致。比较的是线性 HDR 输出，使用同一曝光和显示变换。暗部定义为 PT luminance &lt; 0.05 且法线有效；百分比是区域平均亮度比值，不是逐像素比值平均。</p><h2>改动范围</h2><p>共用漫反射光照改用 BSDFProperties.guideNormal，并调用 Falcor 的反射半球有效性检查。WorldCache 和 SHaRC 的后续余弦采样使用同一最终法线及半球检查；SHaRC 从相机出发的第一个顶点对齐主表面法线修正策略。继续保留原来的 Lambert 漫反射近似与反照率权重，不把镜面 BRDF 写入缓存。WorldCache 第一根射线只负责缓存覆盖、不积累主表面 throughput，其提议分布保持不变。</p><p>缓存布局、法线键、格子尺寸、更新预算、历史、材质去调制、8 顶点上限、throughput 截断、俄罗斯轮盘和半分辨率重建均未修改。三个受测模式的前后属性逐项相同。光栅化和 multi-view 默认仍关闭。</p><h2>结果</h2><table><tr><th>方案</th><th>暗部偏差</th><th>HDR RGB MSE ↓</th><th>HDR-FLIP ↓</th><th>完整渲染图 GPU 时间</th></tr>'''+rows+f'''</table><p>当前 PTReference（8 spp/帧）的完整图 GPU 时间为 {pt:.3f} ms；画质参考复用相同场景/相机的 65536 spp PT 图。8 spp 的单帧时间不代表参考图的生成总成本，也不代表与缓存方案同等画质。</p>'''
report+='''<h2>测试方法与限制</h2><p>版本顺序 A/B/B/A。每个模式每次先预热 2048 帧，再采集 512 帧 GPU 时间，剔除最初 4 条记录；每版本两次运行取均值，单次结果保存在 JSON。计时包含 GBuffer、缓存或探针更新、FG、重建、Accumulate 和显示，不含截图和 stats 回读。首轮 A/B 计时后重置屏幕累积，分别保存 4096/8192 帧截图。GBuffer 法线与 PT 参考逐像素一致；输出全部有限。</p><p>这是固定预算比较，不声称完全收敛。4096→8192 的变化记录在 summary.json；小幅画质/性能差异应结合采样误差与运行间波动判断。修复材质模型不保证所有近似 GI 的误差单调降低，缓存与重建仍有偏差。本轮未验证复杂镜面/透射材质或动态场景。</p>'''
for mode in mode_names:report+=f'<h2>{mode_names[mode]}</h2><img src="{mode}-comparison.png"><p>柱脚局部：三图统一额外 +2 EV。</p><img src="{mode}-contact.png">'
report+='''<h2>复现</h2><p>先构建 Release RTXGIDDGI，准备 Sponza 场景资源。运行时关闭其他 Mogwai，不要同时构建 shader。脚本在输出目录中切换 shader 版本，结束时恢复当前修复源码，不改动源文件。</p><pre>python tests/ddgi/run_material_normal_comparison.py
python tests/ddgi/report_material_normal_fix.py --report
# 可选：重新生成 65536 spp PT 参考；没有旧参考时自动生成。
python tests/ddgi/run_material_normal_comparison.py --generate-reference</pre><p>分析依赖 numpy、OpenEXR、Pillow、matplotlib、flip_evaluator。完整原始输出写入 build/material-normal-fix，报告保存整理后的参数、测量值和对比图。</p><p><a href="summary.json">详细数据与稳定性</a> · <a href="../../../tests/ddgi/run_material_normal_comparison.py">运行脚本</a></p>'''
report=report.replace('../../../tests/','../../tests/')
(D/'report.html').write_text(report,encoding='utf-8')
for mode in mode_names:print('FINAL',mode,'dark',quality['before-'+mode]['dark_bias_percent'],quality['after-'+mode]['dark_bias_percent'],'ms',groups['before-'+mode][gp],groups['after-'+mode][gp])
print('PT ms',pt)
