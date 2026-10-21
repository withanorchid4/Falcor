"""Check NRD/DDGI composition, bypass, dynamic response and paired variance."""
import argparse
import json
import math
from pathlib import Path

from check_rtxdi_results import close_arrays, mean, read_exr, timing_summary


def variance_metrics(read, scene, channel):
    running_mean, running_m2 = None, None
    for index in range(32):
        tag = scene + f"-noise-{index:02d}"
        color = read(tag, channel)
        emission = read(tag, "DirectLighting.emission")
        direct = [a - b for a, b in zip(color, emission)]
        size = len(direct) // 3
        luminance = [0.2126 * direct[i] + 0.7152 * direct[size + i] + 0.0722 * direct[2 * size + i] for i in range(size)]
        if running_mean is None:
            running_mean, running_m2 = luminance, [0.0] * size
        else:
            for i, value in enumerate(luminance):
                delta = value - running_mean[i]
                running_mean[i] += delta / (index + 1)
                running_m2[i] += delta * (value - running_mean[i])
    variance_mean = mean([max(0.0, value / 31) for value in running_m2])
    radiance_mean = mean(running_mean)
    assert radiance_mean > 1e-6, (scene, channel, "No reflected direct light")
    return {
        "sample_count": 32, "surface_direct_luminance_mean": radiance_mean,
        "mean_pixel_temporal_variance": variance_mean,
        "rms_temporal_standard_deviation": math.sqrt(variance_mean),
        "relative_rms_temporal_standard_deviation": math.sqrt(variance_mean) / radiance_mean,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output
    integration = json.loads((out / "integration.json").read_text(encoding="utf-8"))
    report = {"finite_hdr_captures": 0, "scenes": {}, "checks": integration["checks"],
              "composition_max_abs_error": 0.0, "bypass_max_abs_error": 0.0, "note": integration["note"]}

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
        filtered, raw = outputs["DirectModulate.output"], outputs["DirectLighting.color"]
        if record["check"] == "indirect":
            close_arrays(color, indirect, tag + " indirect-only", absolute=1e-6, relative=0)
        else:
            expected = [a + b for a, b in zip(filtered, indirect)]
            error = close_arrays(color, expected, tag + " composition")
            report["composition_max_abs_error"] = max(report["composition_max_abs_error"], error)
        if record["check"] == "direct":
            assert max(map(abs, indirect)) == 0, (tag, "disabled GI is nonzero")
        if record["check"] == "bypass":
            # The denoiser output is RGBA16Float even when disabled; tolerate
            # demodulation/remodulation rounding, not percent-scale changes.
            error = close_arrays(filtered, raw, tag + " bypass", absolute=2e-4, relative=2e-3)
            report["bypass_max_abs_error"] = max(report["bypass_max_abs_error"], error)
        assert max(color) > 0 and max(raw) > 0 and max(filtered) > 0, (tag, "Black image")

    for name in ("cornell", "room"):
        frozen = read(name + "-frozen")
        frozen_error = 0.0
        stable_tags = [
            "nrd-disabled-first", "nrd-disabled-settled", "nrd-enabled-first", "nrd-enabled-settled",
            "nrd-reset-first", "nrd-reset-settled", "indirect-only", "switch-settled",
        ] + ["switch-" + graph for graph in ("PathTracer", "PathTracerNRD", "TraditionalProbeGI")]
        stable_tags += [f"noise-{index:02d}" for index in (0, 31)]
        for suffix in stable_tags:
            error = close_arrays(read(name + "-" + suffix), frozen, name + " frozen " + suffix,
                                 absolute=1e-6, relative=0)
            frozen_error = max(frozen_error, error)
        noise = {mode: variance_metrics(read, name, channel) for mode, channel in
                 (("raw", "DirectLighting.color"), ("filtered", "DirectModulate.output"))}
        ratio = noise["filtered"]["mean_pixel_temporal_variance"] / max(noise["raw"]["mean_pixel_temporal_variance"], 1e-20)
        dynamic = {}
        for mode, channel in (("raw", "DirectLighting.color"), ("filtered", "DirectModulate.output")):
            means = {}
            for tag in ("camera-return-settled", "dim-settled", "light-restored"):
                color = read(name + "-" + tag, channel)
                emission = read(name + "-" + tag, "DirectLighting.emission")
                means[tag] = mean([a - b for a, b in zip(color, emission)])
            assert means["camera-return-settled"] > 1e-6, (name, mode, "Missing direct light", means)
            assert means["dim-settled"] < means["camera-return-settled"] * 0.8, (name, mode, "Dimming failed", means)
            assert means["light-restored"] > means["dim-settled"] * 1.25, (name, mode, "Restore failed", means)
            dynamic[mode] = means
        report["scenes"][name] = {
            "frozen_indirect_max_abs_error": frozen_error, "noise": noise,
            "filtered_to_raw_temporal_variance_ratio": ratio,
            "dynamic_surface_direct_rgb_means": dynamic,
            "gpu_timings": timing_summary(out / integration["scenes"][name]["timing"]["profiler"]),
            "run_metadata": integration["scenes"][name],
        }
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
