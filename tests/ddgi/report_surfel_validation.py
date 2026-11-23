"""Reproducible linear HDR/FLIP comparison of the independent surfel path."""
from pathlib import Path
import sys,json,hashlib,subprocess
R=Path(__file__).resolve().parents[2]
O=R/'docs/2026-11-22_独立SurfelGI验证与对比';O.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'build/final-gather-python'))
sys.path.append(str(R/'build/convergence-python'))
import numpy as np,OpenEXR,flip_evaluator
from PIL import Image,ImageDraw,ImageFont
from matplotlib import colormaps
import matplotlib.pyplot as plt

def read(p):
    a=OpenEXR.File(str(p)).channels()['RGB'].pixels
    assert np.isfinite(a).all(),str(p)
    return a

def display(a,ev):
    x=np.maximum(a*2**ev,0)
    x=np.clip(x*(2.51*x+.03)/(x*(2.43*x+.59)+.14),0,1)
    x=np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
    return Image.fromarray(np.uint8(np.clip(x*255+.5,0,255)))

summary={};sections=[]
for scene in ['CornellLambert','SponzaLambert']:
    D=R/('build/surfel-validation-'+scene)
    if not (D/'complete.json').exists():continue
    info=json.loads((D/'complete.json').read_text())
    assert not (D/'failure.txt').exists()
    refpath=D/'pt-8192.Accumulate.output.0.exr'
    if not refpath.exists():refpath=R/'build/sponza-sun50-20261120/pt-8192.Accumulate.output.0.exr'
    ref=read(refpath);a=read(D/'surfel-8192.Accumulate.output.0.exr')
    norm=read(D/'surfel-8192.Visibility.normW.0.exr')
    pos=read(D/'surfel-8192.Visibility.posW.0.exr')
    mask=np.linalg.norm(norm,axis=-1)>.5
    if refpath.parent==D:
        assert np.array_equal(norm,read(D/'pt-8192.Visibility.normW.0.exr'))
        assert np.array_equal(pos,read(D/'pt-8192.Visibility.posW.0.exr'))
    else:
        assert np.array_equal(norm,read(R/'build/sponza-sun50-20261120/pt-512.Visibility.normW.0.exr'))
        assert np.array_equal(pos,read(R/'build/sponza-sharc-official-20261122/worldcache-16384.Visibility.posW.0.exr'))
    ev=float(-np.log2(np.percentile(ref[mask]@np.array([.2126,.7152,.0722]),99)))
    _,_,params=flip_evaluator.evaluate(ref,ref,'HDR',applyMagma=False,parameters={'ppd':67,'tonemapper':'ACES'})
    f=flip_evaluator.evaluate(ref,a,'HDR',applyMagma=False,parameters=params.copy())[0][:,:,0]
    mse=float(np.mean((a[mask].astype(np.float64)-ref[mask])**2));flip=float(f[mask].mean())
    t=json.loads((D/'surfel-timing.json').read_text())
    prefix='/onFrameRender/RenderGraphExe::execute()'
    ms=t['events'][prefix+'/gpu_time']['stats']['mean']
    times={k[len(prefix)+1:-9]:v['stats']['mean'] for k,v in t['events'].items() if k.startswith(prefix+'/') and k.endswith('/gpu_time')}
    curves={};stability={}
    for n in [512,1024,2048,4096,8192]:
        x=read(D/('surfel-'+str(n)+'.Accumulate.output.0.exr'))
        curves[n]=float(np.mean((x[mask].astype(np.float64)-ref[mask])**2))
    for name in ['pt','surfel']:
        B=refpath.parent if name=='pt' else D
        x=read(B/(name+'-8192.Accumulate.output.0.exr'));y=read(B/(name+'-4096.Accumulate.output.0.exr'))
        stability[name]={'doubling_relative_rms':float(np.sqrt(np.mean((x[mask].astype(np.float64)-y[mask])**2)/max(1e-20,np.mean(x[mask].astype(np.float64)**2))))}
    summary[scene]={'mse':mse,'hdr_flip':flip,'graph_ms':ms,'passes_ms':times,'stability':stability,'mse_curve':curves,'exposure_ev':ev,'flip_parameters':params,'configuration':info,'pt_reference':str(refpath),'pt_spp':65536,'pt_sha256':hashlib.sha256(refpath.read_bytes()).hexdigest()}
    for name,x in [('surfel',a),('pt',ref)]:display(x,ev).save(O/(scene+'-'+name+'.png'))
    heat=np.uint8(colormaps['magma'](f)[:,:,:3]*255);heat[~mask]=[23,26,31]
    Image.fromarray(heat).save(O/(scene+'-flip.png'))
    panel=Image.new('RGB',(1920,580),(23,26,31));draw=ImageDraw.Draw(panel)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
    for j,name in enumerate(['surfel','pt']):
        panel.paste(Image.open(O/(scene+'-'+name+'.png')).resize((960,540)),(j*960,40))
        draw.text((j*960+12,5),'Surfel GI + Accumulate' if name=='surfel' else 'PT Reference / 65536 spp',font=font,fill='white')
    panel.save(O/(scene+'-comparison.png'))
    fig,ax=plt.subplots(figsize=(8,4));ax.loglog(list(curves),list(curves.values()),'o-')
    ax.set(xlabel='Accumulated frames after 2048 warmup frames',ylabel='Linear HDR RGB MSE vs PT',title=scene)
    ax.grid(True,alpha=.3);fig.tight_layout();fig.savefig(O/(scene+'-convergence.png'));plt.close(fig)
    sections.append(f'<h2>{scene}</h2><p>MSE：{mse:.8g}；HDR-FLIP：{flip:.5f}；完整渲染图 GPU：{ms:.3f} ms。</p><p>4096→8192 帧累积变化（相对 RGB RMS）：{', '.join(k+' '+format(v['doubling_relative_rms']*100,'.3f')+'%' for k,v in stability.items())}。变化衡量稳定性，不等于相对 PT 的正确性。</p><img src="{scene}-comparison.png"><p><a href="{scene}-surfel.png">Surfel 1080p</a> · <a href="{scene}-pt.png">PT 1080p</a></p><img width="800" src="{scene}-convergence.png"><h3>HDR-FLIP 热力图</h3><p>Magma [0,1]，黑紫误差低、橙黄误差高；背景为 mask 外，不是相似度百分比。</p><img src="{scene}-flip.png"><img width="520" src="flip-legend.png">')

font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20)
legend=Image.new('RGB',(540,64),(23,26,31))
legend.paste(Image.fromarray(np.uint8(colormaps['magma'](np.linspace(0,1,500))[None,:,:3]*255)).resize((500,20)),(10,6))
draw=ImageDraw.Draw(legend)
for i in range(6):draw.text((10+i*100,32),f'{i/5:.1f}',font=font,fill='white')
legend.save(O/'flip-legend.png')
unit=R/'build/surfel-unit'
if (unit/'unit.Accumulate.output.0.exr').exists():
    assert not (unit/'failure.txt').exists()
    u=read(unit/'unit.Accumulate.output.0.exr');mask=np.linalg.norm(read(unit/'unit.Visibility.normW.0.exr'),axis=-1)>.5
    mean=float(u[mask].mean());med=float(np.median(u[mask]));assert abs(mean-.5)<.02 and abs(med-.5)<.01
    summary['unit_environment']={'expected':.5,'mean':mean,'median':med,'passed':True}
summary['hardware']=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'],text=True).strip()
summary['preview_validation']=json.loads((R/'build/surfel-preview-check/complete.json').read_text())
assert not (R/'build/surfel-preview-check/failure.txt').exists()
observations = '<p>Cornell 的整体能量与颜色接近 PT，仍有局部插值边界误差。Sponza 的间接光区域、拱顶、布帘细节和柱脚附近差异更明显；这是当前实验版本的局限，不能据此认为所有 Surfel GI 都有相同表现。</p>'
if 'SponzaLambert' in summary:
    t=summary['SponzaLambert']['passes_ms']
    observations += f"<p>Sponza 主要耗时：屏幕 surfel 查询 {t['Surfel/Surfel Evaluation Pass']:.3f} ms，缓存射线追踪 {t['Surfel/Surfel RayTrace Pass']:.3f} ms，表面生成 {t['Surfel/Surfel Generation Pass']:.3f} ms。当前逐像素遍历格子候选列表是主要优化目标，尚未实现分层或 tile 级候选筛选。</p>"
summary['source_hashes']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (R/'Source/RenderPasses/Surfel').rglob('*') if p.is_file()}
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
html='''<!doctype html><meta charset="utf-8"><title>独立 SurfelGI 验证与对比</title><style>body{background:#171a1f;color:#eee;font:17px/1.7 sans-serif;max-width:1600px;margin:30px auto;padding:0 24px}img{max-width:100%}a{color:#9cf}</style>
<h1>独立 SurfelGI 验证与对比</h1>
<p>基于 W298/SurfelGI 的移植与修正版本，不代表 EA 官方 GIBS。原项目 MIT 许可保留在插件目录。</p>
<p>Pass 组织：GBufferRT → Surfel（网格重建、路径追踪、缓存积分、生成、屏幕插值）→ Lighting（直接光+材质×缓存间接光）→ Accumulate → Display。没有额外屏幕 final gather、NRD 或 ReSTIR。缓存预热 2048 帧，再清空 Accumulate 并累积 8192 帧。GPU 耗时取稳定期 256 帧平均，包含持续缓存更新和全部显示流程。</p>
<p>CornellLambert 使用当前场景配置。SponzaLambert 使用默认方向光 RGB 50、点光关闭，相机 (-9,1.6,0) 看向 (8,2.5,0)；复用相同场景的 65536 spp PT，已逐像素校验位置/法线与现有实验一致。指标在可见表面 mask 上评估线性 HDR，HDR-FLIP 使用统一参考曝光范围、ACES、PPD 67；显示曝光仅由各场景 PT 决定。</p>
<p>修正：均匀半球 PDF 与 E/π 归一化、多灯索引、字节地址、未初始化结果、环境方向、alpha test、场景材质污染、固定网格清理、可见 surfel 寿命、生成组同步、积分历史读写、错误的 roulette/cache 组合。同时修正深度矩零初始化造成的错误遮挡、深度方向整数除法、空闲计数下溢，并为可见表面保留半池分配容量。原有不正确的 ray guiding 禁用。生成采用每 tile 每帧随机一个候选，无线程组同步；表面缓存插值保留原方法。性能参数改为有界配置，并自动估算网格范围。</p>
''' + '<p>测试硬件：'+summary['hardware']+'；1920×1080，D3D12。</p><p>单位环境验证（Lambert 反照率 0.5）：'+str(summary.get('unit_environment',{}))+'</p>' + ''.join(sections)+observations+'<p>配置：容量 32768，64³ 相机中心网格，targetArea 2048，可见 surfel 每帧 4–16 条起始路径（总容量 524288）；3 跳后尝试接入缓存，最多 6 跳；后台 surfel 跳数加倍。默认关闭邻居 irradiance sharing 和 ray guiding。起始路径数不等于 BVH 总射线数。</p><p>限制：当前是漫反射 GI 实验路径；缓存插值、深度近似、有限覆盖和多尺度估计器仍会引入偏差。Accumulate 稳定不代表与 PT 完全一致。未实现镜面/透射 GI、无限范围分级缓存和 GIBS 的完整回退机制。</p><p><a href="summary.json">完整数据、配置与代码指纹</a></p>'
(O/'report.html').write_text(html,encoding='utf-8')
print(json.dumps({k:{n:v[n] for n in ['mse','hdr_flip','graph_ms','stability']} for k,v in summary.items() if k in ['CornellLambert','SponzaLambert']},indent=2))
