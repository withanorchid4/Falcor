"""Static convergence comparison: no NRD, progressive full-image accumulation."""
from falcor import *

def render_graph_DDGIAccumulated(mode='full', interactive=False, world_cache=False):
    if mode not in ['ddgi','half','full']:raise ValueError(mode)
    name='WorldCache' if world_cache else 'DDGI'
    g=RenderGraph('LumenWorldCache' if world_cache else 'DDGIAccumulated_'+mode)
    g.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False}),'Visibility')
    g.addPass(createPass('RTXGIDDGI',{'finalGather':mode!='ddgi',
        'halfResolutionGather':mode=='half' or (interactive and mode=='ddgi'),
        'restirGather':False,'useRTXDI':False,'worldCache':world_cache}),name)
    for c in ['vbuffer','viewW','mvec']:g.addEdge('Visibility.'+c,name+'.'+c)
    output=name+'.color'
    if mode=='half' or interactive:
        g.addPass(createPass('DDGIReconstruct',{}),'Reconstruct')
        for c in ['diffuse','specular']:
            g.addEdge(name+'.'+c+'RadianceHitDist','Reconstruct.'+c)
            g.addEdge(name+'.'+c+'Reflectance','Reconstruct.'+c+'Reflectance')
        g.addEdge(name+'.unfilteredColor','Reconstruct.direct')
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
