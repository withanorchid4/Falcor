"""1080p full-reservoir A/B. Keep Accumulate separate from reservoir reuse."""
from falcor import *
from pathlib import Path
import os, runpy, json, traceback, time
R = Path(__file__).resolve().parents[2]
O = R / 'build/restir-gather-comparison'
O.mkdir(exist_ok=True)
(O / 'failure.txt').unlink(missing_ok=True)
record = {'resolution': [1920,1080], 'probe_warmup': 2560, 'accumulation_frames': 16384,
          'history_candidates': 20, 'spatial_samples': 4, 'integration_samples': 16, 'spatial_passes': 2, 'jitter': True, 'nrd': False, 'started': time.time()}
def progress(stage):
    record['stage'] = stage; record['elapsed'] = time.time() - record['started']
    (O / 'progress.json').write_text(json.dumps(record, indent=2))
def frames(n):
    for _ in range(n): renderFrame()
def capture(tag):
    m.frameCapture.baseFilename = tag; m.frameCapture.capture()
try:
    os.environ['CORNELL_RTXGI_CONFIG'] = str(R / 'build/highres-1080p-split-rerun/scene.json')
    setup = runpy.run_path(str(R / 'scripts/scenes/cornell_rtxgi.py'))
    factory = runpy.run_path(str(R / 'scripts/DDGIAccumulated.py'))['render_graph_DDGIAccumulated']
    for name, enabled, full_integrate in [('off', False, False), ('restir', True, False), ('integrated', True, True)]:
        g = factory('half'); g.name = 'Reservoir_' + name; setup['configure_graph'](g)
        dd = g.getPass('DDGI'); acc = g.getPass('Accumulate')
        dd.set_properties({'restirFullResolution': full_integrate, 'restirGather': enabled, 'restirHistoryLength': 20, 'jitterHalfGather': True, 'restirSpatialSamples': 4, 'restirIntegrateSamples': 16, 'restirSpatialPasses': 2})
        g.unmarkOutput('Display.dst'); g.markOutput('Accumulate.output')
        m.addGraph(g); m.setActiveGraph(g); m.loadScene(str(R / 'scripts/scenes/CornellLambert.pyscene'))
        m.clock.pause(); m.scene.camera.animated = False
        m.frameCapture.outputDir = str(O); m.frameCapture.captureAllOutputs = False
        progress(name + ' warmup'); frames(2560)
        # Independent raw frames: Accumulate bypassed, reservoir remains active.
        acc.enabled = False
        for i in range(16): renderFrame(); capture(name + '-raw-' + str(i))
        acc.enabled = True
        for i in range(1,16385):
            renderFrame()
            if i in [1,8,32,128,1024,8192,16384]: capture(name + '-' + str(i))
            if i % 2048 == 0: progress(name + ' ' + str(i))
        g.markOutput('Display.dst'); frames(64)
        m.profiler.enabled = True; frames(16); m.profiler.start_capture(); frames(512)
        (O / (name + '-timing.json')).write_text(json.dumps(m.profiler.end_capture()))
        m.profiler.enabled = False; record[name + '_stats'] = dict(dd.stats)
        m.removeGraph(g)
    progress('complete'); (O / 'complete.json').write_text(json.dumps(record, indent=2))
except Exception: (O / 'failure.txt').write_text(traceback.format_exc())
finally: exit()
