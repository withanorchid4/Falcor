"""Compare cached DDGI moments at the original GPU-recorded pixel coordinates.

Read-only offline reconstruction, not a new GPU capture. All maps share physical
units and display ranges. Validate reconstructed moments against the DDGI GPU
inspection records before writing figures.
"""
from pathlib import Path
import argparse
import csv
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'build/probe-variance-14-diagnosis'
parser = argparse.ArgumentParser()
parser.add_argument('--sweep', type=Path, help='Analyze a filter_strength.py output instead of the original DDGI comparison')
args = parser.parse_args()
RUN = args.sweep or ROOT / 'build/probe-ddgi-alignment/verified'
OUT = RUN / 'moments'
OUT.mkdir(exist_ok=True)
CASE = ROOT / 'build/probe-issues/20260924-104702-ae8fb0'
snapshot = json.loads((CASE / 'snapshot.json').read_text())
report = json.loads((OLD / 'analysis/report.json').read_text())
gpu = json.loads((RUN / 'result.json').read_text())
W, H = snapshot['resolution']
font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 18)
small = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 15)
variants = [
    ('baseline', 'Original texel-local / range 2', CASE / 'probes.shprobe'),
    ('angular-only', 'Angular filter / range 2', RUN / 'angular-only/rebaked.shprobe'),
    ('angular-range15', 'Angular filter / range 1.5', RUN / 'angular-range15/rebaked.shprobe'),
]
if args.sweep:
    variants = [(f'p{p}', f'Angular p={p} / range 1.5',
                 ROOT/'build/probe-ddgi-alignment/verified/angular-range15/rebaked.shprobe' if p == 50 else RUN/f'p{p}/rebaked.shprobe')
                for p in (50, 25, 10, 5)]
if args.sweep and (RUN/'variants.json').exists():
    variants = [(v['tag'],v['label'],ROOT/v['cache']) for v in json.loads((RUN/'variants.json').read_text())]
columns = len(variants)


def load(group, corner):
    return np.fromfile(OLD / f'g{group}-c{corner}.f32', dtype='<f4').reshape(H, W, 3)


ids = np.stack([load(3, c)[..., 0].astype(int) for c in range(8)])
uvs = np.stack([load(3, c)[..., 1:] for c in range(8)])
query_distances = np.stack([load(2, c)[..., 2] for c in range(8)])


class Cache:
    def __init__(self, path):
        lines = path.read_text().splitlines()
        cfg = lines[6].split()
        self.n, self.scale = int(cfg[1]), float(cfg[3])
        self.aw, ah = map(int, cfg[4:6])
        self.atlas = np.loadtxt(lines[lines.index('DISTANCE_MOMENTS') + 1:]).reshape(ah, self.aw, 2)
        self.bounds = np.array(list(map(float, lines[5].split())))
        self.counts = np.array(list(map(int, lines[4].split()[:3])))
        self.spacing = (self.bounds[3:] - self.bounds[:3]) / (self.counts - 1)
        self.D = self.scale * np.linalg.norm(self.spacing)
        assert self.n == 14

    def sample(self, probe, uv):
        p = np.clip(np.asarray(uv, dtype=np.float64), 0, 1) * self.n - .5
        ij = np.floor(p).astype(int)
        t = p - ij
        m = np.zeros_like(p)
        tile = self.n + 2
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            x, y = ij[..., 0] + dx, ij[..., 1] + dy
            flip = (x < 0) | (x >= self.n)
            x, y = np.clip(x, 0, self.n - 1), np.where(flip, self.n - 1 - y, y)
            flip = (y < 0) | (y >= self.n)
            y, x = np.clip(y, 0, self.n - 1), np.where(flip, self.n - 1 - x, x)
            a = (t[..., 0] if dx else 1 - t[..., 0]) * (t[..., 1] if dy else 1 - t[..., 1])
            m += a[..., None] * self.atlas[(probe // (self.aw // tile)) * tile + 1 + y,
                                          (probe % (self.aw // tile)) * tile + 1 + x]
        mu, m2 = m[..., 0] * self.D, m[..., 1] * self.D ** 2
        return {'mu': mu, 'm2': m2, 'mu2': mu ** 2, 'variance': m2 - mu ** 2}

    def visibility(self, values, distance, ddgi=False):
        variance = (abs(values['variance']) if ddgi else
                    np.maximum(values['variance'], 0) + snapshot['probeSettings']['varianceBase'] * self.D ** 2)
        delta = np.maximum(distance - values['mu'], 0)
        p = np.divide(variance, variance + delta ** 2, out=np.ones_like(delta), where=(variance + delta ** 2) > 0)
        return p ** 3


caches = {tag: Cache(path) for tag, _, path in variants}
validation = {}
for tag, cache in caches.items():
    errors = {'mean': 0., 'variance': 0.}
    for rec in gpu['points'][tag]:
        x, y = rec['pixel']
        info = rec['data']
        for c in range(8):
            probe = info['probe' + str(c)]
            assert probe == ids[c, y, x], (tag, c, x, y)
            values = cache.sample(probe, uvs[c, y, x])
            for name, field, key in [('mean', 'mu', 'meanDistance'), ('variance', 'variance', 'distanceVariance')]:
                errors[name] = max(errors[name], abs(float(values[field]) - info[key + str(c)]))
    assert max(errors.values()) < 2e-5, (tag, errors)
    validation[tag] = errors

all_values = []
for region in report['edges']:
    probe = region['A']['id']
    mask = ids == probe
    valid = mask.any(0)
    uv = (uvs * mask[..., None]).sum(0)
    distance = (query_distances * mask).sum(0)
    px, py = region['A']['pixel']
    x0, y0 = max(0, min(W - 320, px - 160)), max(0, min(H - 190, py - 95))
    box = (x0, y0, x0 + 320, y0 + 190)
    canvas = Image.new('RGB', (320 * columns, 58 + 4 * 222), (22, 22, 22))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 4), f"{region['region']} / Probe {probe} / same pixels, same bias, 14 x 14", font=font, fill='white')
    for col, (tag, label, _) in enumerate(variants):
        cache = caches[tag]
        values = cache.sample(probe, uv)
        visibility = cache.visibility(values, distance, ddgi=bool(args.sweep))
        draw.text((col * 320 + 5, 31), label, font=small, fill='white')
        rows = [('m2 = E[d^2] : linear [0,1]', values['m2'], 'm2'),
                ('mu^2 = E[d]^2 : linear [0,1]', values['mu2'], 'mu2'),
                ('variance : log10 [-6,0]', (np.log10(np.maximum(values['variance'], 1e-10)) + 6) / 6, 'variance'),
                ('raw visibility : linear [0,1]', visibility, 'visibility')]
        for row, (title, v, key) in enumerate(rows):
            rgb = np.repeat(np.uint8(np.clip(v, 0, 1) * 255 + .5)[..., None], 3, axis=-1)
            rgb[~valid] = [40, 20, 40]
            im = Image.fromarray(rgb)
            im.save(OUT / f'{tag}-probe{probe}-{key}.png')
            crop = im.crop(box)
            cd = ImageDraw.Draw(crop)
            cx, cy = px - x0, py - y0
            cd.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline=(255, 90, 25))
            y = 58 + row * 222
            draw.text((col * 320 + 3, y), title, font=small, fill='white')
            canvas.paste(crop, (col * 320, y + 25))
        for side in ('A', 'B'):
            q = region[side]
            v = cache.sample(probe, q['uv'])
            all_values.append({'region': region['region'], 'probe': probe, 'variant': tag, 'side': side,
                               'pixel': q['pixel'], **{k: float(x) for k, x in v.items()},
                               'visibility': float(cache.visibility(v, np.array(q['d']), ddgi=bool(args.sweep))),
                               'ddgi_raw_visibility': float(cache.visibility(v, np.array(q['d']), ddgi=True))})
    canvas.save(OUT / f"{region['region']}-moments-comparison.png")
    canvas.crop((0, 0, 320 * columns, 58 + 2 * 222)).save(OUT / f"{region['region']}-m2-mu2.png")

# Continuous world-space line through the same neighboring pixels, to distinguish
# a steep continuous transition / derivative kink from a discontinuous value.
edge = next(r for r in report['edges'] if r['region'] == 'left')
probe = edge['A']['id']
x, y = edge['A']['pixel']
xb, yb = edge['B']['pixel']
positions, normals = load(7, 0).astype(np.float64), load(8, 0).astype(np.float64)
P0, P1, normal = positions[y, x], positions[yb, xb], normals[y, x]
cache = caches[variants[0][0]]
counts = cache.counts
origin = cache.bounds[:3] + cache.spacing * np.array([probe % counts[0], (probe // counts[0]) % counts[1], probe // (counts[0] * counts[1])])
assert snapshot['probeSettings']['viewBias'] == 0


def line_query(t):
    Q = P0 + np.asarray(t)[..., None] * (P1 - P0) + cache.spacing.min() * snapshot['probeSettings']['normalBias'] * normal
    delta = Q - origin
    distance = np.linalg.norm(delta, axis=-1)
    p = delta / np.sum(abs(delta), axis=-1)[..., None]
    xy = np.where((p[..., 2] < 0)[..., None], (1 - abs(p[..., [1, 0]])) * np.where(p[..., :2] >= 0, 1, -1), p[..., :2])
    return xy * .5 + .5, distance


lo, hi = 0., 1.
for _ in range(60):
    mid = (lo + hi) / 2
    if line_query(mid)[0][1] > 1.5 / 14: lo = mid
    else: hi = mid
cross = (lo + hi) / 2
t = np.linspace(-2, 3, 5001)
uv, distance = line_query(t)
fields, slopes = {}, {}
for tag, cache in caches.items():
    v = cache.sample(probe, uv)
    v['visibility'] = cache.visibility(v, distance, ddgi=bool(args.sweep))
    fields[tag] = v
    with (OUT / (tag + '-line.csv')).open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['screen_x', 'm2', 'mu2', 'variance', 'visibility'])
        writer.writerows(zip(x + t, *(v[k] for k in ('m2', 'mu2', 'variance', 'visibility'))))
    epsilon = 1e-4
    vv = cache.sample(probe, line_query(np.array([cross - epsilon, cross, cross + epsilon]))[0])
    slopes[tag] = {key: {'left': float((vv[key][1] - vv[key][0]) / epsilon),
                         'right': float((vv[key][2] - vv[key][1]) / epsilon)}
                   for key in ('m2', 'mu2', 'variance')}

canvas = Image.new('RGB', (1050, 1040), 'white')
draw = ImageDraw.Draw(canvas)
draw.text((20, 8), 'Probe 375: same surface line through A=520 and B=521 (y=417)', font=font, fill='black')
colors = {'baseline': (40, 100, 200), 'angular-only': (215, 120, 20), 'angular-range15': (35, 155, 90)}
colors.update({'p50':(40,100,200), 'p25':(215,120,20), 'p10':(35,155,90), 'p5':(155,50,160)})
palette=[(40,100,200),(215,120,20),(35,155,90),(155,50,160),(210,50,50),(20,150,180)]
for i, (tag, label, _) in enumerate(variants):
    colors.setdefault(tag,palette[i%len(palette)])
    draw.text((20 + i * (1020 // columns), 35), label, font=small, fill=colors[tag])
moment_ymax = float(np.ceil(max(float(v[k].max()) for v in fields.values() for k in ('m2', 'mu2')) * 10) / 10) if args.sweep else .27
for row, (key, label, ymin, ymax) in enumerate([
        ('m2', 'm2 (world units squared)', .14, moment_ymax),
        ('mu2', 'mu^2 (world units squared)', .14, moment_ymax),
        ('variance', 'Variance: log10 scale', -5, 0 if args.sweep else -1),
        ('visibility', 'Raw moment visibility (' + ('DDGI' if args.sweep else 'legacy') + ' formula)', 0, 1)]):
    left, top, width, height = 100, 95 + row * 230, 900, 170
    X = lambda z: left + (z + 2) / 5 * width
    Y = lambda z: top + height * (1 - (z - ymin) / (ymax - ymin))
    draw.text((left, top - 25), label, font=small, fill='black')
    for z in np.linspace(ymin, ymax, 5):
        yp = Y(z)
        draw.line((left, yp, left + width, yp), fill=(225, 225, 225))
        draw.text((14, yp - 8), f'1e{z:g}' if key == 'variance' else f'{z:.3f}', font=small, fill='black')
    for z in range(-2, 4):
        xp = X(z)
        draw.line((xp, top, xp, top + height), fill=(230, 230, 230))
        draw.text((xp - 14, top + height + 4), str(x + z), font=small, fill='black')
    for tag, _, _ in variants:
        v = fields[tag][key]
        if key == 'variance': v = np.log10(np.maximum(v, 1e-30))
        pts = list(zip(X(t).tolist(), np.clip(Y(v), top, top + height).tolist()))
        draw.line(pts, fill=colors[tag], width=2)
    draw.line((X(cross), top, X(cross), top + height), fill=(180, 40, 40), width=1)
draw.text((100, 1010), f'Red line = texel center crossing, x={x + cross:.6f}; A/B are neighboring pixels.', font=small, fill='black')
canvas.save(OUT / 'probe375-line-comparison.png')
result = {'method': 'CPU reconstruction from caches and unchanged GPU-recorded UVs; no tone mapping',
          'gpu_validation_max_errors': validation, 'samples': all_values,
          'texel_center_screen_x': x + cross, 'slopes_per_screen_pixel': slopes,
          'settings_preserved': {'resolution': 14, 'normalBias': snapshot['probeSettings']['normalBias'], 'viewBias': 0}}
(OUT / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps({'validation': validation, 'left_AB': [v for v in all_values if v['region'] == 'left'], 'slopes': slopes}, indent=2))
