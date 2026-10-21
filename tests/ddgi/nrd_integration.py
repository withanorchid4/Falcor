"""Headless RTXDI + NRD + DDGI checks against raw lighting from the same frame."""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["NRD_DDGI_VALIDATION_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
os.environ["FALCOR_START_RENDERER"] = "DDGI"
os.environ["PROBE_GI_MODE"] = "manual"
os.environ["PROBE_GI_CACHE"] = str(OUT / "isolated-static-probe.shprobe")
CHANNELS = ("DDGI.color", "DDGI.indirect", "DirectModulate.output",
            "DirectLighting.color", "DirectLighting.emission")
records = {"backend": "d3d12", "scenes": {}, "captures": {}, "checks": []}


def frames(count):
    for _ in range(count):
        renderFrame()


def capture(tag, check="composite", dimensions=(320, 240)):
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = tag
    m.frameCapture.captureAllOutputs = False
    m.frameCapture.capture()
    records["captures"][tag] = {
        "channels": list(CHANNELS), "check": check, "dimensions": list(dimensions),
    }


def probe_stats(p):
    result = dict(p.stats)
    assert result["finite"], result
    assert result["usingRTXDI"], result
    for key, value in result.items():
        if key.startswith("rejected"):
            assert value == 0, (key, value)
    return result


def xyz(value):
    return (value.x, value.y, value.z)


def measure(name):
    # No captures or probe-stat readbacks inside the GPU timing interval.
    m.profiler.enabled = True
    frames(8)
    m.profiler.start_capture()
    started = time.perf_counter()
    frames(64)
    elapsed = time.perf_counter() - started
    timing = m.profiler.end_capture()
    m.profiler.enabled = False
    timing_name = name + "-timing.json"
    (OUT / timing_name).write_text(json.dumps(timing, indent=2), encoding="utf-8")
    return {"timed_frames": 64, "timed_wall_seconds": elapsed, "profiler": timing_name}


try:
    graphs = runpy.run_path(str(ROOT / "scripts/GIPreview.py"), init_globals={"m": m})["graphs"]
    assert set(graphs) == {"PathTracer", "PathTracerNRD", "TraditionalProbeGI", "RTXGIDDGI"}
    graph = graphs["RTXGIDDGI"]
    # GIPreview already registered Display.dst as Mogwai's selected output.
    # Keep it marked while adding the linear HDR diagnostic outputs.
    for channel in CHANNELS:
        graph.markOutput(channel)
    m.setActiveGraph(graph)
    p = graph.getPass("DDGI")
    denoiser = graph.getPass("DirectDenoiser")
    for name, scene_path in (
        ("cornell", "media/test_scenes/cornell_box.pyscene"),
        ("room", "media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene"),
    ):
        p.set_properties({"useRTXDI": True, "enableGI": True, "indirectOnly": False,
                          "showProbes": False, "updateEnabled": True})
        denoiser.set_properties({"enabled": True})
        resets = {"before_scene": int(denoiser.resetHistoryCount)}
        m.loadScene(str(ROOT / scene_path))
        m.clock.pause()
        m.scene.camera.animated = False
        frames(1)
        assert p.updatedFrames == 1, (name, p.updatedFrames)
        resets["scene_first"] = int(denoiser.resetHistoryCount)
        assert resets["scene_first"] > resets["before_scene"], (name, "Scene did not reset NRD", resets)
        capture(name + "-scene-first")
        frames(127)
        scene_record = records["scenes"][name] = {"settled": probe_stats(p), "nrd_reset_counts": resets}
        assert scene_record["settled"]["irradianceMax"] > 0
        p.set_properties({"updateEnabled": False})
        count = p.updatedFrames
        frames(1)
        capture(name + "-frozen")

        # Disabling NRD must bypass its history, while the modulation pass
        # reconstructs the original RTXDI radiance to half-float precision.
        denoiser.set_properties({"enabled": False})
        frames(1)
        capture(name + "-nrd-disabled-first", "bypass")
        frames(7)
        capture(name + "-nrd-disabled-settled", "bypass")
        resets["before_enable"] = int(denoiser.resetHistoryCount)
        denoiser.set_properties({"enabled": True})
        frames(1)
        resets["enable_first"] = int(denoiser.resetHistoryCount)
        assert resets["enable_first"] > resets["before_enable"], (name, "Enable did not reset NRD", resets)
        capture(name + "-nrd-enabled-first")
        frames(63)
        capture(name + "-nrd-enabled-settled")
        assert p.updatedFrames == count

        # Exercise the public history reset without reconstructing the graph.
        resets["before_explicit"] = int(denoiser.resetHistoryCount)
        denoiser.set_properties({"resetHistory": True})
        frames(1)
        resets["explicit_first"] = int(denoiser.resetHistoryCount)
        assert resets["explicit_first"] > resets["before_explicit"], (name, "Explicit reset did not run", resets)
        capture(name + "-nrd-reset-first")
        frames(63)
        capture(name + "-nrd-reset-settled")
        p.set_properties({"indirectOnly": True})
        frames(1)
        capture(name + "-indirect-only", "indirect")
        p.set_properties({"indirectOnly": False, "enableGI": False})
        frames(1)
        capture(name + "-direct-only", "direct")
        p.set_properties({"enableGI": True})
        frames(1)

        scene_record["timing"] = measure(name)
        # Both channels come from the identical RTXDI sample stream. NRD does
        # not alter the input samples, and there is no final accumulation pass.
        for index in range(32):
            frames(1)
            capture(name + f"-noise-{index:02d}")
        assert p.updatedFrames == count

        scene = m.scene
        position, target = xyz(scene.camera.position), xyz(scene.camera.target)
        for other in ("PathTracer", "PathTracerNRD", "TraditionalProbeGI"):
            m.setActiveGraph(graphs[other])
            frames(4)
            assert p.updatedFrames == count
            assert m.scene == scene and xyz(scene.camera.position) == position
            m.setActiveGraph(graph)
            frames(1)
            capture(name + "-switch-" + other)
        frames(32)
        capture(name + "-switch-settled")

        camera = m.scene.camera
        resets["before_camera"] = int(denoiser.resetHistoryCount)
        camera.position = float3(position[0] + 0.01, position[1], position[2])
        camera.target = float3(target[0] + 0.01, target[1], target[2])
        frames(1)
        resets["camera_first"] = int(denoiser.resetHistoryCount)
        assert resets["camera_first"] == resets["before_camera"], (name, "Ordinary camera motion reset NRD", resets)
        capture(name + "-camera-first")
        frames(31)
        capture(name + "-camera-settled")
        camera.position, camera.target = float3(*position), float3(*target)
        frames(1)
        capture(name + "-camera-return-first")
        frames(63)
        capture(name + "-camera-return-settled")
        resets["camera_return"] = int(denoiser.resetHistoryCount)
        assert resets["camera_return"] == resets["before_camera"], (name, "Camera move/return reset NRD", resets)
        assert p.updatedFrames == count

        resets["before_dim"] = int(denoiser.resetHistoryCount)
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
        resets["dim_first"] = int(denoiser.resetHistoryCount)
        assert resets["dim_first"] > resets["before_dim"], (name, "Light dim did not reset NRD", resets)
        capture(name + "-dim-first")
        frames(95)
        capture(name + "-dim-settled")
        resets["before_light_restore"] = int(denoiser.resetHistoryCount)
        restore()
        frames(96)
        resets["light_restore"] = int(denoiser.resetHistoryCount)
        assert resets["light_restore"] > resets["before_light_restore"], (name, "Light restore did not reset NRD", resets)
        capture(name + "-light-restored")
        assert p.updatedFrames == count

        resets["before_resize"] = int(denoiser.resetHistoryCount)
        resizeFrameBuffer(401, 301)
        frames(1)
        resets["resize_first"] = int(denoiser.resetHistoryCount)
        assert resets["resize_first"] > resets["before_resize"], (name, "Resize did not reset NRD", resets)
        capture(name + "-resize-first", dimensions=(401, 301))
        frames(31)
        capture(name + "-resize-settled", dimensions=(401, 301))
        resets["before_resize_restore"] = int(denoiser.resetHistoryCount)
        resizeFrameBuffer(320, 240)
        frames(32)
        resets["resize_restore"] = int(denoiser.resetHistoryCount)
        assert resets["resize_restore"] > resets["before_resize_restore"], (name, "Resize restore did not reset NRD", resets)
        capture(name + "-resize-restored")
        p.set_properties({"updateEnabled": True})
        frames(2)
        assert p.updatedFrames == count + 2
        scene_record["final"] = probe_stats(p)
        (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    records["checks"] = [
        "Cornell and Room first frame and settled output", "same-frame filtered direct plus indirect composition",
        "NRD disabled reconstructs raw direct light", "NRD enable and explicit history reset",
        "NRD scene/enable/light/resize reset counters and preserved history during camera motion",
        "frozen probe field survives NRD switches", "indirectOnly and enableGI",
        "32 paired raw/filtered frames per scene", "four-graph shared-scene switching",
        "camera move and return", "surface lighting follows emissive/environment intensity changes",
        "odd resolution resize and restore", "probe resume",
    ]
    records["note"] = (
        "Raw and filtered signals are paired in the same frame. Temporal variance measures flicker, "
        "not unbiased error, ghosting, or spatial detail preservation. Timings describe the full "
        "RTXDI/NRD/DDGI graph with frozen probes and no capture readbacks in the timing interval."
    )
    (OUT / "integration.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("RTXDI + NRD + DDGI integration captures: " + str(OUT))
except Exception:
    (OUT / "partial.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    exit(1)
exit()
