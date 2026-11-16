import json, pathlib, os, subprocess, shutil, time
root=pathlib.Path('F:/');state=json.loads((root/'build/gi-evaluation-current.json').read_text());work=pathlib.Path(state['work']);out=pathlib.Path(state['result'])
shutil.copy2(work/'capture.py',out/'reproduction/capture.py')
env=os.environ.copy();env.update(FALCOR_DEVMODE='0',FALCOR_MEDIA_FOLDERS='F:/media',GI_SMOKE='0')
for mode in ['ddgi','pt-a','pt-b']:
    env['GI_CASE']=mode
    d=work/mode;d.mkdir(exist_ok=True)
    for f in ['failure.txt','complete.json']:
        if (d/f).exists():(d/f).unlink()
    command=[str(work/'runtime/Mogwai.exe'),'--device-type','d3d12','--headless','--deferred','--script',str(work/'capture.py'),'--width','960','--height','540','--logfile',str(d/'mogwai.log')]
    (d/'command.json').write_text(json.dumps({'command':command,'cwd':str(work/'runtime'),'environment':{k:env[k] for k in ['FALCOR_DEVMODE','FALCOR_MEDIA_FOLDERS','GI_CASE','GI_SMOKE']},'start':time.time()},indent=2))
    print('Starting '+mode,flush=True)
    with (d/'console.log').open('w',encoding='utf-8') as log:
        p=subprocess.run(command,cwd=work/'runtime',env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=1800)
    assert p.returncode==0 and (d/'complete.json').exists() and not (d/'failure.txt').exists(),str(d)
    print('Completed '+mode,flush=True)
