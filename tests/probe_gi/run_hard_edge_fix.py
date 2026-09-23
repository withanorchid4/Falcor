"""Run staged plugin validation, then decode asynchronous captures and build comparisons."""
from pathlib import Path
import json, os, shutil, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'scripts'))
from probe_snapshot import read_image, png, write_json

def main():
    out=ROOT/'build/probe-hard-edge-fix-validation-02'; out.mkdir(exist_ok=False)
    runtime=out/'runtime'; source=ROOT/'build/windows-vs2022/bin/Release'
    def link(a,b):
        if 'plugins' in Path(a).relative_to(source).parts: shutil.copy2(a,b)
        else:
            try: os.link(a,b)
            except OSError: shutil.copy2(a,b)
    shutil.copytree(source,runtime,copy_function=link,ignore=shutil.ignore_patterns('.shadercache','shaders'))
    shutil.copytree(source/'shaders',runtime/'shaders')
    shutil.copy2(ROOT/'build/probe-hard-edge-fix-staging/TraditionalProbeGI.dll',runtime/'plugins/TraditionalProbeGI.dll')
    env=os.environ.copy(); env.update(PROBE_FIX_OUTPUT=str(out),PROBE_SNAPSHOT_RUNTIME=str(runtime),FALCOR_MEDIA_FOLDERS='F:/media')
    with (out/'console.log').open('w') as log:
        r=subprocess.run([str(runtime/'Mogwai.exe'),'--headless','--deferred','--device-type','d3d12','--width','1280','--height','720',
            '--script',str(ROOT/'tests/probe_gi/hard_edge_fix.py'),'--logfile',str(out/'Mogwai.log')],cwd=runtime,env=env,
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
    if r.returncode: raise RuntimeError('Validation failed: '+str(out/'failure.txt'))
    os.environ['PROBE_SNAPSHOT_RUNTIME']=str(runtime)
    for directory in out.iterdir():
        if not directory.is_dir() or directory.name=='runtime': continue
        for name,output in [('hdr','Probes.color'),('display','Display.dst')]:
            files=list(directory.glob('frame.'+output+'.*'))
            if len(files)!=1: raise RuntimeError('Missing output '+str(directory)+' '+output)
            w,h,values=read_image(files[0]); (directory/(name+'.f32')).write_bytes(values.tobytes())
            if name=='display': png(directory/'display.png',np.array(values).reshape(h,w,3))
    case=ROOT/'build/probe-issues/20260924-021543-642825'
    def load(path): return np.fromfile(path,dtype='<f4').reshape(720,1280,3)
    original=load(case/'baseline/hdr.f32'); old=load(out/'baseline/hdr.f32'); restored=load(out/'restored/hdr.f32')
    assert np.max(abs(original-old))==0 and np.max(abs(original-restored))==0
    runs=json.loads((ROOT/'build/probe-hard-edge-candidates/gpu-runs.json').read_text())
    results={'original_max_error':0.,'round_trip_max_error':0.}
    for name in ('smooth','hemisphere','smooth_hemisphere'):
        error=float(np.max(abs(load(out/name/'hdr.f32')-load(Path(runs[name]['output'])/'hdr.f32'))))
        assert error<2e-5,(name,error); results[name+'_candidate_max_error']=error
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',19)
    for filename,entries in [('comparison',[('Original',out/'baseline'),('Smooth moments only',out/'smooth'),
        ('Back-facing rejection',out/'hemisphere'),('Ray visibility reference',case/'runs/20260924-023100-9a017f')]),
        ('second-view',[('Original',out/'room-view-old'),('Back-facing rejection',out/'room-view-fixed'),('Ray visibility',out/'room-view-ray')]),
        ('fixture',[('Original',out/'fixture-old'),('Back-facing rejection',out/'fixture-fixed'),('Ray visibility',out/'fixture-ray')])]:
        canvas=Image.new('RGB',(1280,390*((len(entries)+1)//2)),(24,24,24)); draw=ImageDraw.Draw(canvas)
        for i,(label,path) in enumerate(entries):
            x,y=(i%2)*640,(i//2)*390; draw.text((x+8,y+3),label,font=font,fill='white')
            canvas.paste(Image.open(path/'display.png').resize((640,360)),(x,y+30))
        canvas.save(out/(filename+'.png'))
    write_json(out/'render-checks.json',results); print(json.dumps(results,indent=2))

if __name__=='__main__': main()
