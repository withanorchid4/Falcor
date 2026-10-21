"""Check linear HDR DDGI output and broad response against PathTracer.

This checks finite nonzero output, frozen history and response direction. It does
not claim image equivalence with a full specular/transmissive path tracer.
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probe_gi"))
from check_results import read_exr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output
    integration = json.loads((out / "integration.json").read_text(encoding="utf-8"))
    report = {"finite_hdr_captures": 0, "scenes": {}, "checks": integration["checks"]}
    for path in out.glob("*.DDGI.*.exr"):
        width, height, pixels = read_exr(path)
        assert all(v >= -1e-5 for v in pixels), (path.name, min(pixels))
        assert max(pixels) > 0, path.name
        assert (width, height) == ((400, 300) if path.name.startswith("resize.") else (320, 240))
        report["finite_hdr_captures"] += 1
    assert report["finite_hdr_captures"] >= 26, report

    def read(tag, channel="DDGI.indirect", require_finite=True):
        paths = list(out.glob(f"{tag}.{channel}.*.exr"))
        assert len(paths) == 1, (tag, channel, paths)
        return read_exr(paths[0], require_finite=require_finite)[2]

    def mean(pixels):
        return sum(max(0.0, v) for v in pixels) / len(pixels)

    for name in ("cornell", "room"):
        baseline, dim, restored = [read(name + "-" + tag) for tag in ("baseline", "dim-settled", "restored")]
        before, after = [read(name + "-freeze-" + tag) for tag in ("before", "after")]
        frozen_error = max(abs(a - b) for a, b in zip(before, after))
        assert frozen_error < 1e-6, (name, "frozen indirect changed", frozen_error)
        means = dict(zip(("baseline", "dim", "restored"), map(mean, (baseline, dim, restored))))
        assert means["baseline"] > 1e-6 and means["dim"] > 0, (name, means)
        assert means["dim"] < means["baseline"] * 0.8, (name, "GI did not follow dimming", means)
        assert means["restored"] > means["dim"] * 1.25, (name, "GI did not recover", means)
        reference = {}
        reference_invalid = {}
        for tag in ("baseline", "dim"):
            # Existing PathTracer/NRD tests document occasional upstream BSDF
            # nonfinite samples. Keep DDGI's finite requirement strict, but
            # report those reference channels instead of attributing them to DDGI.
            pixels = read(name + "-reference-" + tag, "AccumulatePass.output", require_finite=False)
            valid = [v for v in pixels if math.isfinite(v)]
            reference_invalid[tag] = len(pixels) - len(valid)
            assert len(valid) > len(pixels) * 0.99, (name, tag, "Unusable PathTracer reference")
            reference[tag] = mean(valid)
        assert reference["dim"] < reference["baseline"] * 0.8, (name, reference)
        # Record (do not gate on) absolute disagreement: surfaces and BSDF lobes
        # differ between the diffuse probe approximation and full path tracing.
        ddgi_color = mean(read(name + "-baseline", "DDGI.color"))
        report["scenes"][name] = {
            "indirect_mean": means, "frozen_max_abs_error": frozen_error,
            "ddgi_dim_ratio": means["dim"] / means["baseline"],
            "pathtracer_dim_ratio": reference["dim"] / reference["baseline"],
            "ddgi_color_to_pathtracer_mean_ratio": ddgi_color / reference["baseline"],
            "pathtracer_nonfinite_channels_excluded": reference_invalid,
            "features_enabled": integration["scenes"][name]["features_enabled"],
            "features_disabled": integration["scenes"][name]["features_disabled"],
            "rejected_samples": {
                stage: {key: value for key, value in data.items() if key.startswith("rejected")}
                for stage, data in integration["scenes"][name].items()
                if isinstance(data, dict)
            },
        }
    # At least one scene must provide actual geometric evidence that the SDK
    # features run. Merely serializing enable flags is not sufficient.
    enabled = [s["features_enabled"] for s in integration["scenes"].values()]
    assert any(s["relocatedProbes"] > 0 for s in enabled), "No probe relocation observed"
    assert any(s["activeProbes"] < s["totalProbes"] for s in enabled), "No probe classification observed"
    report["note"] = "Diffuse GI response smoke test; not an unbiased image-quality or performance benchmark."
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
