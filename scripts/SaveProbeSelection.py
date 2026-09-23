"""Run via File > Load Script after picking a valid surface in TraditionalProbeGI."""
import json
from pathlib import Path

p = m.getGraph('TraditionalProbeGI').getPass('Probes')
selection = p.debugInfo
if not selection['valid']:
    raise RuntimeError('Pick a valid surface before saving. The previous file was not changed.')

def components(value):
    return [value.x, value.y, value.z] if hasattr(value, 'x') else list(value)

selection_path = Path('F:/build/probe-selection.json')
selection_path.parent.mkdir(parents=True, exist_ok=True)
selection_path.write_text(json.dumps({
    'position': components(selection['position']),
    'normal': components(selection['normal']),
    'normalBias': p.settings['normalBias'],
    'viewBias': p.settings['viewBias'],
}, indent=2), encoding='utf-8')
print('Saved probe selection:', selection_path)
