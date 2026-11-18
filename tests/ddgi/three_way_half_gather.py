"""Live DDGI vs half-resolution FG+NRD, with two independent raw PT references."""
from falcor import *
from pathlib import Path
import os,json,runpy,traceback
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/three-way-half-gather';OUT.mkdir(exist_ok=True)
for stale in ['complete.json','failure.txt']:(OUT/stale).unlink(missing_ok=True)
record={'resolution':[480,270],'gather_resolution':[240,135],'pt_spp_per_frame':8,
    'pt_spp_per_sequence':32768,'pt_sequences':2,'pt_max_bounces':31,
    'probe_warmup':2048,'denoiser_warmup':512,'capture_frames':64,
    'probe_updates':True,'point_light_radius':4,'point_light_min_distance':1}
def save():(OUT/'progress.json').write_text(json.dumps(record,indent=2))
def frames(n):
    for _ in range(n):renderFrame()
def capture(tag):m.frameCapture.baseFilename=tag;m.frameCapture.capture()
try:
    cfg=json.loads((ROOT/'build/final-gather-comparison/scene.json').read_text())
    (OUT/'scene.json').write_text(json.dumps(cfg,indent=2))
    os.environ['CORNELL_RTXGI_CONFIG']=str(OUT/'scene.json')
    for mode in ['ddgi','half']:
        record['stage']=mode+' warmup';save()
        if mode=='half':
            g=runpy.run_path(str(ROOT/'scripts/DDGIHalfGatherNRD.py'))['render_graph_DDGIHalfGatherNRD'](preset='legacy')
            output='Reconstruct.color'
        else:
            g=RenderGraph('DDGIOriginal')
            g.addPass(createPass('GBufferRT',{'samplePattern':'Center','useAlphaTest':True,'useDOF':False}),'Visibility')
            g.addPass(createPass('RTXGIDDGI',{'finalGather':False,'useRTXDI':False}),'DDGI')
            g.addPass(createPass('ToneMapper',{'autoExposure':False}),'Display')
            for c in ['vbuffer','viewW']:g.addEdge('Visibility.'+c,'DDGI.'+c)
            g.addEdge('DDGI.color','Display.src');g.markOutput('Display.dst');output='DDGI.color'
        dd=g.getPass('DDGI')
        dd.set_properties({'gridCounts':uint3(9,9,9),'raysPerProbe':256,'autoBounds':False,
            'gridMin':float3(-1.2,-.2,-1.2),'gridMax':float3(1.2,2.2,1.2),
            'normalBias':.02/.3,'viewBias':.1/.3,'hysteresis':.97,'useWRC':False})
        g.markOutput(output);g.markOutput('Visibility.normW')
        m.addGraph(g);m.setActiveGraph(g)
        m.loadScene(str(ROOT/'scripts/scenes/CornellLambert.pyscene'))
        m.clock.pause();m.scene.camera.animated=False
        m.frameCapture.outputDir=str(OUT);m.frameCapture.captureAllOutputs=False
        frames(2048)
        if mode=='half':g.getPass('Denoiser').set_properties({'resetHistory':True})
        frames(256);capture(mode+'-warm-256');frames(256);capture(mode+'-warm-512')
        record['stage']=mode+' capture';save()
        for i in range(64):frames(1);capture(mode+'-'+str(i))
        # Verify actual half-resolution buffers without retaining diagnostic overhead in timing.
        if mode=='half':
            g.markOutput('DDGI.diffuseRadianceHitDist');g.markOutput('Guides.halfDepth')
            frames(1);capture('half-dimensions')
            g.unmarkOutput('DDGI.diffuseRadianceHitDist');g.unmarkOutput('Guides.halfDepth')
        frames(128);m.profiler.enabled=True;frames(32);m.profiler.start_capture();frames(256)
        (OUT/(mode+'-timing.json')).write_text(json.dumps(m.profiler.end_capture(),indent=2));m.profiler.enabled=False
        record[mode+'_stats']=dict(dd.stats);save()
    g=runpy.run_path(str(ROOT/'scripts/PTReference.py'))['PTReference']
    g.markOutput('Accumulate.output');g.markOutput('Visibility.normW')
    pt=g.getPass('PT');acc=g.getPass('Accumulate');acc.set_properties({'autoReset':False})
    m.addGraph(g);m.setActiveGraph(g)
    for seq,offset in [('a',1),('b',100001)]:
        acc.reset()
        for i in range(4096):
            pt.fixedSeed=offset+i;renderFrame()
            if (i+1) in [512,1024,2048,4096]:
                capture('pt-'+seq+'-'+str((i+1)*8))
                record['stage']='PT '+seq+' '+str((i+1)*8)+' spp';save()
    record['stage']='complete';save();(OUT/'complete.json').write_text(json.dumps(record,indent=2))
except Exception:(OUT/'failure.txt').write_text(traceback.format_exc())
finally:exit()
