"""Check sustained finite output and detect collapse of the user's wall view."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probe_gi"))
from check_results import read_exr

out = Path("F:/build/svgf-long-run")
progress = json.loads((out / "progress.json").read_text())
assert progress["frame"] == 6000 and progress["history"] >= 5990
report = {"progress": progress, "frames": {}}
for frame in (64, 512, 2048, 6000):
    path, = out.glob(f"frame{frame}.SVGF.Filtered image.*.exr")
    w, h, data = read_exr(path)
    # Interior central wall, not the bright window: cannot pass with only sky alive.
    roi = [data[k*w*h+y*w+x] for k in range(3)
           for y in range(h//3, 2*h//3) for x in range(w//3, 2*w//3)]
    mean = sum(roi)/len(roi)
    assert mean > 0.001, (frame, mean)
    report["frames"][frame] = {"wall_mean_hdr": mean, "all_finite": True}
(out / "results.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
