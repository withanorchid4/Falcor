"""NRD-denoised RTXDI direct lighting plus RTXGI-DDGI diffuse indirect (D3D12)."""
from falcor import *


def render_graph_RTXGIDDGI():
    g = RenderGraph("RTXGIDDGI")
    # The same primary visibility supplies RTXDI and NRD's surface guides.
    g.addPass(createPass("GBufferRT", {"samplePattern": "Center", "useAlphaTest": True, "useDOF": False}), "Visibility")
    g.addPass(createPass("RTXDIPass", {"options": {
        "mode": "SpatiotemporalResampling",
        "biasCorrection": "RayTraced",
    }}), "DirectLighting")
    g.addPass(createPass("NRD", {
        "method": "RelaxDiffuseSpecular",
        "enabled": True,
        "worldSpaceMotion": True,
        "maxIntensity": 10000.0,
    }), "DirectDenoiser")
    g.addPass(createPass("ModulateIllumination", {"useResidualRadiance": False}), "DirectModulate")
    g.addPass(createPass("RTXGIDDGI", {
        "gridCounts": uint3(8, 6, 8),
        "raysPerProbe": 256,
        "hysteresis": 0.97,
        "normalBias": 0.05,
        "viewBias": 0.05,
        "enableRelocation": True,
        "enableClassification": True,
        "updateEnabled": True,
        "autoBounds": True,
        "showProbes": False,
        "indirectOnly": False,
        "useRTXDI": True,
        "intensity": 1.0,
    }), "DDGI")
    g.addPass(createPass("ToneMapper", {"autoExposure": False, "exposureCompensation": 0.0}), "Display")
    g.addEdge("Visibility.vbuffer", "DDGI.vbuffer")
    g.addEdge("Visibility.viewW", "DDGI.viewW")
    g.addEdge("Visibility.vbuffer", "DirectLighting.vbuffer")
    g.addEdge("Visibility.mvec", "DirectLighting.mvec")
    g.addEdge("DirectLighting.diffuseIllumination", "DirectDenoiser.diffuseRadianceHitDist")
    g.addEdge("DirectLighting.specularIllumination", "DirectDenoiser.specularRadianceHitDist")
    g.addEdge("Visibility.mvecW", "DirectDenoiser.mvec")
    g.addEdge("Visibility.linearZ", "DirectDenoiser.viewZ")
    g.addEdge("Visibility.normWRoughnessMaterialID", "DirectDenoiser.normWRoughnessMaterialID")
    g.addEdge("DirectDenoiser.filteredDiffuseRadianceHitDist", "DirectModulate.diffuseRadiance")
    g.addEdge("DirectDenoiser.filteredSpecularRadianceHitDist", "DirectModulate.specularRadiance")
    g.addEdge("DirectLighting.diffuseReflectance", "DirectModulate.diffuseReflectance")
    g.addEdge("DirectLighting.specularReflectance", "DirectModulate.specularReflectance")
    # Emission and the environment background bypass the denoiser.
    g.addEdge("DirectLighting.emission", "DirectModulate.emission")
    g.addEdge("DirectModulate.output", "DDGI.directLighting")
    g.addEdge("DDGI.color", "Display.src")
    g.markOutput("Display.dst")
    return g


RTXGIDDGI = render_graph_RTXGIDDGI()
try:
    m.addGraph(RTXGIDDGI)
except NameError:
    pass
