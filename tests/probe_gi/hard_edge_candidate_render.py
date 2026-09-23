"""Render candidate formulas in a private shader tree, with the immutable issue snapshot."""
from pathlib import Path
import json, os, shutil, subprocess, sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from probe_snapshot import verify, digest

def main():
    out=ROOT/'build/probe-hard-edge-candidates'; out.mkdir(exist_ok=True)
    runtime=out/'runtime'; source=ROOT/'build/windows-vs2022/bin/Release'
    if not runtime.exists():
        def link(a,b):
            try: os.link(a,b)
            except OSError: shutil.copy2(a,b)
        shutil.copytree(source,runtime,copy_function=link,ignore=shutil.ignore_patterns('.shadercache','shaders'))
        shutil.copytree(source/'shaders',runtime/'shaders')
    relative=Path('shaders/RenderPasses/TraditionalProbeGI/TraditionalProbeGI.rt.slang')
    original=(source/relative).read_text(encoding='utf-8')
    case=ROOT/'build/probe-issues/20260924-021543-642825'; verify(case)
    env=os.environ.copy(); env['PYTHONIOENCODING']='utf-8'
    results={}
    for name,smooth,hemisphere in [('smooth',True,False),('hemisphere',False,True),('smooth_hemisphere',True,True)]:
        shader=original
        if smooth:
            anchor='    float2 t = frac(p);'; assert shader.count(anchor)==1
            shader=shader.replace(anchor,anchor+'\n    t = t * t * (3.f - 2.f * t);')
        if hemisphere:
            anchor='    float normalWeight = gUseNormalWeight ? wrap * wrap + 0.2f : 1.f;'; assert shader.count(anchor)==1
            shader=shader.replace(anchor,'    float gate = saturate(cosine / 0.2f);\n    gate = gate * gate * (3.f - 2.f * gate);\n    float normalWeight = gUseNormalWeight ? (wrap * wrap + 0.2f) * gate : 1.f;')
        (runtime/relative).write_text(shader,encoding='utf-8'); (out/(name+'.slang')).write_text(shader,encoding='utf-8')
        result=subprocess.run([sys.executable,str(ROOT/'scripts/replay_probe_snapshot.py'),str(case),'--executable',str(runtime/'Mogwai.exe')],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',env=env,timeout=600)
        (out/(name+'-console.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode: raise RuntimeError(name+' failed: '+result.stderr)
        results[name]=json.loads(result.stdout)
        print(name,results[name]['output'],flush=True)
        (out/'gpu-runs.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    verify(case)

if __name__=='__main__': main()
