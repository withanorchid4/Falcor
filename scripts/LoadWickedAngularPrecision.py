"""Load the coupled angular-precision experiment; STAGE also accepts r32/r64/r128-wide."""
from pathlib import Path
from datetime import datetime
import sys

STAGE = 'r128'
resolution, rays, exponent = {'r32':(32,10704,334), 'r64':(64,42800,1337),
    'r128-wide':(128,171200,64), 'r128':(128,171200,5350)}[STAGE]
root = Path('F:/')
sys.path.insert(0,str(root/'scripts'))
from probe_snapshot import replay
cache = root/f'build/wicked-angular-precision/{STAGE}/visibility.wdist'
replay(m,renderFrame,root/'build/probe-issues/20260924-104702-ae8fb0',
    root/'build/wicked-angular-interactive'/datetime.now().strftime('%Y%m%d-%H%M%S-%f'), {
        'antiLeakMode':'wickedStatic', 'wickedResolution':resolution,
        'wickedRaysPerProbe':rays, 'wickedExponent':float(exponent), 'wickedCacheFile':str(cache),
        'wickedNormalBias':.001, 'wickedSmoothBackface':.01,
        'wickedVisibilityMode':'moments', 'samplingMode':'full'}, rebake=not cache.is_file())
m.activeGraph.getPass('Probes').configureDebug({'enabled':False})
print('Loaded Wicked angular precision experiment:',STAGE)
