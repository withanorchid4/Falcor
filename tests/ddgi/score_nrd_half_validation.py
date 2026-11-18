from pathlib import Path
import sys,json,csv,hashlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/nrd-half-validation';OLD=ROOT/'build/three-way-half-gather'
OUT=ROOT/'docs/2026-11-18_DDGI-half-NRD-tuning';OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text());assert not (DATA/'failure.txt').exists()
assert '(Error)' not in (ROOT/'build/nrd-half-validation.log').read_text(errors='replace')
assert all(v==0 for v in info['motion_resets'].values())
for name in ['legacy','tuned']:
    assert info[name+'_stats']['finite']
    for k in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:assert info[name+'_stats'][k]==0
ablation=json.loads((ROOT/'build/nrd-half-tuning/scores.json').read_text())
refinement=json.loads((ROOT/'build/nrd-half-tuning-refine/scores.json').read_text())
params=json.loads((ROOT/'docs/2026-11-18_DDGI-half-final-gather-comparison/summary.json').read_text())['flip_parameters']
def read(p):
    a=OpenEXR.File(str(p)).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all(),p
    return np.ascontiguousarray(a)
def get(tag,ch='Reconstruct.color'):return read(DATA/(tag+'.'+ch+'.0.exr'))
target=read(ROOT/'build/accumulated-gather-comparison/half-65536.Accumulate.output.0.exr')
pt=read(OLD/'reference-65536spp.exr')
mask=np.linalg.norm(read(OLD/'pt-a-32768.Visibility.normW.0.exr'),axis=-1)>.5
def mse(a,b,valid=mask):return float(np.mean((a[valid].astype(float)-b[valid])**2))
def flip(a,b,valid=mask):
    return float(flip_evaluator.evaluate(a,b,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0][valid].mean())
summary={};timing={};rows=[];images={}
for name in ['legacy','tuned']:
    summary[name]={}
    for warm in [512,4096]:
        assert np.array_equal(mask,np.linalg.norm(get(f'{name}-{warm}-0','Visibility.normW'),axis=-1)>.5)
        stack=[get(f'{name}-{warm}-{i}') for i in range(64)];images[(name,warm)]=stack
        records=[{'mode':name,'warmup':warm,'frame':i,'mse_to_accumulate':mse(a,target),
            'hdr_flip_to_accumulate':flip(target,a),'mse_to_pt':mse(a,pt),'hdr_flip_to_pt':flip(pt,a)} for i,a in enumerate(stack)]
        rows.extend(records)
        summary[name][str(warm)]={k:float(np.mean([r[k] for r in records])) for k in ['mse_to_accumulate','hdr_flip_to_accumulate','mse_to_pt','hdr_flip_to_pt']}
        summary[name][str(warm)]['temporal_variance']=float(np.var(np.array(stack)[:,mask].astype(float),axis=0).mean())
        summary[name][str(warm)]['mean_image_mse_to_accumulate']=mse(np.mean(stack,axis=0),target)
    t=json.loads((DATA/(name+'-timing.json')).read_text())
    timing[name]={'gpu_frame_ms':t['events']['/onFrameRender/RenderGraphExe::execute()/gpu_time']['stats']['mean'],
        'samples':t['frame_count'],'passes':{s:t['events']['/onFrameRender/RenderGraphExe::execute()/'+s+'/gpu_time']['stats']['mean'] for s in ['Visibility','DDGI','Guides','Denoiser','Reconstruct','Display']}}
motion=[]
for i in info['motion_frame_indices']:
    reference=get('motion-reference-'+str(i),'Accumulate.output')
    valid=np.linalg.norm(get('motion-reference-'+str(i),'Visibility.normW'),axis=-1)>.5
    row={'frame':i}
    for name in ['legacy','tuned']:
        a=get(name+'-motion-'+str(i))
        assert np.array_equal(valid,np.linalg.norm(get(name+'-motion-'+str(i),'Visibility.normW'),axis=-1)>.5)
        row[name]={'mse_to_pt':mse(a,reference,valid),'hdr_flip_to_pt':flip(reference,a,valid)}
    motion.append(row)
delta={k:summary['tuned']['4096'][k]/summary['legacy']['4096'][k]-1 for k in summary['tuned']['4096']}
motion_means={name:{k:float(np.mean([r[name][k] for r in motion])) for k in ['mse_to_pt','hdr_flip_to_pt']} for name in ['legacy','tuned']}
result={'static':summary,'timing':timing,'relative_change':delta,'motion':motion,'motion_mean':motion_means,
    'integration_checks':ablation['integration_checks'],'ablation':ablation['variants'],'refinement':refinement['variants'],
    'capture':info,'flip_parameters':params}
(OUT/'summary.json').write_text(json.dumps(result,indent=2))
with (OUT/'metrics.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
def display(a):
    x=np.maximum(a,0)*8;x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
def panel(items,columns=2):
    canvas=Image.new('RGB',(columns*480,((len(items)+columns-1)//columns)*308),(23,26,31));draw=ImageDraw.Draw(canvas)
    for i,(label,a) in enumerate(items):
        x=i%columns*480;y=i//columns*308;draw.text((x+10,y+10),label,font=font,fill='white');canvas.paste(display(a),(x,y+38))
    return canvas
panel([('Previous NRD / half FG',images[('legacy',4096)][-1]),('Tuned NRD / half FG',images[('tuned',4096)][-1]),
    ('Half FG + Accumulate / 65536 frames',target),('PT reference / 65536 spp',pt)]).save(OUT/'comparison.png')
ani=[panel([('Previous NRD',a),('Tuned NRD',b)]) for a,b in zip(images[('legacy',4096)],images[('tuned',4096)])]
ani[0].save(OUT/'static.gif',save_all=True,append_images=ani[1:],duration=80,loop=0)
ani=[panel([('Moving / previous NRD',get('legacy-motion-'+str(i))),('Moving / tuned NRD',get('tuned-motion-'+str(i))),
    ('PT reference / 4096 spp',get('motion-reference-'+str(i),'Accumulate.output'))],3) for i in info['motion_frame_indices']]
ani[0].save(OUT/'motion.gif',save_all=True,append_images=ani[1:],duration=200,loop=0)
labels={'legacy':'原参数','tuned':'调整后'}
table=''.join(f"<tr><td>{labels[k]}</td><td>{v['4096']['mse_to_accumulate']:.7g}</td><td>{v['4096']['hdr_flip_to_accumulate']:.5f}</td><td>{v['4096']['mse_to_pt']:.7g}</td><td>{v['4096']['hdr_flip_to_pt']:.5f}</td><td>{v['4096']['temporal_variance']:.7g}</td><td>{timing[k]['gpu_frame_ms']:.4f}</td></tr>" for k,v in summary.items())
ablation_rows=''.join(f"<tr><td>{k}</td><td>{v['mse_to_accumulate']:.7g}</td><td>{v['temporal_variance']:.7g}</td><td><code>{json.dumps(v['parameters'])}</code></td></tr>" for k,v in ablation['variants'].items())
check=ablation['integration_checks']
text=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>半分辨率 FG + NRD：接入检查与调参</title>
<style>body{{max-width:1480px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#ddd;background:#171a20}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:8px 12px}}table{{border-collapse:collapse}}a{{color:#8dc7ff}}code{{overflow-wrap:anywhere}}</style>
<h1>半分辨率 final gather + NRD：减小滤波偏差</h1>
<p>当前主要问题是过大的空间滤波范围，不是漏乘 albedo 或亮度截断。做了 12 组消融、7 组细调后，选出参数并以 64 帧窗口及更长预热复测。4096 帧预热后，相对收敛半分辨率 FG 的 MSE 改变 {delta['mse_to_accumulate']:+.1%}，HDR-FLIP 改变 {delta['hdr_flip_to_accumulate']:+.1%}，时间方差改变 {delta['temporal_variance']:+.1%}。</p>
<img src="comparison.png"><table><tr><th>设置</th><th>MSE / Accumulate ↓</th><th>HDR-FLIP / Accumulate ↓</th><th>MSE / PT ↓</th><th>HDR-FLIP / PT ↓</th><th>时间方差 ↓</th><th>GPU 帧 ms</th></tr>{table}</table>
<p>Accumulate 目标为同一半分辨率采样与重建流程累积 65536 帧后的结果；PT 为未降噪的 65536 spp。均在相同 Lambert Cornell、当前点光源公式、固定相机和 480×270 输出下测试。每张 NRD 输出只用当前有限历史，没有额外 Accumulate。</p>
<h2>接入检查与修正</h2><ul>
<li>NRD 关闭后，与直接重建同帧原始信号的相对 L1 差异为 {check['bypass_relative_l1']:.4%}，符合 FP16 旁路量化；未发现漏乘反射率或重复加入直接光。</li>
<li>半分辨率 depth/motion 与其来源像素精确一致。法线采用 NRD 对应的 oct 编码，解码后相对 GBuffer 法线最大分量误差 {check['decoded_guide_normal_max_error']:.4g}；来自编码量化。Lambert 镜面信号为零，hit distance 源码写入实际 x→y 距离，RELAX 不需要 REBLUR 的归一化。</li>
<li>审计帧去调制漫反射输入最大值 {check['demodulated_diffuse_max']:.4f}，远低于 maxIntensity=10000，不是该截断阈值造成的大幅暗化。</li>
<li>发现固定采样相位不匹配：FG/导向来自完整分辨率像素 (2x,2y)，比半分辨率 texel 中心偏 (-0.25,-0.25) 个像素。新增 NRD inputSampleOffset，调整当前/上一帧投影，使 NRD 的位置重建与输入对齐。只修正它没有降低静态主误差，故不把主要改善归功于此修正。</li></ul>
<h2>为什么原参数偏差大？</h2><p>原设置 A-trous 6 轮，后几轮的采样间距逐渐变大；同样的像素尺度在半分辨率下覆盖更多最终像素。深度和法线导向无法区分同一平面上的间接阴影和亮度梯度，所以接触阴影被平滑。SDK 的大步长轮次还采用随帧变化的采样偏移，可能增加输出波动。单独减少到 3 轮，与 Accumulate 的 MSE 从 {ablation['variants']['baseline']['mse_to_accumulate']:.7g} 降至 {ablation['variants']['atrous3']['mse_to_accumulate']:.7g}，是直接消融证据。</p>
<p>原来的 diffusePrepassBlurRadius=16 也偏大；该预滤波的半径/权重依赖随机 FG 命中距离，不能视为无偏平均。但单独关闭预滤波反而变差，说明需要与后续 A-trous 和历史参数一起调整。快速历史只有 2 帧，限幅参考较噪；增加到 8 帧并放宽 sigma，有助于减少对稳定历史的过度限幅。各项作用不能简单相加。</p>
<table><tr><th>参数</th><th>原值</th><th>新值</th></tr>
<tr><td>diffusePrepassBlurRadius</td><td>16</td><td>0</td></tr><tr><td>atrousIterationNum</td><td>6</td><td>2</td></tr>
<tr><td>diffuseMaxAccumulatedFrameNum</td><td>31</td><td>31</td></tr><tr><td>diffuseMaxFastAccumulatedFrameNum</td><td>2</td><td>8</td></tr>
<tr><td>historyClampingColorBoxSigmaScale</td><td>2</td><td>3</td></tr><tr><td>inputSampleOffset</td><td>(0,0)</td><td>(-0.25,-0.25)</td></tr></table>
<h2>稳定性与移动镜头</h2><img src="static.gif"><img src="motion.gif">
<p>两种设置都先更新 probe 2048 帧，重置 NRD 后分别在预热 512 和 4096 帧采集 64 帧；期间 probe 始终更新。调整后在 512 / 4096 帧窗口的目标 MSE 分别为 {summary['tuned']['512']['mse_to_accumulate']:.7g} / {summary['tuned']['4096']['mse_to_accumulate']:.7g}。主表使用未参与最初 32 帧筛选的长预热窗口。</p>
<p>连续横移 32 帧，每帧 0.01m，抽取 8 个机位；两种设置的 NRD 历史重置数都为 0。运动段相对各机位 PT 4096 spp 的平均 MSE 为 {motion_means['legacy']['mse_to_pt']:.7g} / {motion_means['tuned']['mse_to_pt']:.7g}，HDR-FLIP 为 {motion_means['legacy']['hdr_flip_to_pt']:.5f} / {motion_means['tuned']['hdr_flip_to_pt']:.5f}。这只是短程移动验证，不是动态物体、快速转身或镜面场景的全面质量保证。</p>
<p>RTX 5070 / D3D12，计时各 255 个区间，包含 GBuffer、probe 更新、FG、导向准备、NRD、上采样合成和色调映射。所有指标使用线性 HDR 完整光照及可见表面 mask；HDR-FLIP 使用同一固定曝光范围。仍有有限采样噪声和滤波偏差，不能等同于长期累积参考。</p>
<h2>已应用的开关</h2><p>Run-HalfGather.cmd / 启动器 DDGIHalf 默认使用新参数。scripts/nrd_half_settings.py 保存 LEGACY / TUNED；调用 render_graph_DDGIHalfGatherNRD(preset='legacy') 可还原旧设置。仅修改半分辨率实验图的预设，其他 NRD 图保留原参数。当前调参针对不透明 Lambert 漫反射场景；共享 A-trous 参数对镜面信号的影响尚未量化。</p>
<details><summary>第一轮消融明细</summary><table><tr><th>实验</th><th>MSE / Accumulate</th><th>时间方差</th><th>相对旧参数的修改</th></tr>{ablation_rows}</table></details>
<p>复现脚本：tests/ddgi/nrd_half_tuning.py、score_nrd_half_tuning.py、nrd_half_validation.py、score_nrd_half_validation.py。原始捕获与完整参数位于 build/nrd-half-tuning、build/nrd-half-tuning-refine、build/nrd-half-validation。<a href="summary.json">完整结果</a> · <a href="metrics.csv">逐帧指标</a></p></html>'''
(OUT/'report.html').write_text(text,encoding='utf-8')
sources=['Source/RenderPasses/NRDPass/NRDPass.cpp','Source/RenderPasses/NRDPass/NRDPass.h','scripts/DDGIHalfGatherNRD.py','scripts/nrd_half_settings.py',
    'tests/ddgi/nrd_half_tuning.py','tests/ddgi/score_nrd_half_tuning.py','tests/ddgi/nrd_half_validation.py','tests/ddgi/score_nrd_half_validation.py']
(OUT/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},indent=2))
print(json.dumps({'static':summary,'change':delta,'motion_mean':motion_means,'timing':timing,'report':str(OUT/'report.html')},indent=2))
