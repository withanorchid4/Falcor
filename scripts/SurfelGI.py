"""Independent W298-derived Surfel GI, with progressive accumulation."""
from falcor import *

def render_graph_SurfelGI():
    g=RenderGraph('SurfelGI')
    g.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False,'adjustShadingNormals':True}),'Visibility')
    g.addPass(createPass('SurfelGI',{}),'Surfel')
    g.addPass(createPass('SurfelGIRenderPass',{}),'Lighting')
    g.addPass(createPass('AccumulatePass',{'enabled':True,'autoReset':True,'precisionMode':'SingleCompensated'}),'Accumulate')
    g.addPass(createPass('ToneMapper',{'autoExposure':False,'useSceneMetadata':False,'operator':'Aces','filmSpeed':100.,'fNumber':1.,'shutter':1.}),'Display')
    g.addEdge('Visibility.vbuffer','Surfel.packedHitInfo')
    g.addEdge('Visibility.vbuffer','Lighting.packedHitInfo')
    g.addEdge('Surfel.output','Lighting.indirectLighting')
    g.addEdge('Lighting.output','Accumulate.input')
    g.addEdge('Accumulate.output','Display.src')
    g.markOutput('Display.dst')
    return g
SurfelGI=render_graph_SurfelGI()
try:m.addGraph(SurfelGI)
except NameError:pass
