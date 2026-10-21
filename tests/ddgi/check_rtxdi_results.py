"""Check same-frame RTXDI/DDGI composition and report raw temporal variance.

All math uses linear HDR. Temporal variance is reported rather than used as a
quality pass/fail criterion; it cannot distinguish reservoir correlation or bias
from true accuracy without a reference image.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "probe_gi"))
from check_results import read_exr


def close_arrays(actual, expected, label, absolute=2e-5, relative=2e-6):
    assert len(actual) == len(expected), label
    maximum = 0.0
    for a, b in zip(actual, expected):
        error = abs(a - b)
        maximum = max(maximum, error)
        assert error <= absolute + relative * max(abs(a), abs(b)), (label, a, b, error)
    return maximum


def mean(values):
    return sum(values) / len(values)


def noise_metrics(read, scene, mode):
    running_mean = None
    running_m2 = None
    for index in range(32):
        tag = scene + "-noise-" + mode + f"-{index:02d}"
        color = read(tag, "DDGI.color")
        indirect = read(tag, "DDGI.indirect")
        direct = [a - b for a, b in zip(color, indirect)]
        size = len(direct) // 3
        luminance = [0.2126 * direct[i] + 0.7152 * direct[size + i] + 0.0722 * direct[2 * size + i] for i in range(size)]
        if running_mean is None:
            running_mean = luminance
            running_m2 = [0.0] * size
        else:
            for i, value in enumerate(luminance):
                delta = value - running_mean[i]
                running_mean[i] += delta / (index + 1)
                running_m2[i] += delta * (value - running_mean[i])
    variance = [max(0.0, value / 31.0) for value in running_m2]
    radiance_mean = mean(running_mean)
    variance_mean = mean(variance)
    return {
        "sample_count": 32,
        "direct_luminance_mean": radiance_mean,
        "mean_pixel_temporal_variance": variance_mean,
        "rms_temporal_standard_deviation": math.sqrt(variance_mean),
        "relative_rms_temporal_standard_deviation": math.sqrt(variance_mean) / max(abs(radiance_mean), 1e-12),
    }


def timing_summary(path):
    capture = json.loads(path.read_text(encoding="utf-8"))
    lanes = {}
    for name, lane in capture["events"].items():
        if name.endswith("/gpu_time"):
            values = lane["records"][5:]
            if values:
                lanes[name] = {"median_ms": statistics.median(values), "samples": len(values)}
    return lanes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output
    integration = json.loads((out / "integration.json").read_text(encoding="utf-8"))
    report = {"finite_hdr_captures": 0, "scenes": {}, "checks": integration["checks"],
              "composition_max_abs_error": 0.0, "note": integration["timing_note"]}

    def read(tag, channel="DDGI.indirect"):
        paths = list(out.glob(f"{tag}.{channel}.*.exr"))
        assert len(paths) == 1, (tag, channel, paths)
        width, height, pixels = read_exr(paths[0])
        assert [width, height] == integration["captures"][tag]["dimensions"], (tag, width, height)
        assert min(pixels) >= -1e-5, (tag, channel, min(pixels))
        return pixels

    for tag, record in integration["captures"].items():
        outputs = {channel: read(tag, channel) for channel in record["channels"]}
        report["finite_hdr_captures"] += len(outputs)
        color, indirect = outputs["DDGI.color"], outputs["DDGI.indirect"]
        kind = record["check"]
        if kind in ("composite", "direct"):
            direct = outputs["DirectLighting.color"]
            expected = [a + b for a, b in zip(direct, indirect)]
            error = close_arrays(color, expected, tag + " composition")
            report["composition_max_abs_error"] = max(report["composition_max_abs_error"], error)
        if kind == "indirect":
            close_arrays(color, indirect, tag + " indirect-only", absolute=1e-6, relative=0)
        if kind in ("direct", "zero"):
            assert max(map(abs, indirect)) == 0, (tag, "disabled indirect is nonzero")
        if kind == "zero":
            assert max(map(abs, color)) == 0, (tag, "all-off color is nonzero")
        if kind != "zero":
            assert max(color) > 0, (tag, "black color")

    for name in ("cornell", "room"):
        frozen = read(name + "-frozen")
        frozen_error = 0.0
        # Compare only unchanged camera/light states. Camera movement changes
        # screen-space irradiance queries even when the probe textures freeze.
        for suffix in ("indirect-only", "legacy", "restored"):
            frozen_error = max(frozen_error, close_arrays(read(name + "-" + suffix), frozen,
                               name + " " + suffix + " frozen indirect", absolute=1e-6, relative=0))
        for mode in ("legacy", "rtxdi"):
            for index in (0, 31):
                close_arrays(read(name + "-noise-" + mode + f"-{index:02d}"), frozen,
                             name + " " + mode + " noise indirect", absolute=1e-6, relative=0)
        noise = {mode: noise_metrics(read, name, mode) for mode in ("legacy", "rtxdi")}
        base = noise["legacy"]["mean_pixel_temporal_variance"]
        ratio = noise["rtxdi"]["mean_pixel_temporal_variance"] / max(base, 1e-20)
        # RTXDIPass.color includes visible emission and environment background.
        # Their trivial intensity response cannot prove that sampled lighting
        # follows changes, so test only reflected direct illumination.
        direct_means = {}
        total_means = {}
        for tag in ("camera-return-settled", "dim-settled", "light-restored"):
            color = read(name + "-" + tag, "DirectLighting.color")
            emission = read(name + "-" + tag, "DirectLighting.emission")
            direct_means[tag] = mean([a - b for a, b in zip(color, emission)])
            total_means[tag] = mean(color)
        assert direct_means["camera-return-settled"] > 1e-6, (name, "Missing reflected direct light", direct_means)
        assert direct_means["dim-settled"] < direct_means["camera-return-settled"] * 0.8, (name, direct_means)
        assert direct_means["light-restored"] > direct_means["dim-settled"] * 1.25, (name, direct_means)
        timings = {mode: timing_summary(out / data["profiler"])
                   for mode, data in integration["scenes"][name]["noise"].items()}
        report["scenes"][name] = {
            "frozen_indirect_max_abs_error": frozen_error,
            "noise": noise, "rtxdi_to_legacy_temporal_variance_ratio": ratio,
            "dynamic_surface_direct_rgb_means": direct_means,
            "dynamic_direct_plus_emission_rgb_means": total_means,
            "gpu_timings": timings, "run_metadata": integration["scenes"][name],
        }
    report["fallback"] = integration["fallback"]
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
