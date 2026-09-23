"""Check official NRD + DLSS captures; smoothness is not ground-truth accuracy."""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'probe_gi'))
from check_results import read_exr

out = Path('F:/build/nrd-dlss-validation')
assert (out/'integration.json').exists()
report = {'filtered_hdr_count': 0, 'upstream_nonfinite_channels': {}}
for path in out.glob('*.exr'):
    w,h,pixels = read_exr(path, require_finite=False)
    invalid = sum(not math.isfinite(x) for x in pixels)
    if '.DLSS.output.' in path.name:
        assert invalid == 0, (path, invalid)
        assert sum(max(0,x) for x in pixels)/len(pixels) > .0001, path
        report['filtered_hdr_count'] += 1
        if path.name.startswith('resize.'):
            assert (w,h) == (400,300)
        else:
            assert (w,h) == (640,360)
    elif invalid:
        report['upstream_nonfinite_channels'][path.name] = invalid

def read(tag,channel):
    files=list(out.glob(f'{tag}.{channel}.*.exr'))
    assert len(files)==1,files
    return read_exr(files[0],require_finite=False)[2]

raw=[read('noise'+str(i),'PathTracer.color') for i in range(8)]
filtered=[read('noise'+str(i),'DLSS.output') for i in range(8)]
valid=[j for j in range(len(raw[0])) if all(math.isfinite(im[j]) for im in raw)]
def variation(images):
    return sum((math.log1p(max(0,a[j]))-math.log1p(max(0,b[j])))**2
               for a,b in zip(images,images[1:]) for j in valid)/(len(valid)*7)
report['excluded_temporal_channels']=len(raw[0])-len(valid)
report['raw_temporal_log_mse']=variation(raw)
report['nrd_temporal_log_mse']=variation(filtered)
assert report['nrd_temporal_log_mse'] < report['raw_temporal_log_mse'],report
report['note']='Official NRD input clamp and residual settings apply; not an unbiased accuracy comparison.'
(out/'results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
