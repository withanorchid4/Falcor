"""Validate captured HDR outputs from the formerly failing random sequence."""
from pathlib import Path
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'build/final-gather-python'))
import OpenEXR

data = ROOT / 'build/restir-nvidia-fix-replay'
output = ROOT / 'docs/2026-11-18_DDGI-ReSTIR-NVIDIA-fix'
output.mkdir(exist_ok=True)
run = json.loads((data / 'complete.json').read_text())
assert run['stage'] == 'complete' and run['frames'] == 262144
assert run['max_age'] == 0 and run['final_stats']['rejectedRaySamples'] == 0
rows = []
for path in sorted(data.glob('*.exr')):
    rgb = OpenEXR.File(str(path)).channels()['RGB'].pixels
    assert np.isfinite(rgb).all(), path
    # Scene-specific explosion sentinel, not a radiance clamp in the renderer.
    assert rgb.max() < 100, path
    rows.append({'file': path.name, 'max': float(rgb.max())})
assert len(rows) == 102
result = dict(frames=run['frames'], seed_offset=run['seed_offset'], max_age=0,
              rejectedRaySamples=0, capture_count=len(rows),
              max_rgb=max(row['max'] for row in rows), captures=rows)
for path in [data / 'validation.json', output / 'replay-validation.json']:
    path.write_text(json.dumps(result, indent=2))
print({key: value for key, value in result.items() if key != 'captures'})
