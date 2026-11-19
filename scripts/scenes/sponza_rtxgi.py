"""Probe placement from NVIDIA RTXGI-DDGI 1.3.7 test-harness/config/sponza.ini.

Both import the same Khronos Sponza glTF in right-handed Y-up coordinates,
without an additional scene transform. Lighting and materials remain scene-owned.
"""
from falcor import float3, uint3


def configure_graph(graph):
    origin = float3(-0.4, 5.4, -0.25)
    spacing = float3(1.02, 0.5, 0.45)
    # Bounds describe the first/last probe centers, not the outer scene bounds.
    half_extent = spacing * 10.5  # (22 - 1) / 2
    graph.getPass("DDGI").set_properties({
        "autoBounds": False,
        "gridCounts": uint3(22, 22, 22),
        "gridMin": origin - half_extent,
        "gridMax": origin + half_extent,
        "raysPerProbe": 256,
        "hysteresis": 0.97,
        "enableRelocation": True,
        "enableClassification": True,
        # Falcor's existing API expresses these as fractions of min(spacing).
        "normalBias": 0.1 / 0.45,
        "viewBias": 0.3 / 0.45,
        "minFrontfaceDistance": 0.3 / 0.45,
    })
