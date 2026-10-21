"""Headless RTXDI camera lighting + DDGI composition and state validation.

Run using run_rtxdi_validation.py. Probe updates are frozen during direct-light
comparisons, so the two samplers see the same indirect illumination.
"""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["RTXDI_DDGI_VALIDATION_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
CHANNELS = ("DDGI.color", "DDGI.indirect", "DirectLighting.color", "DirectLighting.emission")
records = {"backend": "d3d12", "scenes": {}, "captures": {}, "checks": []}


def frames(count):
    for _ in range(count):
        renderFrame()


def capture(tag, check="composite", channels=CHANNELS, dimensions=(320, 240)):
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = tag
    m.frameCapture.captureAllOutputs = False
    m.frameCapture.capture()
    records["captures"][tag] = {
        "channels": list(channels), "check": check, "dimensions": list(dimensions),
    }


def probe_stats(p):
    result = dict(p.stats)
    assert result["finite"], result
    for key, value in result.items():
        if key.startswith("rejected"):
            assert value == 0, (key, value)
    return result


def camera_tuple(value):
    return (value.x, value.y, value.z)


def measure_mode(p, name, mode):
    p.set_properties({"useRTXDI": mode == "rtxdi"})
    frames(32)
    assert bool(p.stats["usingRTXDI"]) == (mode == "rtxdi")
    # Time without image readbacks. Both modes still execute DirectLighting,
    # because its output remains connected to the graph; this is not a cost
    # measurement of the old graph without RTXDI.
    m.profiler.enabled = True
    frames(8)
    m.profiler.start_capture()
    started = time.perf_counter()
    frames(64)
    elapsed = time.perf_counter() - started
    timing = m.profiler.end_capture()
    m.profiler.enabled = False
    timing_name = name + "-" + mode + "-timing.json"
    (OUT / timing_name).write_text(json.dumps(timing, indent=2), encoding="utf-8")
    started = time.perf_counter()
    for index in range(32):
        frames(1)
        capture(name + "-noise-" + mode + f"-{index:02d}", "composite" if mode == "rtxdi" else "legacy")
    return {
        "sample_count": 32, "warmup_frames": 32, "timed_frames": 64,
        "timed_wall_seconds": elapsed,
        "capture_wall_seconds": time.perf_counter() - started,
        "profiler": timing_name,
    }


try:
    graph = runpy.run_path(str(ROOT / "scripts/RTXGIDDGI.py"))["RTXGIDDGI"]
    # Keep this suite a strict raw-RTXDI integration check after the production
    # graph starts feeding denoised lighting to DDGI. Unused NRD passes are
    # culled by the render graph when their outputs are not marked.
    graph.removeEdge("DirectModulate.output", "DDGI.directLighting")
    graph.addEdge("DirectLighting.color", "DDGI.directLighting")
    graph.unmarkOutput("Display.dst")
    for channel in CHANNELS:
        graph.markOutput(channel)
    m.addGraph(graph)
    m.setActiveGraph(graph)
    p = graph.getPass("DDGI")
    for name, scene_path in (
        ("cornell", "media/test_scenes/cornell_box.pyscene"),
        ("room", "media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene"),
    ):
        p.set_properties({"useRTXDI": True, "enableGI": True, "indirectOnly": False,
                          "showProbes": False, "updateEnabled": True})
        m.loadScene(str(ROOT / scene_path))
        m.clock.pause()
        m.scene.camera.animated = False
        frames(1)
        assert p.updatedFrames == 1, (name, p.updatedFrames)
        frames(127)
        scene_record = records["scenes"][name] = {"settled": probe_stats(p)}
        assert scene_record["settled"]["usingRTXDI"]
        assert scene_record["settled"]["irradianceMax"] > 0
        capture(name + "-baseline")

        p.set_properties({"updateEnabled": False})
        count = p.updatedFrames
        frames(1)
        capture(name + "-frozen")
        p.set_properties({"indirectOnly": True})
        frames(1)
        capture(name + "-indirect-only", "indirect")
        p.set_properties({"enableGI": False})
        frames(1)
        capture(name + "-all-off", "zero")
        p.set_properties({"indirectOnly": False})
        frames(1)
        capture(name + "-direct-only", "direct")
        p.set_properties({"enableGI": True, "useRTXDI": False})
        frames(1)
        assert not p.stats["usingRTXDI"]
        capture(name + "-legacy", "legacy")
        p.set_properties({"useRTXDI": True})
        frames(1)
        capture(name + "-restored")
        assert p.updatedFrames == count

        # A stationary, unchanged probe field separates direct-light variance
        # from DDGI convergence. Capture consecutive frames, with no Accumulate.
        scene_record["noise"] = {}
        for mode in ("legacy", "rtxdi"):
            scene_record["noise"][mode] = measure_mode(p, name, mode)
        assert p.updatedFrames == count

        # Actual temporal reprojection: move position and target together, then
        # move back. The first frame matters as much as the settled capture.
        camera = m.scene.camera
        position, target = camera_tuple(camera.position), camera_tuple(camera.target)
        camera.position = float3(position[0] + 0.01, position[1], position[2])
        camera.target = float3(target[0] + 0.01, target[1], target[2])
        frames(1)
        capture(name + "-camera-first")
        frames(31)
        capture(name + "-camera-settled")
        camera.position, camera.target = float3(*position), float3(*target)
        frames(1)
        capture(name + "-camera-return-first")
        frames(31)
        capture(name + "-camera-return-settled")
        assert p.updatedFrames == count

        # Direct-light response is isolated from probe history. The source is
        # changed, rather than scaling a final image output.
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
        capture(name + "-dim-first")
        frames(63)
        capture(name + "-dim-settled")
        restore()
        frames(64)
        capture(name + "-light-restored")
        assert p.updatedFrames == count

        # Odd dimensions exercise dispatch edges and reservoir reallocations.
        resizeFrameBuffer(401, 301)
        frames(1)
        capture(name + "-resize-first", dimensions=(401, 301))
        frames(15)
        capture(name + "-resize-settled", dimensions=(401, 301))
        resizeFrameBuffer(320, 240)
        frames(16)
        capture(name + "-resize-restored")
        p.set_properties({"updateEnabled": True})
        frames(2)
        assert p.updatedFrames == count + 2
        scene_record["final"] = probe_stats(p)
        (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    # The new input is optional. Legacy external scripts still work even with
    # useRTXDI defaulting to true when no directLighting edge is connected.
    fallback = RenderGraph("DDGIFallbackValidation")
    fallback.addPass(createPass("VBufferRT", {"samplePattern": "Center", "useAlphaTest": True}), "Visibility")
    fallback.addPass(createPass("RTXGIDDGI", {"useRTXDI": True}), "DDGI")
    fallback.addEdge("Visibility.vbuffer", "DDGI.vbuffer")
    fallback.addEdge("Visibility.viewW", "DDGI.viewW")
    for channel in CHANNELS[:2]:
        fallback.markOutput(channel)
    m.addGraph(fallback)
    m.setActiveGraph(fallback)
    frames(32)
    fallback_pass = fallback.getPass("DDGI")
    records["fallback"] = probe_stats(fallback_pass)
    assert not records["fallback"]["usingRTXDI"]
    capture("no-input-fallback", "legacy", channels=CHANNELS[:2])
    records["checks"] = [
        "Cornell and Room scene reload", "same-frame direct plus indirect composition",
        "indirectOnly and enableGI", "legacy switch preserves frozen indirect",
        "32 consecutive raw direct-light frames per sampler and scene",
        "camera move and return", "emissive/environment intensity changes",
        "surface direct response excludes visible emission and environment background",
        "odd resolution resize and restore", "probe resume", "optional-input fallback",
    ]
    records["timing_note"] = (
        "Both switches execute the connected DirectLighting pass. Timings describe this graph, "
        "not the old standalone sampler's cost. Consecutive-frame temporal variance is not an "
        "unbiased image error metric, and correlated reservoir reuse can lower it without eliminating bias."
    )
    (OUT / "integration.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("RTXDI + DDGI integration captures: " + str(OUT))
except Exception:
    (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
