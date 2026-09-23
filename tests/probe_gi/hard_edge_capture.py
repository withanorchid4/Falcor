"""Mogwai entry point, used only by hard_edge_diagnose.py's private runtime."""
import os, sys, time, traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from probe_snapshot import replay, read_image, write_json

out=Path(os.environ['PROBE_DIAG_OUTPUT'])
try:
    replay(m,renderFrame,Path(os.environ['PROBE_DIAG_CASE']),out/'baseline')
    graph=m.activeGraph; p=graph.getPass('Probes')
    # Keep Mogwai's selected output alive even though diagnostics read only the HDR output.
    graph.markOutput('Probes.color')
    p.configureDebug({'enabled':True,'view':6,'showProbes':False,'showBounds':False,'showLinks':False,
        'showIds':False,'preview':False,'pickEnabled':False})
    fc=m.frameCapture; fc.outputDir=str(out); fc.captureAllOutputs=False
    for group in range(10):
        for corner in range(8 if group<7 else 1):
            name=f'g{group}-c{corner}'
            p.configureDebug({'selectedProbe':group*8+corner}); renderFrame()
            fc.baseFilename=name; fc.capture()
            print('Captured',name,flush=True)
    # Decode EXRs in the host after shutdown flushes the background writer.
    write_json(out/'completed.json',{'captures':59})
    exit()
except Exception:
    (out/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8'); exit(1)
