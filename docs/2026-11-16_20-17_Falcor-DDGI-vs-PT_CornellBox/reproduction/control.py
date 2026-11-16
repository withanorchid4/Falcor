import json,pathlib,subprocess,os
s=json.loads(pathlib.Path('F:/build/gi-evaluation-current.json').read_text());w=pathlib.Path(s['work'])
env=os.environ.copy();env.update(FALCOR_DEVMODE='0',FALCOR_MEDIA_FOLDERS='F:/media',GI_SMOKE='0',GI_SCENE=str(w/'lambert.pyscene'),GI_PT_FRAMES='4096',GI_PT_TRACE='Default')
for mode in ['pt-a','pt-b']:
    env.update(GI_CASE=mode,GI_OUT='lambert-'+mode)
    d=w/env['GI_OUT'];d.mkdir(exist_ok=True)
    cmd=[str(w/'runtime/Mogwai.exe'),'--device-type','d3d12','--headless','--deferred','--script',str(w/'capture.py'),'--width','960','--height','540','--logfile',str(d/'mogwai.log')]
    with (d/'console.log').open('w',encoding='utf-8') as f:
        p=subprocess.run(cmd,cwd=w/'runtime',env=env,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
    assert p.returncode==0 and (d/'complete.json').exists() and not (d/'failure.txt').exists(),str(d)
    print('completed '+mode,flush=True)
