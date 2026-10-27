"""Compare original DDGI with the optional world radiance cache on the GPU.

Run with run_wrc_validation.py. Each quality mode gets a new graph and scene,
so the probe ray rotation and direct-light sample sequences start identically.
"""
from falcor import *
from pathlib import Path
import json
import math
import os
import runpy
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["WRC_DDGI_VALIDATION_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
CHANNELS = ("DDGI.color", "DDGI.indirect", "DirectModulate.output")
DEFAULTS = {"useWRC": False, "wrcCellScale": 0.1, "wrcTableSize": 65536,
            "wrcMaxAge": 0, "wrcShadeSamples": 1, "wrcBypassSharing": False,
            "wrcLodDistance": 8.0, "wrcMaxLod": 16, "wrcProbeLimit": 16,
            "updateEnabled": True, "enableGI": True, "indirectOnly": False,
            "showProbes": False, "useRTXDI": True}
records = {"backend": "d3d12", "wrc_design": "distance-lod-bounded-probing-material-dispatch",
           "scenes": {}, "captures": {}, "checks": []}

# Load the factory once. Re-running the module for every mode creates cycles
# between its function globals and the eagerly constructed RTXGIDDGI graph,
# keeping old graphs (and their native GPU/compiler resources) alive until GC.
graph_factory = runpy.run_path(str(ROOT / "scripts/RTXGIDDGI.py"))["render_graph_RTXGIDDGI"]
graph_factory.__globals__.pop("RTXGIDDGI", None)


def frames(count):
    for _ in range(count):
        renderFrame()


def capture(tag, dimensions=(320, 240)):
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = tag
    m.frameCapture.captureAllOutputs = False
    m.frameCapture.capture()
    records["captures"][tag] = {"channels": list(CHANNELS), "dimensions": list(dimensions)}


def stats(p):
    s = dict(p.stats)
    assert s["finite"], s
    assert s["usingRTXDI"], s
    for key, value in s.items():
        if key.startswith("rejected"):
            assert value == 0, (key, value)
    assert s["wrcNonFiniteResults"] == 0, s
    if s["wrcEnabled"] and s["updatedFrames"]:
        valid, served, fallback = (s[k] for k in ("wrcValidRays", "wrcServedRays", "wrcFallbackRays"))
        occupied, shaded, reused = (s[k] for k in ("wrcOccupiedEntries", "wrcShadedEntries", "wrcTemporalReusedEntries"))
        assert served + fallback == valid, ("Ray accounting", s)
        assert shaded + reused == occupied, ("Entry accounting", s)
        assert served >= occupied and occupied <= valid, ("Owner accounting", s)
        active, scheduled, groups = (s[k] for k in ("wrcActiveEntries", "wrcScheduledThreads", "wrcShaderGroups"))
        assert active == occupied, ("Active list accounting", s)
        if occupied:
            assert 0 < groups <= occupied, ("Nonempty material groups", s)
            assert occupied <= scheduled < occupied + 64 * groups, ("Indirect dispatch padding", s)
            assert scheduled % 64 == 0, ("Indirect dispatch alignment", s)
        else:
            assert scheduled == groups == 0, ("Empty dispatch", s)
        assert s["wrcProbeLimitFailures"] <= fallback, ("Probe limit fallback", s)
        assert s["wrcProbeSteps"] <= valid * p.properties["wrcProbeLimit"], ("Unbounded hash probing", s)
        assert s["wrcLodRays"] <= valid, ("LOD ray accounting", s)
        assert s["wrcCrossPrimitiveServedRays"] <= served, ("Cross-primitive ray accounting", s)
        if valid:
            assert s["wrcMaxLod"] in (1, 2, 4, 8, 16, 32, 64), ("Non-power-of-two LOD", s)
            assert s["wrcMaxLod"] <= p.properties["wrcMaxLod"], ("LOD exceeds configured limit", s)
    return s


def new_mode(scene_path, properties):
    graph = graph_factory()
    for channel in CHANNELS:
        graph.markOutput(channel)
    p = graph.getPass("DDGI")
    settings = dict(DEFAULTS)
    settings.update(properties)
    p.set_properties(settings)
    # addGraph replaces the old graph of this name. Never recycle the old pass:
    # reset() alone does not reset its gFrameCount random seed.
    m.addGraph(graph)
    m.setActiveGraph(graph)
    m.loadScene(str(ROOT / scene_path))
    m.clock.pause()
    m.scene.camera.animated = False
    return graph, p, settings


def measure(tag):
    # Probe updates remain enabled: measure the whole update, not a frozen field.
    m.profiler.enabled = True
    frames(8)
    m.profiler.start_capture()
    started = time.perf_counter()
    frames(64)
    elapsed = time.perf_counter() - started
    timing = m.profiler.end_capture()
    m.profiler.enabled = False
    filename = tag + "-timing.json"
    (OUT / filename).write_text(json.dumps(timing, indent=2), encoding="utf-8")
    return {"profiler": filename, "timed_frames": 64, "timed_wall_seconds": elapsed}


def check_bias_invalidation(p):
    """Bias changes discard cached shading without resetting the DDGI field."""
    result = {}
    assert p.properties["useWRC"] and p.properties["wrcMaxAge"] > 0, dict(p.properties)
    for key in ("normalBias", "viewBias"):
        original = float(p.properties[key])
        changed = original + 0.05 if original <= 0.9 else original - 0.05
        before = stats(p)
        for _ in range(8):
            if before["wrcTemporalReusedEntries"] > 0:
                break
            frames(1)
            after = stats(p)
            assert after["updatedFrames"] == before["updatedFrames"] + 1, (key, before, after)
            before = after
        assert before["wrcTemporalReusedEntries"] > 0, (key, "No reuse before bias change", before)
        entry = result[key] = {"original": original, "changed": changed, "before": before}
        try:
            p.set_properties({key: changed})
            frames(1)
            after = entry["changed_first"] = stats(p)
            assert after["wrcInvalidations"] > before["wrcInvalidations"], (key, entry)
            assert after["updatedFrames"] == before["updatedFrames"] + 1, (key, entry)
            assert after["wrcTemporalReusedEntries"] == 0, (key, entry)
        finally:
            p.set_properties({key: original})
        frames(1)
        restored = entry["restored_first"] = stats(p)
        assert restored["wrcInvalidations"] > after["wrcInvalidations"], (key, entry)
        assert restored["updatedFrames"] == after["updatedFrames"] + 1, (key, entry)
        assert restored["wrcTemporalReusedEntries"] == 0, (key, entry)
        assert float(p.properties[key]) == original, (key, dict(p.properties))
    return result


def check_camera_lod(name, p):
    """Exercise changing LOD keys while retaining valid temporal cache entries."""
    camera = m.scene.camera
    # Camera getters return const float3& with reference_internal bindings.
    # Copy the components so setting camera.position cannot mutate our snapshot.
    position = float3(camera.position.x, camera.position.y, camera.position.z)
    target = float3(camera.target.x, camera.target.y, camera.target.z)
    before = stats(p)
    offset = position - target
    view_distance = math.sqrt(offset.x * offset.x + offset.y * offset.y + offset.z * offset.z)
    assert view_distance > 1e-8, (name, "Camera has no view direction")
    direction = offset / view_distance
    move_distance = 8.0 * before["wrcLodDistance"]
    far_position = position + direction * move_distance
    result = {"before": before, "position": [position.x, position.y, position.z],
              "target": [target.x, target.y, target.z], "camera_poses": {},
              "camera_move": {"kind": "move8xLODdistance", "world_distance": move_distance,
                              "lod_distance": before["wrcLodDistance"],
                              "direction": [direction.x, direction.y, direction.z],
                              "far_position": [far_position.x, far_position.y, far_position.z]}}

    def record_pose(label, expected_position):
        actual = {"position": [camera.position.x, camera.position.y, camera.position.z],
                  "target": [camera.target.x, camera.target.y, camera.target.z]}
        result["camera_poses"][label] = actual
        expected = [expected_position.x, expected_position.y, expected_position.z]
        assert actual["position"] == expected, (name, label, "Camera position mismatch", expected, actual)
        assert actual["target"] == result["target"], (name, label, "Camera target mismatch", result["target"], actual)

    record_pose("before", position)
    capture(name + "-camera-base")

    def checkpoint(label, count, expected_position):
        previous = stats(p)
        frames(count)
        record_pose(label, expected_position)
        current = result[label] = stats(p)
        assert current["updatedFrames"] == previous["updatedFrames"] + count, (name, label, result)
        assert current["wrcInvalidations"] == before["wrcInvalidations"], (name, "Camera invalidated WRC", result)
        capture(name + "-camera-" + label.replace("_", "-"))
        return current

    try:
        # Move by a world-space LOD distance; target may be only centimeters away.
        # Keep the original target and look direction while crossing LOD boundaries.
        camera.position = far_position
        record_pose("moved_set", far_position)
        assert result["camera_poses"]["moved_set"]["position"] != result["position"], (name, "Camera did not move", result)
        moved = checkpoint("moved_first", 1, far_position)
        checkpoint("moved_settled", 7, far_position)
        assert moved["wrcMaxLod"] > before["wrcMaxLod"], (name, "Camera did not exercise a coarser LOD", result)
    finally:
        camera.position = position
        camera.target = target
        record_pose("returned_set", position)
    returned = checkpoint("returned_first", 1, position)
    assert returned["wrcMaxLod"] < moved["wrcMaxLod"], (name, "Camera did not return to finer LOD", result)
    checkpoint("returned_settled", 63, position)
    return result


try:
    selected_scene = os.environ.get("WRC_DDGI_VALIDATION_SCENE", "")
    selected_mode = os.environ.get("WRC_DDGI_VALIDATION_MODE", "")
    assert selected_scene in ("", "cornell", "room"), ("Unknown validation scene", selected_scene)
    assert not selected_mode or selected_scene, "Mode isolation requires a scene"
    records["selected_mode"] = selected_mode or None
    records["selected_scenes"] = [selected_scene] if selected_scene else ["cornell", "room"]
    for name, scene_path in (
        ("cornell", "media/test_scenes/cornell_box.pyscene"),
        ("room", "media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene"),
    ):
        if selected_scene and name != selected_scene:
            continue
        scene_record = records["scenes"][name] = {"modes": {}}
        modes = [
            ("baseline", {}),
            ("bypass", {"useWRC": True, "wrcBypassSharing": True}),
            ("wrc", {"useWRC": True}),
            ("lod1", {"useWRC": True, "wrcMaxLod": 1}),
            ("probe1", {"useWRC": True, "wrcMaxLod": 1, "wrcProbeLimit": 1}),
            ("collision", {"useWRC": True, "wrcTableSize": 64}),
            ("lodCoarse", {"useWRC": True, "wrcLodDistance": 2.0}),
            ("temporal", {"useWRC": True, "wrcMaxAge": 2}),
        ]
        assert not selected_mode or selected_mode in dict(modes), ("Unknown validation mode", selected_mode)
        for mode, properties in modes:
            if selected_mode and mode != selected_mode:
                continue
            graph, p, settings = new_mode(scene_path, properties)
            tag = name + "-" + mode
            frames(1)
            assert p.updatedFrames == 1, (tag, p.updatedFrames)
            capture(tag + "-first")
            first = stats(p)
            frames(127)
            steady = []
            for index in range(4):
                if index:
                    frames(1)
                capture(tag + f"-steady-{index}")
                steady.append(stats(p))
            assert p.updatedFrames == 131, (tag, p.updatedFrames)
            assert steady[-1]["irradianceMax"] > 0, (tag, steady[-1])
            if mode == "bypass":
                assert steady[-1]["wrcFallbackRays"] == steady[-1]["wrcValidRays"] > 0, steady[-1]
                assert steady[-1]["wrcOccupiedEntries"] == 0, steady[-1]
            elif mode != "baseline":
                assert steady[-1]["wrcValidRays"] > 0 and steady[-1]["wrcOccupiedEntries"] > 0, steady[-1]
            if mode == "collision":
                assert steady[-1]["wrcFallbackRays"] > 0, (tag, "No collision fallback exercised")
                assert steady[-1]["wrcProbeLimitFailures"] > 0, (tag, "No bounded probing failure exercised")
            if mode == "wrc":
                assert steady[-1]["wrcMaxLod"] > 1 and steady[-1]["wrcLodRays"] > 0, (tag, "No distance LOD exercised")
            if mode in ("lod1", "probe1"):
                assert all(s["wrcMaxLod"] == 1 and s["wrcLodRays"] == 0 for s in steady), (tag, "Fixed LOD failed", steady)
            if mode == "temporal":
                assert any(s["wrcTemporalReusedEntries"] > 0 for s in steady), (tag, "No temporal reuse", steady)
            scene_record["modes"][mode] = {
                "settings": settings, "first": first, "steady": steady, "timing": measure(tag),
            }
            (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

        # Lifecycle checks belong to the temporal worker in isolated runs.
        if selected_mode and selected_mode != "temporal":
            continue
        # Continue the temporal mode to exercise real cache invalidation.
        lifecycle = scene_record["lifecycle"] = {}
        lifecycle["bias_invalidation"] = check_bias_invalidation(p)
        capture(name + "-light-base")
        lifecycle["before_dim"] = stats(p)
        if name == "cornell":
            light = m.scene.getMaterial("Light")
            original = light.emissiveFactor
            light.emissiveFactor = original * 0.25
            restore = lambda: setattr(light, "emissiveFactor", original)
        else:
            original = m.scene.envMap.intensity
            m.scene.envMap.intensity = original * 0.25
            restore = lambda: setattr(m.scene.envMap, "intensity", original)
        frames(1)
        lifecycle["dim_first"] = stats(p)
        assert lifecycle["dim_first"]["wrcInvalidations"] > lifecycle["before_dim"]["wrcInvalidations"], lifecycle
        assert lifecycle["dim_first"]["wrcTemporalReusedEntries"] == 0, lifecycle["dim_first"]
        capture(name + "-dim-first")
        frames(95)
        capture(name + "-dim-settled")
        lifecycle["before_restore"] = stats(p)
        restore()
        frames(1)
        lifecycle["restore_first"] = stats(p)
        assert lifecycle["restore_first"]["wrcInvalidations"] > lifecycle["before_restore"]["wrcInvalidations"], lifecycle
        assert lifecycle["restore_first"]["wrcTemporalReusedEntries"] == 0, lifecycle["restore_first"]
        frames(95)
        capture(name + "-light-restored")
        lifecycle["camera_lod"] = check_camera_lod(name, p)

        # Runtime A/B toggles clear both estimators' probe history.
        p.set_properties({"useWRC": False})
        frames(1)
        lifecycle["toggle_off"] = stats(p)
        assert p.updatedFrames == 1 and not lifecycle["toggle_off"]["wrcEnabled"], lifecycle["toggle_off"]
        capture(name + "-toggle-off-first")
        frames(63)
        p.set_properties({"useWRC": True, "wrcMaxAge": 0})
        frames(1)
        lifecycle["toggle_on"] = stats(p)
        assert p.updatedFrames == 1 and lifecycle["toggle_on"]["wrcEnabled"], lifecycle["toggle_on"]
        capture(name + "-toggle-on-first")
        frames(127)
        capture(name + "-toggle-on-settled")

        p.set_properties({"updateEnabled": False})
        count = p.updatedFrames
        frames(1)
        capture(name + "-frozen")
        lifecycle["frozen"] = stats(p)
        frames(8)
        capture(name + "-frozen-later")
        assert p.updatedFrames == count, (name, "Frozen probe update advanced")
        resizeFrameBuffer(401, 301)
        frames(1)
        capture(name + "-resize-first", dimensions=(401, 301))
        assert p.updatedFrames == count, (name, "Resize updated frozen probes")
        resizeFrameBuffer(320, 240)
        frames(1)
        capture(name + "-resize-restored")
        p.set_properties({"updateEnabled": True})
        frames(2)
        assert p.updatedFrames == count + 2, (name, "Probe resume failed")
        lifecycle["final"] = stats(p)
        (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    records["checks"] = [
        "requested scenes with fresh graph and sample seeds per mode",
        "baseline versus unshared split-path first frame and settled equality",
        "same-frame direct plus indirect composition and finite HDR",
        "distance LOD, fixed LOD, and earlier LOD transition: indirect mean and relative RMSE",
        "bounded hash probing versus a single slot, overflow fallback, and complete ray accounting",
        "material active lists and rounded 64-thread GPU indirect dispatch accounting",
        "cross-primitive sharing is reported without assuming matching scene materials",
        "bounded temporal cache reuse and light/material/environment invalidation",
        "normal/view bias changes and restoration invalidate WRC without resetting probe history",
        "camera moves and returns across distance LODs without resetting probes or invalidating WRC",
        "runtime WRC toggle resets history and restores original path",
        "frozen probes, odd resize, and resume",
        "64-frame GPU timing with live probe updates and no capture readbacks",
    ]
    records["note"] = (
        "Each quality mode reconstructs the graph and scene, then captures probe updates 128 through 131. "
        "Reference is the original DDGI estimator with identical initial random sequences, not path-traced ground truth. "
        "Spatial sharing changes sample correlation and may change bias; shading-count savings are not GPU speedup."
    )
    if selected_mode:
        # A worker is not a complete quality comparison. The parent combines all
        # eight modes and runs the unchanged image checker before reporting PASS.
        records["checks"] = ["mode captures and ray accounting"]
        if selected_mode == "temporal":
            records["checks"].append("temporal reuse and all lifecycle assertions")
    completion_file = "mode-complete.json" if selected_mode else "integration.json"
    (OUT / completion_file).write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("WRC + DDGI captures: " + str(OUT))
except Exception:
    (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
