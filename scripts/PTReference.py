"""Undenoised 8 spp/frame path tracing with progressive accumulation."""
from falcor import *
def render_graph_PTReference():
    g=RenderGraph('PTReference')
    g.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False}),'Visibility')
    g.addPass(createPass('PathTracer',{'samplesPerPixel':8,'maxSurfaceBounces':31,
        'maxDiffuseBounces':31,'maxSpecularBounces':31,'maxTransmissionBounces':0,
        'useRussianRoulette':False,'useNEE':True,'useMIS':True,'useRTXDI':False,
        'useReSTIRPT':False,'colorFormat':'RGBA32F'}),'PT')
    g.addPass(createPass('AccumulatePass',{'enabled':True,'autoReset':True,'precisionMode':'Single'}),'Accumulate')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    for c in ['vbuffer','viewW','mvec']:g.addEdge('Visibility.'+c,'PT.'+c)
    g.addEdge('PT.color','Accumulate.input');g.addEdge('Accumulate.output','Display.src')
    g.markOutput('Display.dst');return g
PTReference=render_graph_PTReference()
try:m.addGraph(PTReference)
except NameError:pass
