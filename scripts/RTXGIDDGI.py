"""Interactive DDGI: optional full/half final gather and accumulation, without NRD."""
from pathlib import Path
import runpy


def render_graph_RTXGIDDGI():
    factory = runpy.run_path(str(Path(__file__).with_name('DDGIAccumulated.py')))['render_graph_DDGIAccumulated']
    graph = factory('ddgi', interactive=True)
    graph.name = 'RTXGIDDGI'
    return graph


RTXGIDDGI = render_graph_RTXGIDDGI()
try:
    m.addGraph(RTXGIDDGI)
except NameError:
    pass
