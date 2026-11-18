"""Full-resolution direct light; quarter pixel count final gather and RELAX."""
from falcor import *
from pathlib import Path
import runpy

def render_graph_DDGIHalfGatherNRD(preset='tuned'):
    presets=runpy.run_path(str(Path(__file__).with_name('nrd_half_settings.py')))
    if preset not in ['legacy','tuned']:raise ValueError(preset)
    settings=dict(presets['TUNED' if preset=='tuned' else 'LEGACY'])
    settings['inputSampleOffset']=float2(*settings['inputSampleOffset'])
    g=RenderGraph('DDGIHalfGatherNRD')
    g.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False}),'Visibility')
    g.addPass(createPass('RTXGIDDGI',{'finalGather':True,'halfResolutionGather':True,'useRTXDI':False}),'DDGI')
    g.addPass(createPass('DDGIReconstruct',{'prepare':True}),'Guides')
    g.addPass(createPass('NRD',{'method':'RelaxDiffuseSpecular','outputSize':'Half',
        'worldSpaceMotion':True,'maxIntensity':10000.0,**settings}),'Denoiser')
    g.addPass(createPass('DDGIReconstruct',{}),'Reconstruct')
    g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
    for c in ['vbuffer','viewW']:g.addEdge('Visibility.'+c,'DDGI.'+c)
    for a,b in [('linearZ','depth'),('normWRoughnessMaterialID','normalRoughness'),('mvecW','motion')]:
        g.addEdge('Visibility.'+a,'Guides.'+b)
    for a,b in [('halfDepth','viewZ'),('halfNormalRoughness','normWRoughnessMaterialID'),('halfMotion','mvec')]:
        g.addEdge('Guides.'+a,'Denoiser.'+b)
    for c in ['diffuseRadianceHitDist','specularRadianceHitDist']:g.addEdge('DDGI.'+c,'Denoiser.'+c)
    for c in ['diffuse','specular']:
        g.addEdge('Denoiser.filtered'+c.title()+'RadianceHitDist','Reconstruct.'+c)
        g.addEdge('DDGI.'+c+'Reflectance','Reconstruct.'+c+'Reflectance')
    g.addEdge('DDGI.unfilteredColor','Reconstruct.direct')
    g.addEdge('Visibility.normW','Reconstruct.normal')
    g.addEdge('Visibility.linearZ','Reconstruct.depth')
    g.addEdge('Reconstruct.color','Display.src');g.markOutput('Display.dst')
    return g
DDGIHalfGatherNRD=render_graph_DDGIHalfGatherNRD()
try:m.addGraph(DDGIHalfGatherNRD)
except NameError:pass
