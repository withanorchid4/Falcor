"""Load one verified fixed-camera experiment in Mogwai; keep the app interactive.

Set STAGE to p64 / range / weights / cutoff / hitbias to inspect a cumulative step.
The default removes the previous strong-filter experiment without enabling the
later, unsuccessful candidates automatically.
"""
from pathlib import Path
from datetime import datetime
import json, shutil, sys

STAGE = 'p64'
sys.path.insert(0, 'F:/scripts')
from probe_snapshot import replay, digest, write_json

root = Path('F:/build/probe-wicked-alignment')
source = Path('F:/build/probe-issues/20260924-104702-ae8fb0')
report = json.loads((root/STAGE/'render.json').read_text())
cache = root/('range' if STAGE == 'weights' else STAGE)/'rebaked.shprobe'
case = root/(STAGE+'-interactive-case')
case.mkdir(exist_ok=True)
shutil.copyfile(source/'graph.py', case/'graph.py')
shutil.copyfile(cache, case/'probes.shprobe')
metadata = json.loads((source/'snapshot.json').read_text())
metadata['cacheSha256'] = digest(case/'probes.shprobe')
write_json(case/'snapshot.json', metadata)
replay(m, renderFrame, case, root/'interactive'/datetime.now().strftime('%Y%m%d-%H%M%S-%f'), report['overrides'])
m.activeGraph.getPass('Probes').configureDebug({'enabled':False})
print('Loaded Wicked alignment step:', STAGE)
