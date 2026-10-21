"""Static Probe GI snapshots. Called inside Mogwai; utility functions also work in host Python."""
import ast
import array
import contextlib
from datetime import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import time
import uuid
import zlib

CAMERA = ('position', 'target', 'up', 'frameHeight', 'aspectRatio', 'focalLength',
          'focalDistance', 'apertureRadius', 'nearPlane', 'farPlane', 'shutterSpeed', 'ISOSpeed', 'animated')
MATERIAL = ('doubleSided', 'thinSurface', 'alphaMode', 'alphaThreshold', 'nestedPriority',
    'baseColor', 'specularParams', 'transmissionColor', 'diffuseTransmission', 'specularTransmission',
    'volumeAbsorption', 'volumeScattering', 'volumeAnisotropy', 'indexOfRefraction',
    'displacementScale', 'displacementOffset', 'emissiveColor', 'emissiveFactor', 'entryPointVolumeProperties')
LIGHT = ('active', 'intensity', 'position', 'direction', 'openingAngle', 'penumbraAngle', 'angle')
RENDER = ('useEnvLight', 'useAnalyticLights', 'useEmissiveLights', 'useGridVolumes', 'diffuseAlbedoMultiplier')

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def json_value(v):
    if isinstance(v,float) and not math.isfinite(v): return {'float':repr(v)}
    if v is None or isinstance(v, (str, bool, int, float)): return v
    if isinstance(v, Path): return str(v)
    if isinstance(v, dict): return {k: json_value(x) for k,x in v.items()}
    if isinstance(v, (list, tuple)): return [json_value(x) for x in v]
    if hasattr(v, 'value'): return {'enum': int(v.value)}
    if hasattr(v, 'x'):
        return json_value([getattr(v,k) for k in ('x','y','z','w') if hasattr(v,k)])
    raise TypeError(f'Unsupported snapshot value: {type(v).__name__}')

def like(current, value):
    if isinstance(value,dict) and 'float' in value: return float(value['float'])
    if isinstance(value, dict) and 'enum' in value: return type(current)(value['enum'])
    if isinstance(value, list) and hasattr(current, 'x'):
        return type(current)(*[like(0.,x) for x in value])
    return value

def properties(obj, names):
    return {k: json_value(getattr(obj,k)) for k in names if hasattr(obj,k)}

def restore(obj, values):
    for k,v in values.items(): setattr(obj,k,like(getattr(obj,k),v))

def write_json(path, value):
    Path(path).write_text(json.dumps(json_value(value), ensure_ascii=False, indent=2, allow_nan=False),encoding='utf-8')

def png(path, image):
    import numpy as np
    a=np.asarray(image)
    if a.dtype != np.uint8: a=np.rint(np.clip(a,0,1)*255).astype(np.uint8)
    a=np.ascontiguousarray(a[:,:,:3]); h,w,_=a.shape
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+row.tobytes() for row in a)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+
                          chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))

def read_image(path):
    """Read Falcor captures using its bundled FreeImage; no packages in embedded Python."""
    import ctypes as ct
    runtime=Path(os.environ.get('PROBE_SNAPSHOT_RUNTIME',str(Path(__file__).resolve().parents[1]/'build/windows-vs2022/bin/Release')))
    with os.add_dll_directory(str(runtime)):
        lib=ct.WinDLL(str(runtime/'FreeImage.dll'))
        signatures={'GetFileTypeU':([ct.c_wchar_p,ct.c_int],ct.c_int),
            'LoadU':([ct.c_int,ct.c_wchar_p,ct.c_int],ct.c_void_p),'Unload':([ct.c_void_p],None),
            'GetWidth':([ct.c_void_p],ct.c_uint),'GetHeight':([ct.c_void_p],ct.c_uint),
            'GetPitch':([ct.c_void_p],ct.c_uint),'GetImageType':([ct.c_void_p],ct.c_int),
            'GetBPP':([ct.c_void_p],ct.c_uint),'GetBits':([ct.c_void_p],ct.c_void_p)}
        for name,(args,result) in signatures.items():
            fn=getattr(lib,'FreeImage_'+name); fn.argtypes=args; fn.restype=result
        filename=str(Path(path).resolve()); fmt=lib.FreeImage_GetFileTypeU(filename,0)
        bitmap=lib.FreeImage_LoadU(fmt,filename,0)
        if not bitmap: raise RuntimeError('Could not read capture: '+filename)
        try:
            w,h=lib.FreeImage_GetWidth(bitmap),lib.FreeImage_GetHeight(bitmap)
            typ,pitch=lib.FreeImage_GetImageType(bitmap),lib.FreeImage_GetPitch(bitmap)
            ptr=lib.FreeImage_GetBits(bitmap); values=array.array('f')
            channels={11:3,12:4}.get(typ)
            for y in range(h-1,-1,-1):  # FreeImage bottom-up -> PNG/array top-down.
                if channels:
                    row=struct.unpack('<'+str(w*channels)+'f',ct.string_at(ptr+y*pitch,w*channels*4))
                    for x in range(w): values.extend(row[x*channels:x*channels+3])
                elif typ==1 and lib.FreeImage_GetBPP(bitmap) in (24,32):
                    n=lib.FreeImage_GetBPP(bitmap)//8; row=ct.string_at(ptr+y*pitch,w*n)
                    for x in range(w): values.extend((row[x*n+2]/255,row[x*n+1]/255,row[x*n]/255))
                else: raise RuntimeError('Unsupported capture image format')
            if not all(math.isfinite(v) for v in values): raise RuntimeError('Non-finite capture pixels')
            return w,h,values
        finally: lib.FreeImage_Unload(bitmap)

def png_rgb(path,w,h,values):
    rgb=bytes(round(max(0,min(1,v))*255) for v in values)
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+rgb[y*w*3:(y+1)*w*3] for y in range(h))
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+
        chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))

def graph_source(graph):
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream): graph.print()
    source=stream.getvalue()
    if not source.strip(): raise RuntimeError('Could not export the current render graph.')
    ast.parse(source)
    return source

def marked_outputs(source):
    return {node.args[0].value for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Attribute) and node.func.attr in ('mark_output','markOutput')
            and node.args and isinstance(node.args[0],ast.Constant)}

def capture(m, frame, graph, p, directory):
    """One clean evaluation; restore live UI/debug/capture state even if writing fails."""
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    marked=marked_outputs(graph_source(graph)); added=[]
    old_debug=p.debugInfo['enabled']
    fc=m.frameCapture; old_capture=(fc.outputDir,fc.baseFilename,fc.captureAllOutputs)
    try:
        for output in ('Probes.color','Display.dst'):
            if output not in marked: graph.markOutput(output); added.append(output)
        p.configureDebug({'enabled':False}); frame()
        fc.outputDir=str(directory); fc.baseFilename='frame'; fc.captureAllOutputs=False; fc.capture()
        resolution=None
        for name,output in (('hdr','Probes.color'),('display','Display.dst')):
            deadline=time.monotonic()+15
            while True:
                files=list(directory.glob('frame.'+output+'.*'))
                try:
                    if len(files)!=1: raise RuntimeError('Waiting for capture: '+output)
                    w,h,values=read_image(files[0])
                    break
                except (RuntimeError,OSError):
                    if time.monotonic()>=deadline: raise
                    time.sleep(.05)  # Falcor writes captures on a worker thread.
            (directory/(name+'.f32')).write_bytes(values.tobytes())
            if name=='display': png_rgb(directory/'display.png',w,h,values)
            if resolution and resolution!=[w,h]: raise RuntimeError('Output dimensions differ')
            resolution=[w,h]
        return resolution
    finally:
        fc.outputDir,fc.baseFilename,fc.captureAllOutputs=old_capture
        p.configureDebug({'enabled':old_debug})
        for output in added: graph.unmarkOutput(output)

def build_identity(root):
    import ctypes as ct
    filename=ct.create_unicode_buffer(32768)
    kernel=ct.WinDLL('kernel32',use_last_error=True)
    kernel.GetModuleFileNameW.argtypes=[ct.c_void_p,ct.c_wchar_p,ct.c_uint]
    kernel.GetModuleFileNameW.restype=ct.c_uint
    if not kernel.GetModuleFileNameW(None,filename,len(filename)): raise ct.WinError(ct.get_last_error())
    runtime=Path(filename.value).parent
    paths=[runtime/'plugins/TraditionalProbeGI.dll']
    paths+=list((runtime/'shaders/RenderPasses/TraditionalProbeGI').glob('*.slang'))
    return {str(p):digest(p) for p in paths if p.is_file()}

def save_snapshot(m, frame, root=None):
    root=Path(root or 'F:/build/probe-issues')
    graph=m.activeGraph
    if graph is None: raise RuntimeError('Select the TraditionalProbeGI graph first.')
    p=graph.getPass('Probes'); display=graph.getPass('Display')
    if p.type!='TraditionalProbeGI' or not p.ready or p.baking:
        raise RuntimeError('A completed, loaded Probe GI bake is required.')
    if display.properties.get('autoExposure',False):
        raise RuntimeError('Disable Auto Exposure before creating a reproducible snapshot.')
    cache=Path(p.cacheFile)
    if not cache.is_file(): raise RuntimeError('The completed probe cache is missing.')
    case=root/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    case.mkdir(parents=True,exist_ok=False)
    with cache.open(encoding='utf-8') as stream:
        magic=stream.readline().strip()
        if magic not in ('FALCOR_PROBE_SH 3','FALCOR_PROBE_SH 4','FALCOR_PROBE_SH 5'): raise RuntimeError('Unsupported cache format.')
        source=Path(json.loads(stream.readline()))
    companion=source.with_suffix('.pyscene')
    entry=companion if companion.is_file() else source
    files={str(x.resolve()):digest(x) for x in {source,entry}}
    env=m.scene.envMap
    env_data=None
    if env is not None:
        env_path=Path(env.path); files[str(env_path.resolve())]=digest(env_path)
        env_data={'path':str(env_path.resolve()),'properties':properties(env,('rotation','intensity','tint'))}
    source_text=graph_source(graph); (case/'graph.py').write_text(source_text,encoding='utf-8')
    shutil.copyfile(cache,case/'probes.shprobe')
    data={'version':1,'graph':graph.name,'scene':str(entry.resolve()),'assets':files,
          'camera':properties(m.scene.camera,CAMERA),'time':m.clock.time,'frame':m.clock.frame,'animated':m.scene.animated,
          'renderSettings':properties(m.scene.renderSettings,RENDER),'environment':env_data,
          'materials':[{'name':x.name,'properties':properties(x,MATERIAL)} for x in m.scene.materials],
          'lights':[{'name':x.name,'properties':properties(x,LIGHT)} for x in m.scene.lights],
          'probeSettings':json_value(p.settings),'selection':json_value(p.debugInfo),
          'cacheOriginal':str(cache),'cacheSha256':digest(case/'probes.shprobe'),
          'graphSha256':digest(case/'graph.py'),'build':build_identity(Path(__file__).resolve().parents[1])}
    if p.settings.get('antiLeakMode','current') == 'wickedStatic':
        wicked=Path(p.wickedCacheFile)
        if not wicked.is_file(): raise RuntimeError('Save the Wicked distance cache before taking a snapshot.')
        shutil.copyfile(wicked,case/'visibility.wdist')
        data['wickedCacheSha256']=digest(case/'visibility.wdist')
    old_time_scale=m.clock.timeScale
    try:
        m.clock.timeScale=0
        data['resolution']=capture(m,frame,graph,p,case/'baseline')
    finally:
        m.clock.timeScale=old_time_scale
    write_json(case/'snapshot.json',data)
    (root/'latest.txt').write_text(str(case),encoding='utf-8')
    print('Probe issue snapshot:',case)
    return case

def verify(case):
    case=Path(case); data=json.loads((case/'snapshot.json').read_text(encoding='utf-8'))
    if data['version']!=1: raise RuntimeError('Unsupported snapshot version.')
    for path,expected in data['assets'].items():
        if not Path(path).is_file() or digest(path)!=expected: raise RuntimeError('Scene asset changed: '+path)
    for name,key in (('probes.shprobe','cacheSha256'),('graph.py','graphSha256')):
        if digest(case/name)!=data[key]: raise RuntimeError('Snapshot modified: '+name)
    if 'wickedCacheSha256' in data and digest(case/'visibility.wdist') != data['wickedCacheSha256']:
        raise RuntimeError('Snapshot modified: visibility.wdist')
    return data

def replay(m, frame, case, output, overrides=None, rebake=False):
    import falcor
    case=Path(case); output=Path(output); data=verify(case)
    overrides=overrides or {}
    # Rewrite only this plugin's constructor properties; no snapshot may trigger an auto-bake.
    class Rewrite(ast.NodeTransformer):
        def visit_Call(self,node):
            self.generic_visit(node)
            if isinstance(node.func,ast.Attribute) and node.func.attr=='create_pass' and len(node.args)>=3:
                if isinstance(node.args[1],ast.Constant) and node.args[1].value=='TraditionalProbeGI':
                    node.args[2]=ast.Call(func=ast.Name(id='_snapshot_props',ctx=ast.Load()),args=[node.args[2]],keywords=[])
            return node
    def snapshot_props(props):
        props=dict(props)
        for key,value in overrides.items():
            # Explicit opt-in for runtime options introduced after older snapshots were saved.
            extensions={'distanceSmooth':False,'normalHemisphere':False,'samplingMode':'full','sparseStride':2,'ddgiWeights':False,'wickedWeights':False,'distanceWeightCutoff':0.,'distanceHitBias':0.,'antiLeakMode':'current','wickedNormalBias':.001,'wickedSmoothBackface':.01,'wickedExponent':64.,'wickedResolution':14,'wickedRaysPerProbe':2048,'wickedCacheFile':'','wickedVisibilityMode':'moments'}
            if key not in props and key not in extensions: raise ValueError('Unknown override: '+key)
            props[key]=like(props.get(key,extensions.get(key)),value)
        props['mode']='manual'
        wicked=props.get('antiLeakMode','current') == 'wickedStatic'
        props['cacheFile']=str(output/'rebaked.shprobe' if rebake and not wicked else case/'probes.shprobe')
        if wicked and 'wickedCacheFile' not in overrides:
            props['wickedCacheFile']=str(output/'visibility.wdist' if rebake else case/'visibility.wdist')
        return props
    tree=ast.fix_missing_locations(Rewrite().visit(ast.parse((case/'graph.py').read_text(encoding='utf-8'))))
    scope={'_snapshot_props':snapshot_props}
    exec(compile(tree,str(case/'graph.py'),'exec'),scope)
    functions=[n.name for n in tree.body if isinstance(n,ast.FunctionDef)]
    if len(functions)!=1: raise RuntimeError('Expected a single exported graph.')
    graph=scope[functions[0]](); m.addGraph(graph); m.setActiveGraph(graph)
    m.loadScene(data['scene']); m.resizeFrameBuffer(*data['resolution']); m.clock.time=data['time']; m.clock.pause()
    m.scene.animated=data['animated']
    restore(m.scene.camera,data['camera'])
    settings=m.scene.renderSettings; restore(settings,data['renderSettings']); m.scene.renderSettings=settings
    env=data['environment']
    if env is None: m.scene.envMap=None
    else:
        m.scene.setEnvMap(env['path']); restore(m.scene.envMap,env['properties'])
    for kind in ('materials','lights'):
        objects=list(getattr(m.scene,kind)); records=data[kind]
        if len(objects)!=len(records): raise RuntimeError(kind+' count changed')
        for obj,record in zip(objects,records):
            if obj.name!=record['name']: raise RuntimeError(kind+' identity changed')
            restore(obj,record['properties'])
    frame(); frame(); p=graph.getPass('Probes')
    if p.settings.get('antiLeakMode','current') == 'wickedStatic' and rebake:
        p.configureAntiLeak({'antiLeakMode':'current'})
        p.loadCache(); frame()
        if not p.ready: raise RuntimeError(p.status)
        p.configureAntiLeak({'antiLeakMode':'wickedStatic'})
        p.bake()
    elif rebake: p.bake()
    else: p.loadCache()
    for i in range(200000 if rebake else 2):
        frame()
        if p.ready or not p.baking: break
    if not p.ready: raise RuntimeError(p.status)
    selection=data['selection']
    if selection['valid']:
        p.inspectSurfacePoint(falcor.float3(*selection['position']),falcor.float3(*selection['normal'])); frame()
    actual_selection=json_value(p.debugInfo)
    capture(m,frame,graph,p,output)
    report={'ready':True,'camera':properties(m.scene.camera,CAMERA),'resolution':data['resolution'],
        'probeSettings':json_value(p.settings),'selection':actual_selection,'overrides':overrides,'rebake':rebake,
        'build':build_identity(Path(__file__).resolve().parents[1]),'sourceSnapshot':str(case),
        'cacheSha256':digest(p.cacheFile)}
    write_json(output/'render.json',report)
    return report
