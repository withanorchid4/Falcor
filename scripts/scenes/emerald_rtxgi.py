"""Full-city preview volume, deliberately coarse; not a tuned GI benchmark.

Imported bounds: (-115.12,-4.93,-115.11)..(115.02,108.25,115.06) meters.
Single volume, 16384 probes, spacing about (7.74,8,7.74) meters. No adaptive
subdivision: future street/interior experiments need denser or multiple volumes.
"""
from falcor import float3, uint3


def configure_graph(graph):
    graph.getPass('DDGI').set_properties({
        'autoBounds': False, 'gridCounts': uint3(32, 16, 32),
        'gridMin': float3(-120, -6, -120), 'gridMax': float3(120, 114, 120),
        'raysPerProbe': 256, 'hysteresis': 0.97,
        'enableRelocation': True, 'enableClassification': True,
        'normalBias': 0.1 / (240.0 / 31),
        'viewBias': 0.3 / (240.0 / 31),
        'minFrontfaceDistance': 0.3 / (240.0 / 31),
    })


def configure_display(graph):
    graph.updatePass('Display', {'autoExposure': False, 'useSceneMetadata': False,
        'operator': 'Aces', 'filmSpeed': 100.0, 'fNumber': 2.0, 'shutter': 1.0})
