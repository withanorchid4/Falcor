"""Standalone static preview; use PathTracerSVGF.py to import only the graph."""
from pathlib import Path
import runpy

scope = runpy.run_path(str(Path(__file__).with_name("PathTracerSVGF.py")))
m.addGraph(scope["PathTracerSVGF"])
m.clock.pause()
