"""Official NRD graph and pass defaults, with scene time paused for inspection."""
from pathlib import Path
import runpy

PathTracerNRD = runpy.run_path(str(Path(__file__).with_name("PathTracerNRD.py")))["PathTracerNRD"]
try:
    m.addGraph(PathTracerNRD)
    m.clock.pause()
except NameError:
    pass
