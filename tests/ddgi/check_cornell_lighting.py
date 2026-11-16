"""Check light configuration, all-off startup, and live light edits using GPU captures."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probe_gi"))
from check_results import read_exr

out = Path(sys.argv[1])
assert not (out / "failure.txt").exists(), (out / "failure.txt").read_text(encoding="utf-8")
stats = json.loads((out / "stats.json").read_text())
results = {}
images = {}
for tag in ("sun", "point", "off", "live-red-point"):
    values = {}
    for channel in ("DDGI.indirect", "DDGI.color", "DirectLighting.diffuseIllumination"):
        _, _, pixels = read_exr(next(out.glob(f"{tag}.{channel}.*.exr")))
        values[channel] = pixels
    images[tag] = values
    assert stats["cases"][tag]["finite"], tag
    results[tag] = {"indirectMean": sum(values["DDGI.indirect"]) / len(values["DDGI.indirect"]),
                    "directMean": sum(values["DirectLighting.diffuseIllumination"]) / len(values["DirectLighting.diffuseIllumination"])}
for tag in ("sun", "point", "live-red-point"):
    assert results[tag]["indirectMean"] > 1e-4 and results[tag]["directMean"] > 1e-4, results
assert max(map(abs, images["off"]["DDGI.color"])) < 1e-6, "Turning all lights off must produce black"
red = images["live-red-point"]["DDGI.color"]
assert max(map(abs, red[len(red)//3:])) < 1e-5, "A red-only source must not introduce green/blue energy"
sun, point = images["sun"]["DDGI.indirect"], images["point"]["DDGI.indirect"]
assert sum(abs(a-b) for a,b in zip(sun,point))/len(sun) > 1e-4, "Point and directional lighting must differ"
assert "(Error)" not in (out / "mogwai.log").read_text(encoding="utf-8", errors="replace")
(out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
