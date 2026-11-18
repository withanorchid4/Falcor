"""Two independent reflection samples per pixel, terminated with DDGI.
Denoiser.Enabled toggles NRD. Static accumulation is optional and off by default.
"""
from falcor import *


def render_graph_RTXGIDDGIFinalGather(denoise=True, accumulate=False):
    g = RenderGraph("RTXGIDDGIFinalGather")
    g.addPass(createPass("GBufferRT", {"samplePattern": "Center", "useAlphaTest": True, "useDOF": False}), "Visibility")
    g.addPass(createPass("RTXGIDDGI", {"finalGather": True, "gatherDiffuse": True,
        "gatherSpecular": True, "useRTXDI": False}), "DDGI")
    g.addPass(createPass("NRD", {"method": "RelaxDiffuseSpecular", "enabled": denoise,
        "worldSpaceMotion": True, "maxIntensity": 10000.0}), "Denoiser")
    g.addPass(createPass("ModulateIllumination", {"useResidualRadiance": False}), "Compose")
    g.addPass(createPass("AccumulatePass", {"enabled": accumulate, "autoReset": True,
        "precisionMode": "Single"}), "Accumulate")
    g.addPass(createPass("ToneMapper", {"autoExposure": False}), "Display")
    g.addEdge("Visibility.vbuffer", "DDGI.vbuffer")
    g.addEdge("Visibility.viewW", "DDGI.viewW")
    g.addEdge("DDGI.diffuseRadianceHitDist", "Denoiser.diffuseRadianceHitDist")
    g.addEdge("DDGI.specularRadianceHitDist", "Denoiser.specularRadianceHitDist")
    g.addEdge("Visibility.mvecW", "Denoiser.mvec")
    g.addEdge("Visibility.linearZ", "Denoiser.viewZ")
    g.addEdge("Visibility.normWRoughnessMaterialID", "Denoiser.normWRoughnessMaterialID")
    g.addEdge("Denoiser.filteredDiffuseRadianceHitDist", "Compose.diffuseRadiance")
    g.addEdge("Denoiser.filteredSpecularRadianceHitDist", "Compose.specularRadiance")
    g.addEdge("DDGI.diffuseReflectance", "Compose.diffuseReflectance")
    g.addEdge("DDGI.specularReflectance", "Compose.specularReflectance")
    g.addEdge("DDGI.unfilteredColor", "Compose.emission")
    g.addEdge("Compose.output", "Accumulate.input")
    g.addEdge("Accumulate.output", "Display.src")
    g.markOutput("Display.dst")
    return g

RTXGIDDGIFinalGather = render_graph_RTXGIDDGIFinalGather()
try:
    m.addGraph(RTXGIDDGIFinalGather)
except NameError:
    pass
