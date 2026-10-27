"""Check captured WRC wireframes without rerunning the renderer."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probe_gi"))
from check_results import read_exr

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
args = parser.parse_args()
out = args.output
assert not (out / "failure.txt").exists(), (out / "failure.txt").read_text(encoding="utf-8")
record = json.loads((out / "smoke.json").read_text(encoding="utf-8"))
assert record["passed"]


def read(tag, channel):
    paths = list(out.glob(f"{tag}.DDGI.{channel}.*.exr"))
    assert len(paths) == 1, (tag, channel, paths)
    return read_exr(paths[0])


_, _, reference = read("off", "indirect")
_, _, base = read("off", "color")
errors = {}
for tag in ("on", "xray", "empty-lod", "transparent", "off-again"):
    _, _, indirect = read(tag, "indirect")
    assert len(indirect) == len(reference)
    error = max(abs(a - b) for a, b in zip(indirect, reference))
    errors[tag] = error
    assert error == 0, (tag, "Overlay changed frozen indirect lighting", error)

differences = {}
for tag in ("on", "xray", "empty-lod", "transparent", "off-again"):
    _, _, color = read(tag, "color")
    differences[tag] = sum(abs(a - b) > 1e-6 for a, b in zip(color, base))
    if tag in ("on", "xray"):
        assert differences[tag] > 0, (tag, "Missing visible overlay")
    else:
        assert differences[tag] == 0, (tag, "Unexpected overlay pixels")

assert read("resize", "indirect")[:2] == (401, 301)
finite = 0
for path in out.glob("*.exr"):
    read_exr(path)
    finite += 1
report = {"passed": True, "scene": record["scene"], "finite_hdr": finite,
          "frozen_indirect_max_errors": errors, "changed_rgb_components": differences}
(out / "checked.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
