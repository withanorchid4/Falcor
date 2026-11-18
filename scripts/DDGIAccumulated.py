"""Static convergence comparison: no NRD, progressive full-image accumulation."""
from falcor import *

def render_graph_DDGIAccumulated(mode='full', interactive=False):
    if mode not in ['ddgi','half','full']:raise ValueError(mode)
    g=RenderGraph('DDGIAccumulated_'+mode)
    g.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False}),'Visibility')
    g.addPass(createPass('RTXGIDDGI',{'finalGather':mode!='ddgi',
        'halfResolutionGather':mode=='half' or (interactive and mode=='ddgi'),'useRTXDI':False}),'DDGI')
    for c in ['vbuffer','viewW']:g.addEdge('Visibility.'+c,'DDGI.'+c)
    output='DDGI.color'
    if mode=='half' or interactive:
        g.addPass(createPass('DDGIReconstruct',{}),'Reconstruct')
        for c in ['diffuse','specular']:
            g.addEdge('DDGI.'+c+'RadianceHitDist','Reconstruct.'+c)
            g.addEdge('DDGI.'+c+'Reflectance','Reconstruct.'+c+'Reflectance')
        g.addEdge('DDGI.unfilteredColor','Reconstruct.direct')
        g.addEdge('Visibility.normW','Reconstruct.normal')
        g.addEdge('Visibility.linearZ','Reconstruct.depth')
        output='Reconstruct.color'
    g.addPass(createPass('AccumulatePass',{'enabled':True,'autoReset':True,'precisionMode':'Single'}),'Accumulate')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    g.addEdge(output,'Accumulate.input');g.addEdge('Accumulate.output','Display.src')
    g.markOutput('Display.dst')
    return g

DDGIAccumulated=render_graph_DDGIAccumulated(interactive=True)
try:m.addGraph(DDGIAccumulated)
except NameError:pass
