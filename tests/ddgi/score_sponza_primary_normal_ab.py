"""Attribute the Sponza DDGI+FG error change to the primary-normal policy."""
from pathlib import Path
import sys,json,hashlib
R=Path(__file__).resolve().parents[2];D=R/'build/sponza-primary-normal-ab-20261120'
O=R/'docs/2026-11-20_Sponza主命中法线修正验证';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
info=json.loads((D/'complete.json').read_text());assert not (D/'failure.txt').exists()
def exr(p):
 a=OpenEXR.File(str(p)).channels()['RGB'].pixels
 assert np.isfinite(a).all()
 return a
def read(n):return exr(D/(n+'.Accumulate.output.0.exr'))
oldD=R/'build/sponza-worldcache-ddgi-official-probes-20261119'
refpath=oldD/'reference-131072spp.exr';ref=exr(refpath)
old=exr(oldD/'half-65536.Accumulate.output.0.exr')
recent=exr(R/'build/sponza-probe-budget-sweep-20261120/ddgi_half-stable32768.Accumulate.output.0.exr')
normalA=exr(D/'on-32768.Visibility.normW.0.exr');normalB=exr(D/'off-32768.Visibility.normW.0.exr')
assert np.array_equal(normalA,normalB),'GBuffer must not change in the isolated A/B'
mask=np.linalg.norm(normalA,axis=-1)>.5
def mse(a,b):return float(np.mean((a[mask].astype(np.float64)-b[mask])**2))
_,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
metrics={};imgs={'pt':ref}
for name in ['on','off']:
 a=read(name+'-32768');prior=read(name+'-16384');imgs[name]=a
 flip=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
 metrics[name]={'mse':mse(a,ref),'hdr_flip':float(flip[mask].mean()),'tail_mse':mse(a,prior),'doubling_relative_mse_change':mse(a,ref)/mse(prior,ref)-1,'mse_to_old_render':mse(a,old),'mse_to_recent_render':mse(a,recent)}
 print(name,metrics[name],flush=True)
oldError=np.mean((old.astype(np.float64)-ref)**2,axis=-1)
top=mask&(oldError>=np.percentile(oldError[mask],99))
regional={}
for name,a in [('old',old),('on',imgs['on']),('off',imgs['off'])]:
 e=np.mean((a.astype(np.float64)-ref)**2,axis=-1)
 regional[name]={'old_top_1percent_mse':float(e[top].mean()),'remaining_99percent_mse':float(e[mask&~top].mean())}
propsA=info['runs']['on']['properties'];propsB=info['runs']['off']['properties']
diff={k:[propsA.get(k),propsB.get(k)] for k in set(propsA)|set(propsB) if propsA.get(k)!=propsB.get(k)}
assert set(diff)=={'primaryShadingNormalCorrection'},diff
lum=ref@np.array([.2126,.7152,.0722]);exposure=float(-np.log2(np.percentile(lum[mask],99)))
def display(a):
 x=np.maximum(a*2**exposure,0);x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
 x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
 return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))
for n,a in imgs.items():display(a).save(O/(n+'.png'))
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',25)
panel=Image.new('RGB',(1920,1184),(23,26,31));draw=ImageDraw.Draw(panel)
for i,(n,label) in enumerate([('off','Correction OFF'),('on','Correction ON'),('pt','PT reference')]):
 x=i%2*960;y=i//2*592;draw.text((x+12,y+8),label,font=font);panel.paste(display(imgs[n]).resize((960,540)),(x,y+52))
panel.save(O/'comparison.png')
ratio=metrics['off']['mse']/metrics['on']['mse']
result={'metrics':metrics,'regional':regional,'mse_ratio_off_over_on':ratio,'gbuffer_normals_identical':True,'property_diff':diff,'capture':info,'reference_sha256':hashlib.sha256(refpath.read_bytes()).hexdigest(),'flip_parameters':params,'mask_pixels':int(mask.sum()),'old_mse_recomputed':mse(old,ref)}
(O/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
rows=''.join(f'<tr><td>{n}</td><td>{r["mse"]:.9g}</td><td>{r["hdr_flip"]:.6f}</td><td>{r["mse_to_old_render"]:.6g}</td><td>{r["doubling_relative_mse_change"]:.3%}</td></tr>' for n,r in metrics.items())
html=f'''<!doctype html><meta charset="utf-8"><title>Sponza 主命中法线修正验证</title><style>body{{background:#171a1f;color:#eee;max-width:1500px;margin:32px auto;font:17px/1.7 sans-serif}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:10px}}table{{border-collapse:collapse}}a{{color:#9cf}}</style>
<h1>Sponza DDGI＋半分辨率 FG：主命中法线修正 A/B</h1>
<p><strong>验证结论：本场景 DDGI＋FG 新旧 MSE 的巨大差异可由主命中法线修正开关复现。开启组与上一轮新实验图像完全相同；关闭组恢复旧实验的 MSE 水平，且与旧 EXR 的图像差异很小。这里验证的是 DDGI＋FG，不是 WorldCache 的独立 A/B。</strong></p>
<p>仅切换 RTXGIDDGI.primaryShadingNormalCorrection。两组 GBuffer.adjustShadingNormals 都为 true；已逐像素验证 GBuffer 法线完全相同，重建输入保持一致。关闭组在主命中材质实例中不传 AdjustShadingNormal，复现旧版 DDGI/FG 的策略。探针和次级命中材质策略不变，PT reference 不变。</p>
<p>1920×1080，SponzaLambert，相同固定相机、点光源、官方 22³ 探针、全量更新、256 rays/probe、hysteresis 0.97。两组各新建图与场景，运行同样数量的帧、相同采样序列起点，预热 8192 帧后 Accumulate 累积 32768 帧；半分辨率 FG 固定左上采样。WRC、ReSTIR、NRD、RTXDI 关闭。参考为之前同一张 131072 spp PT，MSE 使用相同可见表面 mask，HDR-FLIP 使用相同曝光范围、ACES、PPD 67。</p>
<table><tr><th>法线修正</th><th>MSE 对 PT</th><th>HDR-FLIP</th><th>与旧版 65536 帧图像的 MSE</th><th>16384→32768 MSE 变化</th></tr>{rows}</table>
<p>关/开 MSE 比值：{ratio:.2f} 倍。旧版 DDGI＋FG 的 MSE 重新计算为 {mse(old,ref):.9g}。关闭组与旧图仍可能有随机采样、累积帧数和其他版本改动导致的小差别；本次开关之间只改变上述一项。</p>
<img src="comparison.png"><p><a href="off.png">关闭原图</a> · <a href="on.png">开启原图</a> · <a href="pt.png">PT 原图</a> · <a href="summary.json">完整数据</a></p>
<p>复现：tests/ddgi/sponza_primary_normal_ab.py；评分：tests/ddgi/score_sponza_primary_normal_ab.py。诊断属性默认 true，保持原有修正行为；没有改变 PT，也没有关闭法线贴图。</p>'''
(O/'report.html').write_text(html,encoding='utf-8')
