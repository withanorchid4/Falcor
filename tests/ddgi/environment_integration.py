"""GPU captures for SDK-style sky injection. Run via run_environment_validation.py."""
from falcor import *
from pathlib import Path
import json
import os
import runpy
import traceback

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["DDGI_ENV_VALIDATION_OUTPUT"])


def frames(count):
    for _ in range(count):
        renderFrame()


def capture(tag):
    m.frameCapture.outputDir = str(OUT)
    m.frameCapture.baseFilename = tag
    m.frameCapture.capture()


try:
    graph = runpy.run_path(str(ROOT / "scripts/RTXGIDDGI.py"))["RTXGIDDGI"]
    for channel in ("DDGI.color", "DDGI.indirect", "DirectLighting.diffuseIllumination",
                    "DirectLighting.diffuseReflectance", "DirectLighting.specularIllumination",
                    "DirectLighting.emission", "DirectModulate.output"):
        graph.markOutput(channel)
    m.addGraph(graph)
    m.setActiveGraph(graph)
    m.loadScene(str(OUT / "sky-plane.pyscene"))
    m.clock.pause()
    m.scene.camera.animated = False
    graph.getPass("DirectDenoiser").set_properties({"enabled": False})
    ddgi = graph.getPass("DDGI")
    ddgi.set_properties({"autoBounds": False, "gridMin": float3(-3, 0.1, -3),
                         "gridMax": float3(3, 2, 3), "enableRelocation": False,
                         "enableClassification": False, "hysteresis": 0.9})
    records = {}
    for name, options in (
        ("original", {"useWRC": False}),
        ("wrc-bypass", {"useWRC": True, "wrcBypassSharing": True}),
        ("wrc", {"useWRC": True, "wrcBypassSharing": False}),
    ):
        ddgi.set_properties(options)
        ddgi.reset()
        frames(128)
        records[name] = dict(ddgi.stats)
        assert records[name]["finite"], records[name]
        capture(name)

    ddgi.set_properties({"useWRC": False, "useRTXDI": False})
    ddgi.reset()
    frames(128)
    ddgi.set_properties({"updateEnabled": False})
    frames(1)
    capture("fallback")
    ddgi.set_properties({"indirectOnly": True})
    frames(1)
    capture("indirect-only")

    m.scene.envMap.intensity = 0.25
    ddgi.set_properties({"useWRC": True, "updateEnabled": True, "indirectOnly": False, "useRTXDI": True})
    ddgi.reset()
    frames(128)
    capture("dim-sky")
    m.scene.envMap.intensity = 1.0

    # The generic RTXDI pass must still support sky diffuse outside the DDGI graph.
    options = dict(graph.getPass("DirectLighting").properties)
    options["excludeEnvDiffuse"] = False
    graph.updatePass("DirectLighting", options)
    frames(32)
    capture("rtxdi-default")

    m.scene.envMap.intensity = 0.0
    ddgi.set_properties({"useWRC": True, "updateEnabled": True, "indirectOnly": False})
    ddgi.reset()
    frames(64)
    capture("black-sky")
    records["black-sky"] = dict(ddgi.stats)
    assert records["black-sky"]["finite"], records["black-sky"]
    (OUT / "integration.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
except Exception:
    (OUT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
finally:
    exit()
