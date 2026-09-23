"""Host-side isolated GPU factor capture for a saved Probe snapshot (no production edits)."""
import argparse
from pathlib import Path
import json, os, shutil, subprocess, sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from probe_snapshot import verify, write_json, digest, read_image

BRANCH=r'''
        // Isolated diagnostic runtime only. The production shader is unchanged.
        if (gDebugEnabled && gDebugView == 6)
        {
            uint group = gSelectedProbe / 8, corner = gSelectedProbe % 8;
            float3 t, biased; bool clamped;
            uint3 cell = probeCell(sd.posW, sd.frame.N, t, biased, clamped);
            float total = 0.f;
            for (uint j=0; j<8; ++j) {
                float a,b; float4 c;
                total += cornerWeight(sd.posW,sd.frame.N,biased,cell,t,j,a,b,c);
            }
            float tri, vis; float4 info;
            float raw = cornerWeight(sd.posW,sd.frame.N,biased,cell,t,corner,tri,vis,info);
            float w = raw / max(total,1e-4f);
            uint3 offset=uint3(corner&1,(corner>>1)&1,(corner>>2)&1);
            uint id=flattenProbe(cell+offset);
            float3 origin=lerp(gGridMin,gGridMax,float3(cell+offset)/float3(gGridCounts-1));
            float3 dir=normalize(biased-origin);
            float3 E=float3(0);
            for(uint k=0;k<9;++k) E+=gProbeSH[id*9+k].xyz*(probeSH(k,sd.frame.N)*probeCosineKernel(k)/float(gSampleTotal));
            float3 result=float3(0);
            if(group==0) result=float3(w,raw,vis);
            else if(group==1) result=float3(tri,info.w,total);
            else if(group==2) result=info.xyz;
            else if(group==3) result=float3(float(id),probeOctEncode(dir));
            else if(group==4) result=E;
            else if(group==5) result=w*E;
            else if(group==6) { float h=traceProbeDistance(origin,biased); result=float3(h,probeHitVisible(h,info.z)?1.f:0.f,info.z-info.x); }
            else if(group==7) result=sd.posW;
            else if(group==8) result=sd.frame.N;
            else if(group==9) result=properties.diffuseReflectionAlbedo;
            gOutputColor[pixel]=float4(result,1);
            gProbeLighting[pixel]=float4(0,0,0,1);
            return;
        }
'''

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('case',type=Path); ap.add_argument('output',type=Path)
    args=ap.parse_args(); data=verify(args.case)
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    runtime=out/'runtime'; source=ROOT/'build/windows-vs2022/bin/Release'
    def link(a,b):
        try: os.link(a,b)
        except OSError: shutil.copy2(a,b)
    # Immutable binaries are shared; shader copies are private. Never edit a hardlinked binary.
    shutil.copytree(source,runtime,copy_function=link,ignore=shutil.ignore_patterns('.shadercache','shaders'))
    shutil.copytree(source/'shaders',runtime/'shaders')
    shader=runtime/'shaders/RenderPasses/TraditionalProbeGI/TraditionalProbeGI.rt.slang'
    original=shader.read_text(encoding='utf-8')
    anchor='        let properties = mi.getProperties(sd);'
    assert original.count(anchor)==1
    shader.write_text(original.replace(anchor,anchor+'\n'+BRANCH),encoding='utf-8')
    write_json(out/'diagnostic-identity.json',{'sourceShader':digest(source/'shaders/RenderPasses/TraditionalProbeGI/TraditionalProbeGI.rt.slang'),
        'diagnosticShader':digest(shader),'snapshot':str(args.case.resolve()),'groups':['weight/raw/visibility','tri/normal/total',
        'mean/variance/distance','id/uv','SH irradiance','weighted irradiance','hit/ray/d-mean','position','normal','albedo']})
    env=os.environ.copy(); env.update(PROBE_DIAG_CASE=str(args.case.resolve()),PROBE_DIAG_OUTPUT=str(out),
        PROBE_SNAPSHOT_RUNTIME=str(runtime),FALCOR_MEDIA_FOLDERS='F:/media')
    cmd=[str(runtime/'Mogwai.exe'),'--headless','--deferred','--device-type','d3d12','--width',str(data['resolution'][0]),
        '--height',str(data['resolution'][1]),'--script',str(ROOT/'tests/probe_gi/hard_edge_capture.py'),'--logfile',str(out/'Mogwai.log')]
    with (out/'console.log').open('w') as stream:
        result=subprocess.run(cmd,cwd=runtime,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError(f'Capture failed: {out}')
    os.environ['PROBE_SNAPSHOT_RUNTIME']=str(runtime)
    for group in range(10):
        for corner in range(8 if group<7 else 1):
            name=f'g{group}-c{corner}'
            files=list(out.glob(name+'.Probes.color.*.exr'))
            assert len(files)==1, name
            w,h,values=read_image(files[0])
            assert [w,h]==data['resolution']
            (out/(name+'.f32')).write_bytes(values.tobytes())
    verify(args.case); print(out)

if __name__=='__main__': main()
