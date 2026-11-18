from pathlib import Path
import sys,json,csv,hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/full-gather-nrd-comparison';OLD=ROOT/'build/three-way-half-gather'
OUT=ROOT/'docs/2026-11-18_DDGI-full-vs-half-final-gather';OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
assert '(Error)' not in (ROOT/'build/full-gather-nrd-comparison.log').read_text(errors='replace')
assert info['stats']['finite']
for k in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:assert info['stats'][k]==0
previous=json.loads((ROOT/'docs/2026-11-18_DDGI-half-final-gather-comparison/summary.json').read_text())
params=previous['flip_parameters']
def read(path):
    a=OpenEXR.File(str(path)).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all(),path
    return np.ascontiguousarray(a)
def get(folder,tag,ch):return read(folder/(tag+'.'+ch+'.0.exr'))
ref=read(OLD/'reference-65536spp.exr')
mask=np.linalg.norm(get(OLD,'pt-a-32768','Visibility.normW'),axis=-1)>.5
assert np.array_equal(mask,np.linalg.norm(get(DATA,'full-0','Visibility.normW'),axis=-1)>.5)
assert get(DATA,'full-dimensions','DDGI.diffuseRadianceHitDist').shape[:2]==(270,480)
def score(a):
    error=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    return {'mse':float(np.mean((ref[mask].astype(float)-a[mask])**2)),'hdr_flip':float(error[mask].mean())}
images=[get(DATA,'full-'+str(i),'Compose.output') for i in range(64)]
rows=[{'frame':i,**score(a)} for i,a in enumerate(images)]
full={k:float(np.mean([r[k] for r in rows])) for k in ['mse','hdr_flip']}
full['temporal_rgb_variance']=float(np.var(np.array(images)[:,mask].astype(float),axis=0).mean())
full['first_last_32_mean_relative_change']=float(abs(np.mean(images[:32])-np.mean(images[32:]))/max(np.mean(images),1e-12))
full['warm256']=score(get(DATA,'full-warm-256','Compose.output'))
full['warm512']=score(get(DATA,'full-warm-512','Compose.output'))
assert full['first_last_32_mean_relative_change']<.005,full
t=json.loads((DATA/'full-timing.json').read_text())
timing={'samples':t['frame_count'],'passes':{stage:t['events']['/onFrameRender/RenderGraphExe::execute()/'+stage+'/gpu_time']['stats']['mean'] for stage in ['Visibility','DDGI','Denoiser','Compose','Display']}}
timing['gpu_frame_ms']=t['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['mean']
timing['gpu_frame_std_ms']=t['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['std_dev']
timing['sum_without_display_ms']=sum(v for k,v in timing['passes'].items() if k!='Display')
metrics={**previous['metrics'],'full':full};times={**previous['timing'],'full':timing}
delta={k:full[k]/metrics['half'][k]-1 for k in ['mse','hdr_flip','temporal_rgb_variance']}
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
def display(a):
    x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
items=[('Original DDGI',get(OLD,'ddgi-63','DDGI.color')),
    ('Half FG + NRD / 240 x 135',get(OLD,'half-63','Reconstruct.color')),
    ('Full FG + NRD / 480 x 270',images[-1]),('PT reference / 65536 spp',ref)]
panel=Image.new('RGB',(960,616),(23,26,31));draw=ImageDraw.Draw(panel)
for i,(label,a) in enumerate(items):
    x=i%2*480;y=i//2*308;draw.text((x+10,y+10),label,font=font,fill='white');panel.paste(display(a),(x,y+38))
panel.save(OUT/'comparison.png')
frames=[]
for i,a in enumerate(images):
    canvas=Image.new('RGB',(960,308),(23,26,31));draw=ImageDraw.Draw(canvas)
    draw.text((10,10),'Half FG + NRD',font=font,fill='white');draw.text((490,10),'Full FG + NRD',font=font,fill='white')
    canvas.paste(display(get(OLD,'half-'+str(i),'Reconstruct.color')),(0,38));canvas.paste(display(a),(480,38));frames.append(canvas)
frames[0].save(OUT/'stability.gif',save_all=True,append_images=frames[1:],duration=80,loop=0)
result={'metrics':metrics,'timing':times,'full_relative_to_half':delta,'capture':info,
    'flip_parameters':params,'reference_convergence':previous['convergence']}
(OUT/'summary.json').write_text(json.dumps(result,indent=2))
with (OUT/'full-metrics.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
labels={'ddgi':'原始 DDGI','half':'半分辨率 FG + NRD','full':'全分辨率 FG + NRD'}
table=''.join(f"<tr><td>{labels[k]}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.5f}</td><td>{v['temporal_rgb_variance']:.7g}</td><td>{times[k]['gpu_frame_ms']:.4f}</td></tr>" for k,v in metrics.items())
conclusion=('全分辨率的 MSE 和 HDR-FLIP 均优于半分辨率。' if delta['mse']<0 and delta['hdr_flip']<0 else '全分辨率未同时改善 MSE 和 HDR-FLIP。')
conclusion+=('但仍未同时优于原始 DDGI。' if not(full['mse']<metrics['ddgi']['mse'] and full['hdr_flip']<metrics['ddgi']['hdr_flip']) else '且两项指标均优于原始 DDGI。')
text=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>全分辨率与半分辨率 FG + NRD</title>
<style>body{{max-width:1100px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#ddd;background:#171a20}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:8px 16px}}table{{border-collapse:collapse}}a{{color:#8dc7ff}}</style>
<h1>全分辨率 final gather 对照实验</h1><p>{conclusion}相对半分辨率，全分辨率 MSE 变化 {delta['mse']:+.1%}，HDR-FLIP 变化 {delta['hdr_flip']:+.1%}。</p>
<img src="comparison.png"><table><tr><th>方案</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>时间方差 ↓</th><th>GPU 帧耗时 ms ↓</th></tr>{table}</table>
<p>沿用同一 Lambert Cornell、当前 Test Harness 点光源衰减、相机、480×270 输出和未经降噪的 65536 spp PT reference。原始 DDGI / 半分辨率的结果直接沿用上一组，没有改变评分范围或 HDR-FLIP 曝光参数。全分辨率仍是每像素每帧 1 根漫反射 FG 射线；NRD 使用相同 RELAX 参数。无 Accumulate、无 DLSS；全分辨率不经过半分辨率重建。</p>
<p>Probe 2048 帧预热，然后 NRD 重置并预热 512 帧，连续采集 64 帧逐帧评分。Probe 持续更新。全分辨率连续样本前后各 32 帧平均亮度变化 {full['first_last_32_mean_relative_change']:.3%}。MSE 为线性 HDR 完整光照，时间方差为固定可见表面像素的 RGB 总体方差均值。相同参考的残余噪声估计 MSE 为 {previous['convergence']['estimated_65536spp_reference_noise_mse']:.7g}。</p>
<img src="stability.gif"><p>RTX 5070 / D3D12。GPU 帧耗时包含 GBuffer、probe 更新、FG、NRD、合成、色调映射，不含 CPU 和文件保存；每种 255 个时间戳区间。全分辨率分项：DDGI {timing['passes']['DDGI']:.4f} ms，NRD {timing['passes']['Denoiser']:.4f} ms，合成 {timing['passes']['Compose']:.4f} ms。不同方案来自各自实测运行，存在运行间频率波动。</p>
<p>这项实验隔离的是“采样/降噪分辨率及其重建”的整体影响。相同 NRD 像素半径在半分辨率下覆盖更大的屏幕区域，因此不等同于只改变射线数。FG 能把第一段可见性追踪得更准确，但后续仍由 DDGI 近似，且单帧采样噪声与 NRD 滤波偏差可能抵消收益；不能保证最终整体指标必然改善。要单独判断积分器误差，需要另做当前灯光下的未降噪 FG 收敛实验。</p>
<pre>build\\windows-vs2022\\bin\\Release\\Mogwai.exe --device-type d3d12 --headless --deferred --script tests/ddgi/full_gather_nrd_comparison.py --width 480 --height 270 --logfile build/full-gather-nrd-comparison.log
python tests/ddgi/score_full_gather_nrd_comparison.py</pre><p><a href="summary.json">结构化结果</a> · <a href="full-metrics.csv">全分辨率逐帧指标</a> · <a href="../2026-11-18_DDGI-half-final-gather-comparison/report.html">上一组实验</a></p></html>'''
(OUT/'report.html').write_text(text,encoding='utf-8')
paths=['scripts/RTXGIDDGIFinalGather.py','tests/ddgi/full_gather_nrd_comparison.py','tests/ddgi/score_full_gather_nrd_comparison.py']
(OUT/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},indent=2))
print(json.dumps({'metrics':metrics,'full_timing':timing,'change':delta,'report':str(OUT/'report.html')},indent=2))
