"""Mogwai integration test of the same controller used by the bake UI.

Run headless with --deferred. Restores any pre-existing per-scene cache files.
"""
from falcor import *
from pathlib import Path
import json
import traceback

output = Path("F:/build/probe-interactive-validation")
output.mkdir(parents=True, exist_ok=True)
cache_root = Path("F:/build/probes").resolve()
backups = {}
checks = []


def frames(count=1):
    for _ in range(count):
        renderFrame()


def waiting(probes):
    assert not probes.ready and not probes.baking and probes.completedSamples == 0, probes.status


def protect_cache(probes):
    path = Path(probes.cacheFile).resolve()
    assert path.parent == cache_root and path.suffix == ".shprobe", path
    if path not in backups:
        backups[path] = path.read_bytes() if path.exists() else None
    return path


def finish(probes):
    for _ in range(80):
        if probes.ready:
            return
        renderFrame()
    raise AssertionError(probes.status)


def capture(tag):
    m.frameCapture.outputDir = str(output)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()


try:
    g = RenderGraph("InteractiveProbeValidation")
    g.addPass(createPass("VBufferRT", {"samplePattern": "Center"}), "Visibility")
    g.addPass(createPass("TraditionalProbeGI", {
        "mode": "manual", "gridCounts": uint3(3, 3, 3),
        "samplesPerProbe": 64, "samplesPerFrame": 4,
        "sceneRevision": "interactive-validation",
    }), "Probes")
    g.addPass(createPass("ToneMapper", {"autoExposure": False}), "Display")
    g.addEdge("Visibility.vbuffer", "Probes.vbuffer")
    g.addEdge("Visibility.viewW", "Probes.viewW")
    g.addEdge("Probes.color", "Display.src")
    g.markOutput("Display.dst")
    g.markOutput("Probes.color")
    g.markOutput("Probes.probeLighting")
    m.addGraph(g)
    m.loadScene("F:/media/test_scenes/cornell_box.pyscene")
    m.clock.pause()
    p = g.getPass("Probes")
    frames(3)
    waiting(p)
    cornell_cache = protect_cache(p)
    capture("waiting")
    checks.append("manual startup waits without baking")

    # Invalid bounds are safe while editing and reject a Bake request.
    p.configureBake({"gridMin": float3(1), "gridMax": float3(0)})
    p.bake()
    frames(2)
    waiting(p)
    assert "Invalid bounds" in p.status
    checks.append("invalid bounds reject Bake without terminating")

    p.configureBake({"autoBounds": True, "gridCounts": uint3(4, 3, 4), "samplesPerProbe": 80, "maxBounces": 2})
    frames(2)
    waiting(p)
    # Matching load is non-fatal when there is no compatible cache.
    p.loadCache()
    frames()
    waiting(p)
    assert "Cache not loaded" in p.status
    checks.append("manual load failure waits without fallback bake")

    p.bake()
    frames(2)
    assert p.baking and p.completedSamples == 8
    p.configureBake({"samplesPerFrame": 8})
    frames()
    assert p.completedSamples == 16 and p.baking
    p.cancelBake()
    frames(2)
    waiting(p)
    assert (cornell_cache.read_bytes() if cornell_cache.exists() else None) == backups[cornell_cache]
    checks.append("batch change preserves progress; cancel does not save partial cache")

    p.bake()
    finish(p)
    assert p.completedSamples == 80 and cornell_cache.exists()
    capture("baked")
    baked_bytes = cornell_cache.read_bytes()
    p.loadCache()
    frames()
    assert p.ready and not p.baking
    capture("loaded")
    pos = m.scene.camera.position
    m.scene.camera.position = float3(pos.x + 0.02, pos.y, pos.z)
    frames(2)
    assert p.ready and p.completedSamples == 80
    checks.append("Bake saves; Load succeeds; camera movement preserves Ready")

    p.configureBake({"samplesPerProbe": 96, "gridCounts": uint3(3, 4, 3)})
    frames(2)
    waiting(p)
    p.bake()
    frames()
    assert p.baking
    p.configureBake({"maxBounces": 1})
    frames()
    waiting(p)
    p.configureBake({"samplesPerProbe": 80, "gridCounts": uint3(4, 3, 4), "maxBounces": 2})
    p.loadCache()
    frames()
    assert p.ready
    material = m.scene.getMaterial(0)
    material.baseColor = float4(0.1, 0.2, 0.3, 1)
    frames(2)
    waiting(p)
    assert "Scene changed" in p.status
    checks.append("parameter edits and material changes invalidate without exiting")

    # Explicit bounds from the old scene must not leak into the new scene.
    p.configureBake({"gridMin": float3(-1), "gridMax": float3(1)})
    m.loadScene("F:/media/test_scenes/grey_and_white_room/grey_and_white_room.pyscene")
    frames(3)
    waiting(p)
    room_cache = protect_cache(p)
    assert room_cache != cornell_cache
    assert "gridMin" not in p.settings
    p.bake()
    finish(p)
    assert room_cache.exists() and cornell_cache.read_bytes() == baked_bytes
    capture("room-baked")
    m.loadScene("F:/media/test_scenes/cornell_box.pyscene")
    frames(3)
    waiting(p)
    assert Path(p.cacheFile).resolve() == cornell_cache
    p.loadCache()
    frames()
    assert p.ready
    capture("cornell-return")
    checks.append("Cornell -> Room -> Cornell resets bounds and isolates caches")

    # Save failure should preserve a usable completed GPU bake in manual mode.
    blocked = output / "not-a-directory"
    blocked.write_text("intentional save failure fixture", encoding="utf-8")
    failure_graph = RenderGraph("SaveFailureValidation")
    failure_graph.addPass(createPass("VBufferRT", {"samplePattern": "Center"}), "Visibility")
    failure_graph.addPass(createPass("TraditionalProbeGI", {
        "mode": "manual", "gridCounts": uint3(2), "samplesPerProbe": 4,
        "samplesPerFrame": 4, "cacheFile": str(blocked / "cache.shprobe"),
    }), "Probes")
    failure_graph.addEdge("Visibility.vbuffer", "Probes.vbuffer")
    failure_graph.markOutput("Probes.color")
    m.addGraph(failure_graph)
    m.setActiveGraph(failure_graph)
    frames()
    failing = failure_graph.getPass("Probes")
    failing.bake()
    frames()
    assert failing.ready and "saving failed" in failing.status
    checks.append("save failure preserves completed GPU bake and reports error")
    (output / "interaction.json").write_text(json.dumps({"passed": checks}, indent=2), encoding="utf-8")
    print("INTERACTIVE PROBE VALIDATION PASSED", checks)
    exit()
except Exception:
    traceback.print_exc()
    if "g" in globals():
        m.removeGraph(g)
    if "failure_graph" in globals():
        m.removeGraph(failure_graph)
    exit(1)
finally:
    # Only restore/remove exact cache paths created by this test inside the verified build directory.
    for path, original in backups.items():
        assert path.parent == cache_root and path.suffix == ".shprobe"
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
