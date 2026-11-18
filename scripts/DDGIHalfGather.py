"""Default half-resolution final gather: AccumulatePass, without NRD."""
from pathlib import Path
import runpy

factory=runpy.run_path(str(Path(__file__).with_name('DDGIAccumulated.py')))['render_graph_DDGIAccumulated']
DDGIHalfGather=factory('half', interactive=True)
DDGIHalfGather.name='DDGIHalfGather'
try:m.addGraph(DDGIHalfGather)
except NameError:pass
