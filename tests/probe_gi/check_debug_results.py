"""Check finite debug HDRs and invariance of the non-debug lighting output."""
import json
from pathlib import Path
from check_results import read_exr

output = Path("F:/build/probe-debug-validation")
assert (output / "integration.json").exists()
images = {p.name: read_exr(p)[2] for p in output.glob("*.exr")}
assert len(images) >= 28


def image(tag, channel="Probes.color"):
    matches = [pixels for name, pixels in images.items() if name.startswith(f"{tag}.{channel}.")]
    assert len(matches) == 1, tag
    return matches[0]


baseline = image("baseline")
report = {"finite_hdr_count": len(images)}
for tag in ("debug-no-overlay", "restored"):
    error = max(abs(a - b) for a, b in zip(baseline, image(tag)))
    assert error == 0, (tag, error)
    report[f"{tag}_max_abs_error"] = error

probe_error = max(abs(a-b) for a,b in zip(image("baseline", "Probes.probeLighting"), image("links-xray", "Probes.probeLighting")))
assert probe_error == 0
report["overlay_probeLighting_error"] = probe_error
for tag in ("links-xray", "depth-tested", "irradiance", "albedo", "normals", "cells", "clamp", "radiance-negative"):
    assert max(abs(a-b) for a,b in zip(baseline, image(tag))) > 0, tag
depth_difference = sum(a != b for a,b in zip(image("links-xray"), image("depth-tested")))
assert depth_difference > 0
report["xray_depth_different_channels"] = depth_difference
(output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
