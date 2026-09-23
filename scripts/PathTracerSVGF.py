from falcor import *


def render_graph_PathTracerSVGF():
    """Official SVGF wiring, with raw and accumulated comparison outputs."""
    g = RenderGraph("PathTracerSVGF")
    # SVGF generates the missing pnFwidth from RT position/normal guides.
    g.addPass(createPass("GBufferRT", {
        "samplePattern": "Stratified", "sampleCount": 16, "useAlphaTest": True,
    }), "GBuffer")
    g.addPass(createPass("PathTracer", {
        "samplesPerPixel": 1, "tracePassMode": "MinimalPayload",
    }), "PathTracer")
    g.addPass(createPass("SVGFPass", {
        "Enabled": True, "Demodulate": False, "Iterations": 4, "FeedbackTap": 1,
        "PhiColor": 10.0, "PhiNormal": 128.0,
        "Alpha": 0.05, "MomentsAlpha": 0.2,
    }), "SVGF")
    g.addPass(createPass("AccumulatePass", {
        "enabled": True, "autoReset": True, "precisionMode": "Single",
        "maxFrameCount": 0,
    }), "Reference")
    for name in ("ToneMapperSVGF", "ToneMapperRaw", "ToneMapperReference"):
        g.addPass(createPass("ToneMapper", {
            "autoExposure": False, "exposureCompensation": 0.0,
        }), name)

    for channel in ("vbuffer", "viewW", "mvec"):
        g.addEdge("GBuffer." + channel, "PathTracer." + channel)
    g.addEdge("PathTracer.color", "SVGF.Color")
    g.addEdge("PathTracer.albedo", "SVGF.Albedo")
    for source, target in (
        ("emissive", "Emission"), ("posW", "WorldPosition"),
        ("guideNormalW", "WorldNormal"),
        ("linearZ", "LinearZ"), ("mvec", "MotionVec"),
    ):
        g.addEdge("GBuffer." + source, "SVGF." + target)
    g.addEdge("SVGF.Filtered image", "ToneMapperSVGF.src")
    g.addEdge("PathTracer.color", "ToneMapperRaw.src")
    g.addEdge("PathTracer.color", "Reference.input")
    g.addEdge("Reference.output", "ToneMapperReference.src")
    # First output is the default when imported in Mogwai.
    for name in ("ToneMapperSVGF", "ToneMapperRaw", "ToneMapperReference"):
        g.markOutput(name + ".dst")
    return g


PathTracerSVGF = render_graph_PathTracerSVGF()
try:
    m.addGraph(PathTracerSVGF)
except NameError:
    pass
