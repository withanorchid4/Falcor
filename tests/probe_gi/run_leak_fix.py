"""Host for isolated leak-preset regression and HDR/PNG comparisons."""
from pathlib import Path
import json, os, shutil, subprocess, sys
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from probe_snapshot import read_image,png,write_json,verify
def main():
    out=ROOT/'build/probe-leak-validation';out.mkdir(exist_ok=False);runtime=out/'runtime';src=ROOT/'build/windows-vs2022/bin/Release'
    def link(a,b):
        if 'plugins' in Path(a).relative_to(src).parts:shutil.copy2(a,b)
        else:
            try:os.link(a,b)
            except OSError:shutil.copy2(a,b)
    shutil.copytree(src,runtime,copy_function=link,ignore=shutil.ignore_patterns('.shadercache','shaders'));shutil.copytree(src/'shaders',runtime/'shaders')
    shutil.copy2(ROOT/'build/probe-leak-fix-staging/TraditionalProbeGI.dll',runtime/'plugins/TraditionalProbeGI.dll')
    env=os.environ.copy();env.update(PROBE_LEAK_OUTPUT=str(out),PROBE_SNAPSHOT_RUNTIME=str(runtime),FALCOR_MEDIA_FOLDERS='F:/media')
    with (out/'console.log').open('w') as log:
        r=subprocess.run([str(runtime/'Mogwai.exe'),'--headless','--deferred','--device-type','d3d12','--width','1280','--height','720',
            '--script',str(ROOT/'tests/probe_gi/leak_fix_validation.py'),'--logfile',str(out/'Mogwai.log')],cwd=runtime,env=env,
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
    if r.returncode:raise RuntimeError('See '+str(out/'failure.txt'))
    os.environ['PROBE_SNAPSHOT_RUNTIME']=str(runtime)
    for d in out.iterdir():
        if not d.is_dir() or d.name=='runtime':continue
        for name,output in [('hdr','Probes.color'),('display','Display.dst')]:
            files=list(d.glob('frame.'+output+'.*'));assert len(files)==1,(d,output)
            w,h,v=read_image(files[0]);(d/(name+'.f32')).write_bytes(v.tobytes())
            if name=='display':png(d/'display.png',np.array(v).reshape(h,w,3))
    def image(d):return np.fromfile(out/d/'hdr.f32',dtype='<f4').reshape(720,1280,3)
    metrics={}
    for name,old,new,ray in [('first','original','first-new','first-ray'),('second','room2-old','room2-new','room2-ray'),('fixture','fixture-old','fixture-new','fixture-ray')]:
        a,b,r=image(old),image(new),image(ray)
        metrics[name]={'old_mae_to_ray':float(abs(a-r).mean()),'new_mae_to_ray':float(abs(b-r).mean()),
            'old_positive_error':float(np.maximum(a-r,0).mean()),'new_positive_error':float(np.maximum(b-r,0).mean()),
            'old_negative_error':float(np.maximum(r-a,0).mean()),'new_negative_error':float(np.maximum(r-b,0).mean())}
        font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',18);canvas=Image.new('RGB',(1280,780),(24,24,24));draw=ImageDraw.Draw(canvas)
        for i,(label,folder) in enumerate([('Before',old),('Leak-resistant preset',new),('Ray visibility reference (same bias)',ray)]):
            x,y=i%2*640,i//2*390;draw.text((x+8,y+4),label,font=font,fill='white');canvas.paste(Image.open(out/folder/'display.png').resize((640,360)),(x,y+30))
        canvas.save(out/(name+'-comparison.png'))
    a,r=image('open-new'),image('open-ray');metrics['open']={'mean_signal':float(a.mean()),'mae_to_ray':float(abs(a-r).mean())};assert a.mean()>.001
    write_json(out/'metrics.json',metrics);verify(ROOT/'build/probe-issues/20260924-021543-642825');print(json.dumps(metrics,indent=2))
if __name__=='__main__':main()
