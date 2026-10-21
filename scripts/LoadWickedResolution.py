"""Load the fixed-camera resolution experiment. Change RESOLUTION to 14/32/64/128 for comparison."""
from pathlib import Path
from datetime import datetime
import sys

RESOLUTION=128
root=Path('F:/')
sys.path.insert(0,str(root/'scripts'))
from probe_snapshot import replay

cache=root/f'build/wicked-resolution-sweep/r{RESOLUTION}/visibility.wdist'
replay(m,renderFrame,root/'build/probe-issues/20260924-104702-ae8fb0',
    root/'build/wicked-resolution-interactive'/datetime.now().strftime('%Y%m%d-%H%M%S-%f'),{
        'antiLeakMode':'wickedStatic','wickedResolution':RESOLUTION,'wickedCacheFile':str(cache),
        'wickedRaysPerProbe':2048,'wickedNormalBias':.001,'wickedSmoothBackface':.01,
        'wickedVisibilityMode':'moments','samplingMode':'full'},rebake=not cache.is_file())
m.activeGraph.getPass('Probes').configureDebug({'enabled':False})
print('Loaded Wicked resolution experiment:',RESOLUTION)
