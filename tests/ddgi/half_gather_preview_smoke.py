"""Verify the updated preview graph selection after removing PT+NRD."""
from pathlib import Path
import os,runpy,json,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/half-gather-preview-smoke.json'
try:
    os.environ['FALCOR_START_SCENE']='CornellLambert'
    os.environ['FALCOR_START_RENDERER']='DDGIHalf'
    os.environ['CORNELL_RTXGI_CONFIG']=str(ROOT/'build/three-way-half-gather/scene.json')
    graphs=runpy.run_path(str(ROOT/'scripts/GIPreview.py'),init_globals={'m':m})['graphs']
    assert set(graphs)=={'PTReference','TraditionalProbeGI','RTXGIDDGI','DDGIHalfGather'}
    assert m.activeGraph.name=='DDGIHalfGather'
    m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
    for name in graphs:
        m.setActiveGraph(graphs[name])
        for _ in range(4):renderFrame()
    OUT.write_text(json.dumps({'passed':True,'graphs':list(graphs)}))
except Exception:OUT.write_text(json.dumps({'passed':False,'error':traceback.format_exc()}))
finally:exit()
