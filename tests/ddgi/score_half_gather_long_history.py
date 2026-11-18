from pathlib import Path
import sys,json,csv
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/half-gather-long-history';OLD=ROOT/'build/three-way-half-gather'
OUT=ROOT/'docs/2026-11-18_DDGI-half-history-convergence';OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
assert '(Error)' not in (ROOT/'build/half-gather-long-history.log').read_text(errors='replace')
assert len(set(info['history_reset_counts']))==1
assert info['stats']['finite']
for k in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:assert info['stats'][k]==0
old=json.loads((ROOT/'docs/2026-11-18_DDGI-half-final-gather-comparison/summary.json').read_text())
params=old['flip_parameters']
def read(p):
    a=OpenEXR.File(str(p)).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all(),p
    return np.ascontiguousarray(a)
ref=read(OLD/'reference-65536spp.exr')
mask=np.linalg.norm(read(OLD/'pt-a-32768.Visibility.normW.0.exr'),axis=-1)>.5
summary={};rows=[];last={}
for warm in info['warmup_windows']:
    images=[];measurements=[]
    assert np.array_equal(mask,np.linalg.norm(read(DATA/f'warm-{warm}-0.Visibility.normW.0.exr'),axis=-1)>.5)
    for i in range(64):
        a=read(DATA/f'warm-{warm}-{i}.Reconstruct.color.0.exr');images.append(a)
        error=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
        r={'warmup_frames':warm,'frame':warm+i+1,'mse':float(np.mean((ref[mask].astype(float)-a[mask])**2)),
            'hdr_flip':float(error[mask].mean())}
        measurements.append(r);rows.append(r)
    summary[str(warm)]={k:float(np.mean([r[k] for r in measurements])) for k in ['mse','hdr_flip']}
    summary[str(warm)]['temporal_rgb_variance']=float(np.var(np.array(images)[:,mask].astype(float),axis=0).mean())
    summary[str(warm)]['mse_min']=min(r['mse'] for r in measurements)
    summary[str(warm)]['mse_max']=max(r['mse'] for r in measurements)
    last[warm]=images[-1]
delta={k:summary['4096'][k]/summary['512'][k]-1 for k in ['mse','hdr_flip','temporal_rgb_variance']}
baseline_difference={k:summary['512'][k]/old['metrics']['half'][k]-1 for k in ['mse','hdr_flip']}
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
def display(a):
    x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
panel=Image.new('RGB',(1440,308),(23,26,31));draw=ImageDraw.Draw(panel)
for i,(label,a) in enumerate([('Half FG + NRD / warmup 512',last[512]),('Half FG + NRD / warmup 4096',last[4096]),('PT reference / 65536 spp',ref)]):
    draw.text((480*i+10,10),label,font=font,fill='white');panel.paste(display(a),(480*i,38))
panel.save(OUT/'comparison.png')
result={'windows':summary,'change_4096_vs_512':delta,'repeat_512_vs_previous':baseline_difference,
    'capture':info,'flip_parameters':params,'diffuse_max_accumulated_frames':31,'diffuse_fast_history_frames':2}
(OUT/'summary.json').write_text(json.dumps(result,indent=2))
with (OUT/'metrics.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
table=''.join(f"<tr><td>{warm}</td><td>{v['mse']:.7g}</td><td>{v['hdr_flip']:.5f}</td><td>{v['temporal_rgb_variance']:.7g}</td></tr>" for warm,v in summary.items())
text=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>半分辨率 FG：延长 NRD 预热</title>
<style>body{{max-width:1480px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#ddd;background:#171a20}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:8px 16px}}table{{border-collapse:collapse}}a{{color:#8dc7ff}}</style>
<h1>半分辨率 FG + NRD：多等一些帧是否改善？</h1>
<p>不修改采样、滤波或上采样参数，保持静止相机，延长 NRD 预热。每个阶段都评价之后连续 64 张单帧输出；没有额外图像平均。4096 相对 512 帧的 MSE 变化 {delta['mse']:+.2%}，HDR-FLIP 变化 {delta['hdr_flip']:+.2%}。</p>
<table><tr><th>NRD 预热帧数</th><th>MSE ↓</th><th>HDR-FLIP ↓</th><th>时间方差 ↓</th></tr>{table}</table><img src="comparison.png">
<p>复用同一未经降噪的 PT 65536 spp reference、可见表面 mask 和 HDR-FLIP 曝光参数。仍是 480×270 输出 / 240×135 FG 与 NRD。Probe 先预热 2048 帧，之后始终更新；NRD 仅在开始重置一次，四个窗口之间没有历史重置。延长测试也让 probe 得到更多更新，因此测的是等待整个流程后的效果。</p>
<p>NRD RELAX 当前 diffuseMaxAccumulatedFrameNum=31，快速历史为 2 帧。它限制历史权重，并持续混入当前样本，不会像 AccumulatePass 那样把等过的 4096 帧全部等权平均。因此输出达到稳态后仍可能有噪声，空间滤波与半分辨率重建的偏差也不会仅靠等待消失。此实验只能判断当前设置延长等待的效果，不能单独确定采样、滤波、重建各自贡献了多少误差。</p>
<p>新跑的 512 帧窗口相对上次同条件结果：MSE 变化 {baseline_difference['mse']:+.3%}，HDR-FLIP 变化 {baseline_difference['hdr_flip']:+.3%}。完整逐帧数据保留在 CSV。</p>
<pre>build\\windows-vs2022\\bin\\Release\\Mogwai.exe --device-type d3d12 --headless --deferred --script tests/ddgi/half_gather_long_history.py --width 480 --height 270 --logfile build/half-gather-long-history.log
python tests/ddgi/score_half_gather_long_history.py</pre>
<p><a href="summary.json">结果 JSON</a> · <a href="metrics.csv">逐帧指标</a> · <a href="../2026-11-18_DDGI-full-vs-half-final-gather/report.html">全/半分辨率对比</a></p></html>'''
(OUT/'report.html').write_text(text,encoding='utf-8')
print(json.dumps({'windows':summary,'change':delta,'repeat':baseline_difference},indent=2))
