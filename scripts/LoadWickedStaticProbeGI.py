"""Load the saved wall view with the independent Wicked static visibility option.

Use Probes > Anti-leak scheme to switch between Current and Wicked static.
This script deliberately loads the saved scene/camera, like the other reproduction scripts.
"""
from pathlib import Path
from datetime import datetime
import sys

root = Path('F:/')
sys.path.insert(0, str(root/'scripts'))
from probe_snapshot import replay

case = root/'build/probe-issues/20260924-104702-ae8fb0'
cache = root/'build/wicked-static-validation/visibility.wdist'
output = root/'build/wicked-static-interactive'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
replay(m, renderFrame, case, output, {
    'antiLeakMode':'wickedStatic', 'wickedCacheFile':str(cache),
    'wickedNormalBias':0.001, 'wickedSmoothBackface':0.01,
    'wickedVisibilityMode':'moments', 'samplingMode':'full',
}, rebake=not cache.is_file())
m.activeGraph.getPass('Probes').configureDebug({'enabled':False})
print('Wicked static ready. Anti-leak scheme switches back to the preserved Current path.')
