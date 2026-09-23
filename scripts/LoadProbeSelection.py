"""Run via File > Load Script after loading the SAME scene and its probe cache."""
import json
from pathlib import Path
from falcor import float3

selection = json.loads(Path('F:/build/probe-selection.json').read_text(encoding='utf-8'))
p = m.getGraph('TraditionalProbeGI').getPass('Probes')
p.inspectSurfacePoint(float3(*selection['position']), float3(*selection['normal']))
p.configureDebug({'normalBias': selection['normalBias'], 'viewBias': selection.get('viewBias', 0), 'showLinks': True})
print('Restored probe selection. Inspection updates on the next rendered frame.')
