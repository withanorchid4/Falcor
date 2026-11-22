"""Four equal-exposure screenshots and shared shadow-detail crops."""
from pathlib import Path
import sys,json
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-sun50-20261120';O=R/'docs/2026-11-20_Sponza方向光50四组稳定对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
assert all(r['stable'] for r in info['runs'].values()),'Do not label unfinished results converged'
cfg=json.loads((D/'display.json').read_text());names=['ddgi','half','worldcache','pt']
labels={'ddgi':'DDGI / direct probe interpolation','half':'DDGI + half-resolution FG','worldcache':'WorldCache + half-resolution FG','pt':'PT Reference / undenoised'}
zh={'ddgi':'原生 DDGI','half':'DDGI＋半分辨率 FG','worldcache':'WorldCache＋半分辨率 FG','pt':'PT Reference（未经降噪）'}
def exr(p):return OpenEXR.File(str(p)).channels()['RGB'].pixels
imgs={n:exr(D/(n+'-'+str(info['runs'][n]['final_frame'])+'.Accumulate.output.0.exr')) for n in names}
norms={n:exr(D/(n+'-'+str(info['runs'][n]['final_frame'])+'.Visibility.normW.0.exr')) for n in names}
assert all(np.array_equal(norms['pt'],norms[n]) for n in names)
mask=np.linalg.norm(norms['pt'],axis=-1)>.5;ref=imgs['pt']
def display(a,extra_ev=0):
 x=np.maximum(a*2**(cfg['exposure_ev']+extra_ev),0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
metrics={}
for n,a in imgs.items():
 display(a).save(O/(n+'.png'))
 if n!='pt':
  f=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
  metrics[n]={'mse':float(np.mean((a[mask].astype(np.float64)-ref[mask])**2)),'hdr_flip':float(f[mask].mean())}
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',30)
def panel(images,w,h,title=''):
 out=Image.new('RGB',(2*w,2*(h+54)+54*bool(title)),(23,26,31));d=ImageDraw.Draw(out)
 if title:d.text((12,8),title,font=font,fill='white')
 for i,n in enumerate(names):
  x=i%2*w;y=i//2*(h+54)+54*bool(title);d.text((x+12,y+8),labels[n],font=font,fill='white');out.paste(images[n].resize((w,h)),(x,y+54))
 return out
panel({n:display(a) for n,a in imgs.items()},1920,1080).save(O/'comparison-4k.png')
panel({n:display(a) for n,a in imgs.items()},960,540).save(O/'comparison.png')
rois={'column-floor':(440,640,1140,1080),'arches':(120,150,820,650)}
for tag,roi in rois.items():
 crops={n:display(a,2).crop(roi) for n,a in imgs.items()};panel(crops,roi[2]-roi[0],roi[3]-roi[1],'Shadow details / shared exposure +2 EV').save(O/(tag+'.png'))
summary={'capture':info,'display':cfg,'metrics':metrics,'flip_parameters':params,'gbuffer_normals_identical':True,'detail_crops':rois,'detail_exposure_offset_ev':2}
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''
for n in names:
 r=info['runs'][n];c=r['checkpoints'][str(r['final_frame'])];m=metrics.get(n,{})
 rows+=f'<tr><td>{zh[n]}</td><td>{r["final_frame"]}</td><td>{r["spp"]}</td><td>{c["relative_rgb_rms"]:.3%}</td><td>{c["display_mean_abs_levels"]:.4f}</td><td>{c["display_p99_abs_levels"]:.4f}</td><td>{m.get("mse","—")}</td><td>{m.get("hdr_flip","—")}</td></tr>'
observations=(O/'observations.html').read_text(encoding='utf-8') if (O/'observations.html').exists() else '<p>图像检查待完成。</p>'
html=f'''<!doctype html><meta charset="utf-8"><title>Sponza 方向光 50 四组稳定对比</title><style>body{{background:#171a1f;color:#eee;font:17px/1.7 sans-serif;max-width:1600px;margin:32px auto;padding:0 20px}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:9px}}table{{border-collapse:collapse}}a{{color:#9cf}}</style>
<h1>SponzaLambert：方向光强度 50</h1><p>保持原相机位置 (-9,1.6,0)、看向 (8,2.5,0)。关闭 Atrium Point，开启 Atrium Sun，RGB intensity=(50,50,50)，方向沿场景原值 (0.3,-1,0.2)。没有新增环境光或 AO。</p>
<p>四组均为 1920×1080，使用 Accumulate 的 SingleCompensated 累积，静态镜头。DDGI 使用官方 22³ 布局、256 rays/probe、每帧全量更新；两条 FG 均为 960×540，每粗像素每帧一根漫反射射线。WorldCache 参数与上一轮相同：8×8 更新起点下采样、3 跳、history 16、density 20。主命中法线修正开启。ReSTIR、NRD、RTXDI、额外 WRC 复用关闭。</p>
<p>三条 GI 各预热 8192 帧后清空画面历史并累积。PT 为重新渲染的方向光参考，8 spp/帧、最大 31 次表面/漫反射反弹、NEE+MIS、关闭 RR，不降噪。没有复用点光源 PT。最终图均通过一次累积翻倍检查（GI 至少累积 2048 帧）：线性 RGB RMS 变化/自身 RGB RMS &lt;0.1%，统一显示映射后平均绝对变化 &lt;0.25/255、99 百分位 &lt;2/255。该判据表示静态画面实用稳定，不保证每个像素零噪声。</p>
<p>原图统一曝光 {cfg['exposure_ev']:.4f} EV、ACES fitted＋sRGB。局部图仅统一额外提亮 2 EV，不单独调整某个算法；亮部会更容易饱和，局部图用于观察阴影区。GBuffer 法线逐像素一致，确认相机与可见几何一致。</p>
<a href="comparison-4k.png"><img src="comparison.png"></a><p>1080p 单图：<a href="ddgi.png">原生 DDGI</a> · <a href="half.png">DDGI＋半 FG</a> · <a href="worldcache.png">WorldCache＋半 FG</a> · <a href="pt.png">PT Reference</a></p>
<h2>画面检查</h2>{observations}<h2>柱脚与地面（统一＋2 EV）</h2><img src="column-floor.png"><h2>拱廊阴影区（统一＋2 EV）</h2><img src="arches.png">
<h2>稳定性与参考误差</h2><table><tr><th>方案</th><th>累积帧数</th><th>累计 spp / FG 粗像素样本数</th><th>尾段相对 RGB RMS</th><th>显示平均变化 /255</th><th>显示 P99 变化 /255</th><th>MSE 对 PT</th><th>HDR-FLIP 对 PT</th></tr>{rows}</table><p>原生 DDGI 不从像素发射 FG，表中其样本数只表示累积帧数。MSE 使用可见表面 mask 内线性 HDR RGB；HDR-FLIP 使用共同曝光范围、ACES、PPD 67。<a href="summary.json">完整配置和数据</a>。</p>'''
(O/'report.html').write_text(html,encoding='utf-8');print(metrics)
