"""Run isolated sparse GI validation. Decodes captures only after the GPU process exits."""
from pathlib import Path
import argparse, os, shutil, subprocess, sys, json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from probe_snapshot import read_image, png, write_json

def analyze(out):
    os.environ['PROBE_SNAPSHOT_RUNTIME']=str(out/'runtime')
    images={}; metrics={}
    for d in sorted(out.iterdir()):
        if not d.is_dir() or d.name=='runtime':continue
        images[d.name]={}
        for label,output in [('hdr','Probes.color'),('display','Display.dst'),('info','Probes.samplingInfo')]:
            files=list(d.glob('frame.'+output+'.*'))
            if not files:continue
            assert len(files)==1
            w,h,v=read_image(files[0]);a=np.array(v,dtype=np.float32).reshape(h,w,3)
            assert np.isfinite(a).all(),(d,label)
            if d.name.startswith('odd-'):assert (w,h)==(1279,719),(d,w,h)
            images[d.name][label]=a
            if label=='display':png(d/'display.png',a)
        if 'info' in images[d.name]:
            a=images[d.name]['info']; surface=float(a[:,:,2].sum()); fallback=float(a[:,:,1].sum())
            if d.name!='unbaked':assert surface>0,(d,'missing sampling diagnostics')
            else:assert surface==0,(d,'unbaked sparse data')
            metrics[d.name]={'surface_pixels':surface,'exact_fallback_fraction':fallback/max(surface,1)}
    for view in ('wall','corner','room','fixture','open'):
        for backend in ('moments','rayTraced'):
            base=images[f'{view}-{backend}-0']
            for stride in (2,4,8):
                key=f'{view}-{backend}-{stride}';a=images[key];delta=abs(a['hdr']-base['hdr']);display=abs(a['display']-base['display'])
                metrics[key].update(hdr_mae=float(delta.mean()),hdr_max=float(delta.max()),display_mae=float(display.mean()),
                    display_p99=float(np.quantile(display,.99)),display_max=float(display.max()),
                    pixels_over_5_percent=float((display.max(axis=2)>.05).mean()))
                canvas=Image.new('RGB',(1280,750),(20,20,20));draw=ImageDraw.Draw(canvas)
                font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17)
                for i,(title,img) in enumerate([('Every pixel',base['display']),(f'Sparse {stride} x {stride}',a['display']),('Difference x 8',np.clip(display*8,0,1)),('Red: reused / green: exact fallback',a['info']*np.array([1,1,0]))]):
                    x,y=(i%2)*640,(i//2)*375;draw.text((x+6,y+2),title,font=font,fill='white')
                    canvas.paste(Image.fromarray(np.uint8(np.clip(img,0,1)*255)).resize((640,350)),(x,y+25))
                canvas.save(out/(key+'-comparison.png'))
    exact=abs(images['restored']['hdr']-images['wall-moments-0']['hdr']).max();assert exact==0,exact
    reference=np.fromfile(ROOT/'build/probe-leak-validation/first-new/hdr.f32',dtype='<f4').reshape(720,1280,3)
    same=abs(reference-images['wall-moments-0']['hdr']).max();assert same==0,same
    metrics['roundtrip_max']=float(exact);metrics['previous_version_max']=float(same)
    timing={}
    for f in sorted(out.glob('timing-*.json')):
        capture=json.loads(f.read_text());key=f.stem.rsplit('-',1)[0]
        lanes=timing.setdefault(key,{})
        for name,lane in capture['events'].items():
            if name.endswith('/gpu_time'):
                records=np.array(lane['records'])[5:]
                if records.size:lanes.setdefault(name,[]).append(float(np.median(records)))
    write_json(out/'quality.json',metrics);write_json(out/'timing-summary.json',timing)
    print(json.dumps(timing,indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',default='build/probe-sparse-validation');ap.add_argument('--analyze-only',action='store_true');a=ap.parse_args()
    out=(ROOT/a.output).resolve()
    if a.analyze_only:analyze(out);return
    out.mkdir(exist_ok=False);runtime=out/'runtime';src=ROOT/'build/windows-vs2022/bin/Release'
    def link(s,d):
        if 'plugins' in Path(s).relative_to(src).parts:shutil.copy2(s,d)
        else:
            try:os.link(s,d)
            except OSError:shutil.copy2(s,d)
    shutil.copytree(src,runtime,copy_function=link,ignore=shutil.ignore_patterns('.shadercache','shaders'))
    shutil.copytree(src/'shaders',runtime/'shaders')
    for f in (ROOT/'Source/RenderPasses/TraditionalProbeGI').glob('*.slang'):shutil.copy2(f,runtime/'shaders/RenderPasses/TraditionalProbeGI'/f.name)
    shutil.copy2(ROOT/'build/probe-sparse-staging/TraditionalProbeGI.dll',runtime/'plugins/TraditionalProbeGI.dll')
    env=os.environ.copy();env.update(PROBE_SPARSE_OUTPUT=str(out),PROBE_SNAPSHOT_RUNTIME=str(runtime),FALCOR_MEDIA_FOLDERS='F:/media')
    with (out/'console.log').open('w') as log:
        r=subprocess.run([str(runtime/'Mogwai.exe'),'--headless','--deferred','--device-type','d3d12','--width','1280','--height','720',
            '--script',str(ROOT/'tests/probe_gi/sparse_sampling_validation.py'),'--logfile',str(out/'Mogwai.log')],cwd=runtime,env=env,
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=900)
    if r.returncode:raise RuntimeError('GPU validation failed; see '+str(out/'failure.txt'))
    analyze(out)
if __name__=='__main__':main()
