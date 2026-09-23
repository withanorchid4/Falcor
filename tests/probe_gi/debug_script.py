"""Headless Vulkan integration coverage of the GUI's probe debug controller."""
from falcor import *
from pathlib import Path
import json
import math
import traceback

output = Path("F:/build/probe-debug-validation")
output.mkdir(parents=True, exist_ok=True)
for filename in ("failure.txt", "integration.json", "results.json"):
    (output / filename).unlink(missing_ok=True)
cache = output / "debug-validation.shprobe"
checks = []


def frames(n=1):
    for _ in range(n):
        renderFrame()


def capture(tag):
    m.frameCapture.outputDir = str(output)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()


def xyz(v):
    return list(v) if isinstance(v, (list, tuple)) else [v.x, v.y, v.z]


def inspect(uv):
    p.pickSurface(float2(*uv))
    frames()
    info = p.debugInfo
    if info["valid"]:
        weights = [info[f"weight{i}"] for i in range(8)]
        assert min(weights) >= 0 and abs(sum(weights) - 1) < 2e-6, weights
        ids = [info[f"probe{i}"] for i in range(8)]
        assert len(set(ids)) == 8 and all(0 <= i < 384 for i in ids), ids
        for key in ("position", "samplePosition", "normal", "irradiance"):
            assert all(math.isfinite(v) for v in xyz(info[key]))
    return info


try:
    g = RenderGraph("ProbeDebugValidation")
    g.addPass(createPass("VBufferRT", {"samplePattern": "Center"}), "Visibility")
    g.addPass(createPass("TraditionalProbeGI", {
        "mode": "manual", "samplesPerProbe": 128, "samplesPerFrame": 32,
        "cacheFile": str(cache), "sceneRevision": "debug-validation",
    }), "Probes")
    g.addPass(createPass("ToneMapper", {"autoExposure": False}), "Display")
    g.addEdge("Visibility.vbuffer", "Probes.vbuffer")
    g.addEdge("Visibility.viewW", "Probes.viewW")
    g.addEdge("Probes.color", "Display.src")
    for channel in ("Display.dst", "Probes.color", "Probes.probeLighting"):
        g.markOutput(channel)
    m.addGraph(g)
    m.loadScene("F:/media/test_scenes/cornell_box.pyscene")
    m.clock.pause()
    p = g.getPass("Probes")
    frames(3)
    assert not p.ready and not p.debugInfo["enabled"]
    p.configureDebug({"enabled": True, "showIds": True, "xray": True})
    frames()
    capture("unbaked")
    assert inspect((0.5, 0.5))["valid"]
    checks.append("unbaked overlay and normalized-coordinate surface picking")

    p.configureBake({"gridMin": float3(0), "gridMax": float3(0)})
    p.configureDebug({"view": 4})
    frames(2)
    assert not p.ready and not p.debugInfo["valid"]
    capture("invalid-bounds")
    p.configureBake({"autoBounds": True})
    p.configureDebug({"view": 0})
    frames(2)
    checks.append("invalid grid safely suspends debug; restoring bounds resumes without rebaking")

    p.configureDebug({"enabled": False})
    p.bake()
    frames(5)
    assert p.ready
    baked_cache = cache.read_bytes()
    capture("baseline")
    p.configureDebug({"enabled": True, "xray": True, "showIds": True})
    info = inspect((0.5, 0.5))
    assert info["valid"]
    capture("links-xray")
    saved_anchor = xyz(info["position"])
    old_position = float3(*xyz(m.scene.camera.position))
    m.scene.camera.position = float3(old_position.x + 0.05, old_position.y, old_position.z)
    frames()
    assert xyz(p.debugInfo["position"]) == saved_anchor
    capture("anchor-moved")
    m.scene.camera.position = old_position
    frames()
    checks.append("weights sum to one, eight valid IDs, finite records, world anchor persists on camera move")

    p.configureDebug({"xray": False})
    frames()
    capture("depth-tested")
    p.configureDebug({"xray": True, "onlyContributors": True})
    frames()
    capture("selected-cell")
    p.configureDebug({"onlyContributors": False, "xray": False})
    p.configureDebug({"normalBias": 0.1})
    frames()
    assert xyz(p.debugInfo["position"]) == saved_anchor
    assert xyz(p.debugInfo["samplePosition"]) != xyz(info["samplePosition"])
    p.configureDebug({"normalBias": 0.05})
    frames()
    checks.append("normal bias refreshes inspection without moving anchor or rebaking")

    # Scan surfaces including the boxes, to exercise both visible and blocked links.
    visible = blocked = 0
    captured_blocked = False
    for y in (0.25, 0.45, 0.65, 0.8):
        for x in (0.25, 0.45, 0.65, 0.8):
            info = inspect((x, y))
            if info["valid"]:
                if not captured_blocked and any(info[f"weight{i}"] > 1e-6 and not info[f"visible{i}"] for i in range(8)):
                    p.configureDebug({"xray": True, "onlyContributors": True})
                    frames()
                    capture("blocked-links")
                    p.configureDebug({"xray": False, "onlyContributors": False})
                    captured_blocked = True
                for i in range(8):
                    if info[f"weight{i}"] > 1e-6:
                        if info[f"visible{i}"]: visible += 1
                        else: blocked += 1
    assert visible > 0 and blocked > 0, (visible, blocked)
    checks.append(f"shadow-ray diagnostics: {visible} visible / {blocked} blocked contributing links")

    for view, tag in ((1, "irradiance"), (2, "albedo"), (3, "normals"), (4, "cells"), (5, "clamp")):
        p.configureDebug({"view": view, "showProbes": False, "showBounds": False, "showLinks": False, "preview": False})
        frames()
        capture(tag)
    p.configureDebug({"view": 0, "preview": True, "radiance": True, "negative": True})
    frames()
    capture("radiance-negative")
    # No overlays, debug view Normal must leave the color output bitwise unchanged.
    p.configureDebug({"view": 0, "preview": False})
    frames()
    capture("debug-no-overlay")
    p.configureDebug({"enabled": False})
    frames()
    capture("restored")
    assert p.ready and p.completedSamples == 128 and cache.read_bytes() == baked_cache
    checks.append("all surface views and SH preview; debug never alters ready state or cache bytes")

    # Aim away from the Cornell box, then pick the background to clear the anchor.
    original_target = float3(*xyz(m.scene.camera.target))
    pos = m.scene.camera.position
    m.scene.camera.target = float3(pos.x, pos.y, pos.z + 10)
    frames()
    assert not inspect((0.5, 0.5))["valid"]
    m.scene.camera.target = original_target
    frames()
    assert inspect((0.5, 0.5))["valid"]
    m.loadScene("F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene")
    frames(2)
    assert not p.debugInfo["valid"] and not p.ready
    capture("room-reset")
    checks.append("background click and scene switch clear old selection")
    (output / "integration.json").write_text(json.dumps({"passed": checks}, indent=2), encoding="utf-8")
    (output / "failure.txt").unlink(missing_ok=True)
except Exception:
    (output / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise
exit()
