"""Exercise the launcher graph set, material preservation and Surfel reset/sharing."""
from falcor import *
from pathlib import Path
import os, runpy, json, traceback

R = Path(__file__).resolve().parents[2]
O = R / 'build/surfel-preview-check'
O.mkdir(exist_ok=True)
(O / 'failure.txt').unlink(missing_ok=True)
try:
    os.environ['FALCOR_START_SCENE'] = 'CornellLambert'
    os.environ['FALCOR_START_RENDERER'] = 'SurfelGI'
    ns = runpy.run_path(str(R / 'scripts/GIPreview.py'), init_globals={'m': m})
    assert ns['initial_graph'] == 'SurfelGI'
    graphs = ns['graphs']
    m.loadScene(str(R / 'scripts/scenes/CornellLambert.pyscene'))
    def materials():
        return [(x.name, str(x.type), str(getattr(x, 'baseColor', None)),
                 str(getattr(x, 'specularParams', None)), x.doubleSided, str(x.alphaMode))
                for x in m.scene.materials]
    baseline = materials()
    for name in ['SurfelGI', 'PTReference', 'SurfelGI']:
        m.setActiveGraph(graphs[name])
        for _ in range(8): renderFrame()
        assert materials() == baseline
    g = graphs['SurfelGI']
    assert g.getPass('Accumulate').enabled
    g.getPass('Surfel').reset()
    renderFrame()
    assert g.getPass('Surfel').stats['frames'] == 1
    # Exercise the optional history-based sharing path, then restore the default.
    g.updatePass('Surfel', {'irradianceSharing': True})
    for _ in range(8): renderFrame()
    g.updatePass('Surfel', {'irradianceSharing': False})
    for _ in range(8): renderFrame()
    (O / 'complete.json').write_text(json.dumps({'graphs': list(graphs), 'materialsUnchanged': True,
        'accumulateDefaultEnabled': True, 'cacheResetPassed': True, 'sharingTogglePassed': True}, indent=2))
except:
    (O / 'failure.txt').write_text(traceback.format_exc())
exit()
