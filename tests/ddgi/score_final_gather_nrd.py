"""Score paired raw/NRD outputs; never average the displayed denoised frames."""
from pathlib import Path
import sys,json,csv,hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build/final-gather-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
DATA=ROOT/'build/final-gather-nrd';OLD=ROOT/'build/final-gather-comparison'
OUT=ROOT/'docs/2026-11-17_DDGI-final-gather-NRD';OUT.mkdir(exist_ok=True)
info=json.loads((DATA/'complete.json').read_text())
assert not (DATA/'failure.txt').exists()
assert info['motion_resets']==0 and info['toggle_reset_count']>=1
assert '(Error)' not in (ROOT/'build/final-gather-nrd.log').read_text(errors='replace')
for key in ['lambert_stats','native_stats']:
    assert info[key]['finite']
    for counter in ['rejectedMaterialSamples','rejectedDirectSamples','rejectedHistorySamples','rejectedRaySamples']:assert info[key][counter]==0
params=json.loads((ROOT/'docs/2026-11-17_DDGI-final-gather-Lambert/summary.json').read_text())['flip_parameters']
def read(tag,channel,folder=DATA):
    a=OpenEXR.File(str(folder/(tag+'.'+channel+'.0.exr'))).channels()['RGB'].pixels.astype(np.float32)
    assert np.isfinite(a).all()
    return np.ascontiguousarray(a)
for path in DATA.glob('*.exr'):
    for ch in OpenEXR.File(str(path)).channels().values():assert np.isfinite(ch.pixels).all(),path
ref=read('reference','Accumulate.output',OLD)-read('direct','DDGI.color',OLD)
mask=np.linalg.norm(read('reference','Visibility.normW',OLD),axis=-1)>.5
assert np.array_equal(mask,np.linalg.norm(read('static-160','Visibility.normW'),axis=-1)>.5)
def denoised(tag):return np.maximum(read(tag,'Compose.output')-read(tag,'DDGI.unfilteredColor'),0)
def score(ref,a,mask):
    e=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    return {'mse':float(np.mean((ref[mask].astype(float)-a[mask])**2)),
            'hdr_flip':float(e[mask].mean()),'mean_rgb':float(a[mask].mean())}
rows=[];raws=[];dens=[]
for i in range(129,161):
    tag='static-'+str(i);raw=read(tag,'DDGI.indirect');den=denoised(tag)
    raws.append(raw);dens.append(den)
    for name,a in [('Raw',raw),('NRD',den)]:rows.append({'frame':i,'mode':name,**score(ref,a,mask)})
summary={}
for name,images in [('Raw',raws),('NRD',dens)]:
    selected=[row for row in rows if row['mode']==name]
    summary[name]={k:float(np.mean([row[k] for row in selected])) for k in ['mse','hdr_flip','mean_rgb']}
    summary[name]['temporal_rgb_variance']=float(np.var(np.array(images)[:,mask].astype(float),axis=0).mean())
checks={}
for tag in ['off','off-after-motion','native-off','legacy']:
    raw=read(tag,'DDGI.color');composed=read(tag,'Compose.output')
    rel=float(np.abs(raw-composed).sum()/max(raw.sum(),1e-8));assert rel<.001,(tag,rel)
    checks[tag]={'relative_l1':rel,'max_abs':float(np.abs(raw-composed).max())}
assert read('static-160','DDGI.gatherSpecular').max()==0
assert read('native-on','DDGI.gatherSpecular').max()>1e-5
assert read('static-160','DDGI.diffuseRadianceHitDist').max()>0
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
def display(a):
    x=np.maximum(a,0)*8;x=np.clip((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(x*255+.5))
def panel(items):
    canvas=Image.new('RGB',(480*len(items),308),(23,26,31));d=ImageDraw.Draw(canvas)
    for i,(label,a) in enumerate(items):
        d.text((480*i+10,10),label,font=font,fill='white');canvas.paste(display(a),(480*i,38))
    return canvas
panel([('Raw final gather / 1 spp',raws[-1]),('NRD / 1 spp input',dens[-1]),('PT / 32768 spp',ref)]).save(OUT/'comparison.png')
panel([('NRD / first frame',denoised('static-1')),('NRD / frame 8',denoised('static-8')),('NRD / frame 32',denoised('static-32'))]).save(OUT/'startup.png')
panel([('Native BRDF / raw 1 spp',read('native-on','DDGI.indirect')),('Native BRDF / NRD',denoised('native-on'))]).save(OUT/'native.png')
# Fixed-camera animation of paired consecutive frames: reveals temporal noise.
animation=[panel([('Static / raw 1 spp',a),('Static / NRD',b)]) for a,b in zip(raws,dens)]
animation[0].save(OUT/'static.gif',save_all=True,append_images=animation[1:],duration=100,loop=0)
motion=[];animation=[]
for i in range(8):
    tag='motion-'+str(i);a=read(tag,'DDGI.indirect');b=denoised(tag)
    mask_i=np.linalg.norm(read('motion-reference-'+str(i),'Visibility.normW',OLD),axis=-1)>.5
    direct=read('motion-baseline-'+str(i),'DDGI.color',OLD)-read('motion-baseline-'+str(i),'DDGI.indirect',OLD)
    reference=np.maximum(read('motion-reference-'+str(i),'Accumulate.output',OLD)-direct,0)
    motion.append({'frame':i,'Raw':score(reference,a,mask_i),'NRD':score(reference,b,mask_i)})
    animation.append(panel([('Moving / raw 1 spp',a),('Moving / NRD',b),('PT / 512 spp',reference)]))
animation[0].save(OUT/'motion.gif',save_all=True,append_images=animation[1:],duration=200,loop=0)
timing={}
for mode in ['off','on']:
    t=json.loads((DATA/(mode+'-timing.json')).read_text());timing[mode]={}
    for stage in ['DDGI','Denoiser','Compose']:
        key='/onFrameRender/RenderGraphExe::execute()/'+stage+'/gpu_time'
        timing[mode][stage]=t['events'][key]['stats']['mean']
    timing[mode]['sum']=sum(timing[mode].values());timing[mode]['samples']=t['frame_count']
result={'static':summary,'motion':motion,'timing_ms':timing,'bypass_checks':checks,'capture':info,
        'reference_indirect_mean_rgb':float(ref[mask].mean()),'flip_parameters':params,
        'mean_change_from_raw':summary['NRD']['mean_rgb']/summary['Raw']['mean_rgb']-1}
(OUT/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
with (OUT/'metrics.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
rowhtml=''.join(f"<tr><td>{name}</td><td>{v['mse']:.6g}</td><td>{v['hdr_flip']:.4f}</td><td>{v['temporal_rgb_variance']:.6g}</td><td>{v['mean_rgb']:.5f}</td></tr>" for name,v in summary.items())
text=fr"""<!doctype html><html lang="zh"><meta charset="utf-8"><title>Final Gather + NRD 实验</title>
<style>body{{max-width:1480px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#ddd;background:#171a20}}img{{max-width:100%}}td,th{{border:1px solid #555;padding:8px 16px}}table{{border-collapse:collapse}}a{{color:#8dc7ff}}</style>
<h1>DDGI Final Gather + NRD：可选降噪实验</h1>
<p>已接入现有 NRD 的 RelaxDiffuseSpecular。每帧仍是全分辨率、每个有效 lobe 最多一根射线；默认关闭普通 AccumulatePass。下图中央是第 160 帧的单张 NRD 输出，没有再对输出平均。镜头静止时，NRD 的空间滤波与有限历史融合能显著减少噪点。</p>
<img src="comparison.png"><h2>同帧配对评测</h2>
<table><tr><th>输出</th><th>间接光 MSE</th><th>HDR-FLIP</th><th>固定像素时间方差</th><th>平均 RGB</th></tr>{rowhtml}</table>
<p>预热 NRD 128 帧后，连续 32 帧逐帧对照同一 PT 参考，再对指标取平均。时间方差为固定可见表面像素、RGB 通道上的总体方差平均。不能只凭低方差判断正确：强平滑也会降低方差。NRD 平均亮度相对原始输入改变 {result['mean_change_from_raw']:.1%}，并出现接触阴影变软，表明滤波引入了偏差；不是无损恢复。</p>
<img src="static.gif"><h2>启动与运动</h2><img src="startup.png"><img src="motion.gif">
<p>运动使用此前相同的 8 个机位，每帧向右平移 0.04m；参考每机位 512 spp。NRD 在运动期间历史重置次数为 {info['motion_resets']}，表示连续历史参与重投影。关闭后重新开启触发 {info['toggle_reset_count']} 次清空，避免读取停用期间的过期历史。这里只验证短程平移，不据此保证快速转身、动态物体、镜面反射或大范围遮挡变化都无拖影。</p>
<h2>镜面信号检查</h2><img src="native.png"><p>同帧 StandardMaterial 的漫反射与镜面反射合成，镜面输入非零；Lambert 场景镜面输入严格为零。原生材质图用于检查两个通道都能接入，不是有独立镜面 PT 真值的量化评测。理想镜面/透射没有采用 PathTracer 的专用 delta 路径处理。</p>
<h2>耗时</h2><table><tr><th>开关</th><th>DDGI ms</th><th>NRD ms</th><th>合成 ms</th><th>三者合计 ms</th></tr>
<tr><td>关闭</td><td>{timing['off']['DDGI']:.4f}</td><td>{timing['off']['Denoiser']:.4f}</td><td>{timing['off']['Compose']:.4f}</td><td>{timing['off']['sum']:.4f}</td></tr>
<tr><td>开启</td><td>{timing['on']['DDGI']:.4f}</td><td>{timing['on']['Denoiser']:.4f}</td><td>{timing['on']['Compose']:.4f}</td><td>{timing['on']['sum']:.4f}</td></tr></table>
<p>RTX 5070、D3D12、480×270，每种模式 127 个完整 GPU 时间戳区间；计时开启探针更新，两种模式相同诊断输出；排除 GBuffer、显示和文件写入。NRD 关闭后仍有半精度旁路拷贝与合成开销。图像评测则先更新探针 2048 帧再冻结，避免缓存变化干扰噪声测量。</p>
<h2>实现与开关</h2><p>运行项目根目录 Run-FinalGather.cmd，加载场景，在 Denoiser 面板切换 Enabled。脚本：<code>m.activeGraph.getPass("Denoiser").set_properties({{"enabled": False}})</code>；设置 True 恢复。Accumulate 默认禁用，可独立开启做静态实验；本报告全程关闭。</p>
<p>DDGI 新增 diffuseRadianceHitDist、specularRadianceHitDist、diffuseReflectance、specularReflectance、unfilteredColor。漫反射除以 albedo、镜面除以近似 GGX 预积分反射率；NRD 后乘回并加直接光/自发光/背景。不存在的 lobe 反射率为零；有效 lobe 的去调制分母下限 1e-4。距离是 x→y 的真实世界空间距离，miss 为有限 FP16 最大值 65504，未采样为 0。导向来自同一 GBuffer 的世界空间运动、线性深度、法线和粗糙度。RELAX maxIntensity=10000，使用项目现有默认滤波参数。</p>
<p>原始 DDGI.color、gatherDiffuse、gatherSpecular 保留为未降噪输出。关闭 NRD 后 Compose.output 相对原始 color 的 L1 差异小于 0.1%，差异来自现有 NRD 旁路的 FP16 格式。切回原始 probe 查询时走 unfilteredColor，检查结果完全一致。所有捕获 EXR 都经过有限值检查，材质/光照诊断无拒绝样本。</p>
<h2>条件与局限</h2><p>沿用上一份 Lambert Cornell 点光源、相机、probe 9×9×9 与偏移配置。PT 参考为独立保存的 32768 spp，最多 19 surface bounces；不是无限精度真值。NRD 只处理 final gather，未处理直接照明采样噪声；无镜面递归、无 reservoir 重采样。显示使用共同 +3 EV、ACES fitted、sRGB；HDR-FLIP 使用固定曝光区间 {params['startExposure']:.3f} 到 {params['stopExposure']:.3f} EV、PPD 67。</p>
<h2>复现</h2><pre>build\windows-vs2022\bin\Release\Mogwai.exe --device-type d3d12 --headless --deferred --script tests/ddgi/final_gather_nrd.py --width 480 --height 270
python tests/ddgi/score_final_gather_nrd.py</pre><p>需要先有 tests/ddgi/final_gather_compare.py 生成的场景配置和 PT 参考。原始捕获与计时位于 build/final-gather-nrd。评分依赖与上一份报告一致。</p>
<p><a href="summary.json">结构化结果</a> · <a href="metrics.csv">逐帧指标</a> · <a href="../2026-11-17_DDGI-final-gather-Lambert/report.html">未降噪累积实验</a></p></html>"""
(OUT/'report.html').write_text(text,encoding='utf-8')
paths=['Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.cpp','Source/RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang','scripts/RTXGIDDGIFinalGather.py','tests/ddgi/final_gather_nrd.py','tests/ddgi/score_final_gather_nrd.py']
(OUT/'source-hashes.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},indent=2))
print(json.dumps({'static':summary,'timing_ms':timing,'mean_change':result['mean_change_from_raw'],'out':str(OUT)},indent=2))
