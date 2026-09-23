"""Internal headless entry point. Use replay_probe_snapshot.py from the command line."""
from pathlib import Path
import os, sys, json, traceback
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_snapshot import replay
output=Path(os.environ['PROBE_SNAPSHOT_OUTPUT'])
try:
    replay(m,renderFrame,os.environ['PROBE_SNAPSHOT_CASE'],output,
           json.loads(os.environ.get('PROBE_SNAPSHOT_OVERRIDES','{}')),
           os.environ.get('PROBE_SNAPSHOT_REBAKE')=='1')
    exit()
except Exception:
    (output/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    exit(1)
