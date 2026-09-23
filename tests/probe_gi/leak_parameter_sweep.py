"""Derive an explicitly labeled experiment snapshot from an isolated rebake, then sweep runtime settings."""
from pathlib import Path
import argparse, ast, json, os, shutil, subprocess, sys
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'scripts'))
from probe_snapshot import digest, verify

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--resolution',type=int,choices=(64,128),default=128)
    resolution=parser.parse_args().resolution
    source=ROOT/'build/probe-issues/20260924-021543-642825'
    baked=source/('runs/20260924-031025-9187bd' if resolution==128 else 'runs/20260924-031002-4b2257')
    root=ROOT/'build/probe-leak-fix'; case=root/f'local{resolution}-case'; case.mkdir(exist_ok=False)
    data=verify(source); rendered=json.loads((baked/'render.json').read_text())
    shutil.copytree(source/'baseline',case/'baseline',copy_function=os.link)
    shutil.copyfile(baked/'rebaked.shprobe',case/'probes.shprobe')
    tree=ast.parse((source/'graph.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='create_pass' and len(node.args)>2:
            if isinstance(node.args[1],ast.Constant) and node.args[1].value=='TraditionalProbeGI':
                props=rendered['probeSettings']; props['cacheFile']=''; node.args[2]=ast.parse(repr(props),mode='eval').body
    (case/'graph.py').write_text(ast.unparse(tree),encoding='utf-8')
    data.update(probeSettings=props,cacheSha256=digest(case/'probes.shprobe'),graphSha256=digest(case/'graph.py'),
        experiment={'originalSnapshot':str(source),'rebakeRun':str(baked),'baselineIsOriginalAngular':True})
    (case/'snapshot.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    runs={}; env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
    for name,props in [('base8',{'varianceBase':1e-8}),('view02',{'viewBias':.02}),
        ('view02_base8',{'viewBias':.02,'varianceBase':1e-8}),('view05_base8',{'viewBias':.05,'varianceBase':1e-8}),
        ('view02_smooth',{'viewBias':.02,'varianceBase':1e-8,'distanceSmooth':True})]:
        override=root/(f'local{resolution}-'+name+'.json');override.write_text(json.dumps(props))
        r=subprocess.run([sys.executable,str(ROOT/'scripts/replay_probe_snapshot.py'),str(case),'--overrides',str(override)],
            cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=600)
        (root/(f'local{resolution}-'+name+'-console.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode: raise RuntimeError(name+' failed: '+r.stderr)
        runs[name]=json.loads(r.stdout); print(name,runs[name]['output'],flush=True)
        (root/f'local{resolution}-sweep-runs.json').write_text(json.dumps(runs,indent=2),encoding='utf-8')
    verify(source);verify(case)

if __name__=='__main__': main()
