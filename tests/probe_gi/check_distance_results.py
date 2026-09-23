"""Read actual baked moments and HDR captures; no external Python packages."""
from pathlib import Path
import json, math
from check_results import read_exr, check_cache

out = Path('F:/build/probe-distance-validation')
assert (out/'integration.json').exists() and (out/'load.json').exists()
cache = out/'wall.shprobe'
report = {'cache':check_cache(cache)}
lines = cache.read_text(encoding='utf-8').splitlines()
metadata=lines[6].split()
texel_local=lines[0]=='FALCOR_PROBE_SH 3'
if texel_local: assert metadata.pop(0)=='texel_local_uv_point'
resolution, sampling_parameter, distance_range, width, height = map(float,metadata)
r,w,h = int(resolution),int(width),int(height)
tile=r+2
columns=w//tile
data=[tuple(map(float,line.split())) for line in lines[lines.index('DISTANCE_MOMENTS')+1:]]
def texel(probe,x,y):
    return data[(probe//columns*tile+y+1)*w+probe%columns*tile+x+1]
for probe in range(8):
    for j in range(r):
        assert texel(probe,-1,j) == ((1,1) if texel_local else texel(probe,0,r-1-j))
        assert texel(probe,r,j) == ((1,1) if texel_local else texel(probe,r-1,r-1-j))
        assert texel(probe,j,-1) == ((1,1) if texel_local else texel(probe,r-1-j,0))
        assert texel(probe,j,r) == ((1,1) if texel_local else texel(probe,r-1-j,r-1))
    assert texel(probe,-1,-1) == ((1,1) if texel_local else texel(probe,r-1,r-1))
distance_max=distance_range*math.sqrt(1+1.2**2+1)
# Probe 0 at x=-0.5: +X strikes the divider's x=-0.02 face, 0.48 units away.
mean=sum(texel(0,r-1,j)[0] for j in (r//2-1,r//2))*.5*distance_max
assert .45 < mean < .57,mean
report['positive_x_mean_distance']=mean

def read(tag):
    paths=list(out.glob(tag+'.Probes.probeLighting.*.exr'))
    assert len(paths)==1,paths
    return read_exr(paths[0])[2]
on,off,loaded=read('bake-on'),read('off'),read('load-on')
error=max(abs(a-b) for a,b in zip(on,loaded))
assert error < 1e-4,error
ratio=sum(on)/sum(off)
assert ratio < .35,ratio
for path in out.glob('*.exr'): read_exr(path)
report.update({'bake_load_max_error':error,'dark_room_mean_on_off_ratio':ratio,
    'octahedron_padding':'unused for integer texel fetch' if texel_local else 'matches reflected interior at all edges/corners',
    'note':'A controlled opaque wall test, not a guarantee for arbitrary scene geometry.'})
(out/'results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
