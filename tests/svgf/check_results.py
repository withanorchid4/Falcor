"""Finite HDRs, bypass fidelity and static temporal variation (not accuracy)."""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probe_gi"))
from check_results import read_exr

out = Path("F:/build/svgf-validation")
assert (out / "integration.json").exists()


def read(tag, channel, require_finite=True):
    files = list(out.glob(f"{tag}.{channel}.*.exr"))
    assert len(files) == 1, (tag, channel, files)
    return read_exr(files[0], require_finite=require_finite)


report = {"finite_hdr_count": 0, "upstream_nonfinite_channels": {}}
for path in out.glob("*.exr"):
    pixels = read_exr(path, require_finite=False)[2]
    invalid = sum(not math.isfinite(v) for v in pixels)
    if invalid:
        assert ".SVGF." not in path.name, f"Non-finite filtered HDR: {path}"
        report["upstream_nonfinite_channels"][path.name] = invalid
    else:
        report["finite_hdr_count"] += 1

# Bypass uses RGBA32Float, matching the source.
raw = read("disabled", "PathTracer.color")[2]
filtered = read("disabled", "SVGF.Filtered image")[2]
relative = max(abs(a-b) / max(1.0, abs(a)) for a,b in zip(raw,filtered))
assert relative < 1e-6, relative
report["bypass_max_scaled_error"] = relative


raw_images = [read("room" + str(i), "PathTracer.color", False)[2] for i in range(8)]
valid_indices = [j for j in range(len(raw_images[0])) if all(math.isfinite(im[j]) for im in raw_images)]
report["temporal_metric_excluded_channels"] = len(raw_images[0]) - len(valid_indices)


def variation(images):
    # log1p reduces the domination of rare high-energy fireflies.
    total = sum((math.log1p(max(0,a))-math.log1p(max(0,b)))**2
                for first,second in zip(images,images[1:])
                for j in valid_indices for a,b in [(first[j],second[j])])
    return total / (len(valid_indices) * 7)


raw_variation = variation(raw_images)
filtered_variation = variation([read("room" + str(i), "SVGF.Filtered image")[2] for i in range(8)])
assert filtered_variation < raw_variation, (raw_variation, filtered_variation)
report["raw_temporal_log_mse"] = raw_variation
report["svgf_temporal_log_mse"] = filtered_variation
report["variation_ratio"] = filtered_variation / raw_variation
assert read("resized", "SVGF.Filtered image")[:2] == (400, 300)
report["note"] = "Temporal smoothness only; not error against converged ground truth."
(out / "results.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
