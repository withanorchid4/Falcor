"""Official NVIDIA SHaRC cache + common half-resolution FG and Accumulate."""
from pathlib import Path
import runpy
factory = runpy.run_path(str(Path(__file__).with_name('DDGIAccumulated.py')))['render_graph_DDGIAccumulated']
SHaRC = factory('half', interactive=True, world_cache=True)
SHaRC.name = 'SHaRC'
SHaRC.getPass('WorldCache').set_properties({'sharc': True})
try: m.addGraph(SHaRC)
except NameError: pass
