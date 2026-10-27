"""Validate distance-LOD WRC and report probing, material dispatch, quality, and cost."""
import argparse
import json
import math
from pathlib import Path

from check_rtxdi_results import close_arrays, mean, read_exr, timing_summary


def metrics(actual, reference):
    assert len(actual) == len(reference)
    mse = mean([(a - b) ** 2 for a, b in zip(actual, reference)])
    reference_power = mean([v * v for v in reference])
    reference_mean = mean(reference)
    assert reference_power > 1e-12 and reference_mean > 1e-6, "Black indirect reference"
    return {
        "mean": mean(actual), "reference_mean": reference_mean,
        "mean_ratio": mean(actual) / reference_mean,
        "relative_rmse": math.sqrt(mse / reference_power),
        "max_absolute_error": max(abs(a - b) for a, b in zip(actual, reference)),
    }


def strict_comparison(actual, reference):
    """Keep the original tolerance, but retain diagnostics even when it fails."""
    assert len(actual) == len(reference)
    errors = [abs(a - b) for a, b in zip(actual, reference)]
    violations = sum(error > 2e-6 + 2e-5 * max(abs(a), abs(b))
                     for error, a, b in zip(errors, actual, reference))
    return {"max_absolute_error": max(errors), "mean_absolute_error": mean(errors),
            "violating_components": violations, "total_components": len(errors),
            "absolute_tolerance": 2e-6, "relative_tolerance": 2e-5}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output
    integration = json.loads((out / "integration.json").read_text(encoding="utf-8"))
    report = {"wrc_design": integration["wrc_design"],
              "finite_hdr_captures": 0, "composition_max_abs_error": 0.0,
              "scenes": {}, "checks": integration["checks"], "note": integration["note"]}
    if (out / "run.json").is_file():
        report["run"] = json.loads((out / "run.json").read_text(encoding="utf-8"))
    failures = []
    quality_failures = []
    summary = ["WRC validation: distance LOD, bounded probing, material indirect dispatch",
               "GPU timings are medians after discarding the first 5 captured records.",
               "Image metrics average four linear HDR frames with identical initial sample seeds."]

    def read(tag, channel="DDGI.indirect"):
        paths = list(out.glob(f"{tag}.{channel}.*.exr"))
        assert len(paths) == 1, (tag, channel, paths)
        width, height, pixels = read_exr(paths[0])
        assert [width, height] == integration["captures"][tag]["dimensions"], (tag, width, height)
        assert min(pixels) >= -1e-5, (tag, channel, min(pixels))
        return pixels

    def averaged(scene, mode):
        total = read(scene + "-" + mode + "-steady-0")
        for index in range(1, 4):
            pixels = read(scene + "-" + mode + f"-steady-{index}")
            total = [a + b for a, b in zip(total, pixels)]
        return [value / 4 for value in total]

    for tag, record in integration["captures"].items():
        outputs = {channel: read(tag, channel) for channel in record["channels"]}
        report["finite_hdr_captures"] += len(outputs)
        direct, indirect = outputs["DirectModulate.output"], outputs["DDGI.indirect"]
        expected = [a + b for a, b in zip(direct, indirect)]
        error = close_arrays(outputs["DDGI.color"], expected, tag + " composition")
        report["composition_max_abs_error"] = max(report["composition_max_abs_error"], error)
        assert max(outputs["DDGI.color"]) > 0 and max(direct) > 0, (tag, "Black composed/direct output")

    for name, scene in integration["scenes"].items():
        baseline = averaged(name, "baseline")
        entry = report["scenes"][name] = {"modes": {}, "run_metadata": scene}
        # Verify both cold start and the feedback loop, not only a steady image.
        split_error = 0.0
        entry["unshared_split_comparisons"] = {}
        for suffix in ("first", "steady-0", "steady-1", "steady-2", "steady-3"):
            comparison = strict_comparison(read(name + "-bypass-" + suffix), read(name + "-baseline-" + suffix))
            entry["unshared_split_comparisons"][suffix] = comparison
            split_error = max(split_error, comparison["max_absolute_error"])
            if comparison["violating_components"]:
                failures.append({"scene": name, "check": "unshared_split_" + suffix, "comparison": comparison})
        entry["unshared_split_max_abs_error"] = split_error
        for key in ("totalProbes", "activeProbes", "relocatedProbes", "updatedFrames"):
            a = scene["modes"]["baseline"]["steady"][-1][key]
            b = scene["modes"]["bypass"]["steady"][-1][key]
            if a != b:
                failures.append({"scene": name, "check": "split_path_state", "key": key, "baseline": a, "bypass": b})

        baseline_timing = timing_summary(out / scene["modes"]["baseline"]["timing"]["profiler"])
        ddgi_lane = "/onFrameRender/RenderGraphExe::execute()/DDGI/gpu_time"
        update_lane = "/onFrameRender/RenderGraphExe::execute()/DDGI/ProbeUpdate/gpu_time"
        base_ms = baseline_timing.get(ddgi_lane, {}).get("median_ms")
        base_update_ms = baseline_timing.get(update_lane, {}).get("median_ms")
        summary.append("\n" + name + ": mode | mean ratio | relative RMSE | DDGI ms | probe update ms | shading/valid | fallback/valid")
        for mode, metadata in scene["modes"].items():
            quality = metrics(averaged(name, mode), baseline)
            timings = timing_summary(out / metadata["timing"]["profiler"])
            mode_report = entry["modes"][mode] = {"quality": quality, "gpu_timings": timings}
            current_ms = timings.get(ddgi_lane, {}).get("median_ms")
            update_ms = timings.get(update_lane, {}).get("median_ms")
            if base_ms and current_ms:
                mode_report["ddgi_gpu_time_ratio_to_baseline"] = current_ms / base_ms
            if base_update_ms and update_ms:
                mode_report["probe_update_gpu_time_ratio_to_baseline"] = update_ms / base_update_ms
            final = metadata["steady"][-1]
            if final["wrcEnabled"]:
                counts = mode_report["mean_steady_counters"] = {
                    key: mean([frame[key] for frame in metadata["steady"]]) for key in (
                        "wrcValidRays", "wrcOccupiedEntries", "wrcShadedEntries", "wrcServedRays", "wrcFallbackRays",
                        "wrcTemporalReusedEntries", "wrcShadeEvaluations", "wrcShaderGroups", "wrcActiveEntries",
                        "wrcScheduledThreads", "wrcProbeSteps", "wrcProbeLimitFailures", "wrcLodRays",
                        "wrcCrossPrimitiveServedRays")}
                valid = counts["wrcValidRays"]
                evaluations = counts["wrcShadeEvaluations"]
                mode_report["shading_evaluation_ratio"] = evaluations / max(valid, 1)
                mode_report["shared_ray_fraction"] = (counts["wrcServedRays"] - counts["wrcOccupiedEntries"]) / max(valid, 1)
                mode_report["collision_fallback_fraction"] = counts["wrcFallbackRays"] / max(valid, 1)
                mode_report["cross_primitive_served_fraction"] = counts["wrcCrossPrimitiveServedRays"] / max(valid, 1)
                mode_report["lod_ray_fraction"] = counts["wrcLodRays"] / max(valid, 1)
                mode_report["observed_max_lod"] = max(frame["wrcMaxLod"] for frame in metadata["steady"])
                mode_report["probe_steps_per_valid_ray"] = counts["wrcProbeSteps"] / max(valid, 1)
                mode_report["dispatch_utilization"] = counts["wrcActiveEntries"] / max(counts["wrcScheduledThreads"], 1)
                mode_report["allocated_bytes"] = final["wrcAllocatedBytes"]
            # Earlier LOD transitions intentionally expose the tradeoff.
            # All normal/default operating modes retain the original quality gate.
            if mode in ("wrc", "lod1", "probe1", "collision", "temporal"):
                if not (quality["relative_rmse"] <= 0.4 and 0.7 <= quality["mean_ratio"] <= 1.3):
                    quality_failures.append({"scene": name, "mode": mode, "quality": quality,
                                             "required": "relative RMSE <= 0.4 and mean ratio in [0.7, 1.3]"})
            summary.append(f"{mode}: {quality['mean_ratio']:.4f} | {quality['relative_rmse']:.4f} | "
                           f"{current_ms if current_ms is not None else 'missing'} | "
                           f"{update_ms if update_ms is not None else 'missing'} | "
                           f"{mode_report.get('shading_evaluation_ratio', 1.0):.4f} | "
                           f"{mode_report.get('collision_fallback_fraction', 0.0):.4f}")

        probe16 = entry["modes"]["lod1"]["mean_steady_counters"]
        probe1 = entry["modes"]["probe1"]["mean_steady_counters"]
        comparison = entry["bounded_probing_comparison"] = {
            "max_lod": 1, "table_size": scene["modes"]["lod1"]["settings"]["wrcTableSize"],
            "probe16_fallback_rays": probe16["wrcFallbackRays"], "probe1_fallback_rays": probe1["wrcFallbackRays"],
            "probe16_failures": probe16["wrcProbeLimitFailures"], "probe1_failures": probe1["wrcProbeLimitFailures"],
            "probe16_steps": probe16["wrcProbeSteps"], "probe1_steps": probe1["wrcProbeSteps"],
        }
        assert scene["modes"]["lod1"]["settings"]["wrcTableSize"] == scene["modes"]["probe1"]["settings"]["wrcTableSize"]
        if not probe16["wrcFallbackRays"] < probe1["wrcFallbackRays"]:
            failures.append({"scene": name, "check": "bounded_probing_did_not_reduce_fallback", "comparison": comparison})
        summary.append(f"Probe limit 16 vs 1 fallback rays: {probe16['wrcFallbackRays']:.1f} vs {probe1['wrcFallbackRays']:.1f}")

        camera_base = read(name + "-camera-base")
        entry["camera_return_quality"] = {
            "first": metrics(read(name + "-camera-returned-first"), camera_base),
            "settled": metrics(read(name + "-camera-returned-settled"), camera_base),
            "note": "Reported only: live probe updates and sample sequences advance during camera movement.",
        }
        camera = scene["lifecycle"]["camera_lod"]
        entry["camera_lod_transition"] = {key: {field: camera[key][field] for field in
            ("updatedFrames", "wrcInvalidations", "wrcMaxLod", "wrcLodRays", "wrcTemporalReusedEntries")}
            for key in ("before", "moved_first", "moved_settled", "returned_first", "returned_settled")}

        frozen = read(name + "-frozen")
        entry["frozen_indirect_max_abs_error"] = max(
            close_arrays(read(name + "-frozen-later"), frozen, name + " frozen", absolute=1e-6, relative=0),
            close_arrays(read(name + "-resize-restored"), frozen, name + " resize restored", absolute=1e-6, relative=0),
        )
        dynamic = {tag: mean(read(name + "-" + tag)) for tag in ("light-base", "dim-settled", "light-restored")}
        assert dynamic["light-base"] > 1e-6, (name, "Missing indirect", dynamic)
        assert dynamic["dim-settled"] < dynamic["light-base"] * 0.8, (name, "Dimming failed", dynamic)
        assert dynamic["light-restored"] > dynamic["dim-settled"] * 1.25, (name, "Restoring light failed", dynamic)
        entry["dynamic_indirect_means"] = dynamic

    report["quality_failures"] = quality_failures
    report["validation_failures"] = failures
    report["passed"] = not failures and not quality_failures
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary.append(f"\nFinite HDR captures: {report['finite_hdr_captures']}; "
                   f"strict/state failures: {len(failures)}; quality failures: {len(quality_failures)}")
    summary.append("Detailed results: " + str(out / "results.json"))
    (out / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))
    assert report["passed"], ("WRC validation failed; inspect results, do not relax thresholds silently", failures, quality_failures)


if __name__ == "__main__":
    main()
