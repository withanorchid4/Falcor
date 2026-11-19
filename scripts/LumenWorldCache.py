"""Independent world-space diffuse radiance cache + existing half-resolution FG."""
from pathlib import Path
import runpy
factory = runpy.run_path(str(Path(__file__).with_name('DDGIAccumulated.py')))['render_graph_DDGIAccumulated']
LumenWorldCache = factory('half', interactive=True, world_cache=True)
LumenWorldCache.name = 'LumenWorldCache'
try: m.addGraph(LumenWorldCache)
except NameError: pass
