"""Official Cornell geometry with editable Falcor light and probe inputs."""
import json
import math
import os
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]


def load_config():
    path = Path(os.environ.get("CORNELL_RTXGI_CONFIG", DIRECTORY / "CornellRTXGI.json"))
    config = json.loads(path.read_text(encoding="utf-8-sig"))

    def vector(value, label):
        if not isinstance(value, list) or len(value) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value
        ):
            raise ValueError(f"{path}: {label} must contain three finite numbers")
        return value

    for name in ("directionalLight", "ceilingPointLight"):
        light = config[name]
        if not isinstance(light["enabled"], bool):
            raise ValueError(f"{path}: {name}.enabled must be true or false")
        color = vector(light["color"], name + ".color")
        intensity = light["intensity"]
        if not isinstance(intensity, (int, float)) or not math.isfinite(intensity) or intensity < 0 or min(color) < 0:
            raise ValueError(f"{path}: {name} color and intensity must be finite and nonnegative")
    direction = vector(config["directionalLight"]["direction"], "directionalLight.direction")
    if sum(v * v for v in direction) <= 1e-12:
        raise ValueError(f"{path}: directionalLight.direction must be nonzero")
    vector(config["ceilingPointLight"]["position"], "ceilingPointLight.position")
    camera = config["camera"]
    for key in ("position", "target", "up"):
        vector(camera[key], "camera." + key)
    if not 1 < camera["verticalFovDegrees"] < 179:
        raise ValueError(f"{path}: camera.verticalFovDegrees must be between 1 and 179")
    if not math.isfinite(config["display"]["exposureStops"]) or not -10 <= config["display"]["exposureStops"] <= 10:
        raise ValueError(f"{path}: display.exposureStops must be finite and between -10 and 10")
    volume = config["ddgi"]
    counts = vector(volume["gridCounts"], "ddgi.gridCounts")
    low = vector(volume["gridMin"], "ddgi.gridMin")
    high = vector(volume["gridMax"], "ddgi.gridMax")
    if any(not isinstance(n, int) or n < 2 for n in counts) or any(b <= a for a, b in zip(low, high)):
        raise ValueError(f"{path}: invalid DDGI grid counts or bounds")
    for key in ("normalBiasWorld", "viewBiasWorld", "hysteresis"):
        if not math.isfinite(volume[key]) or volume[key] < 0:
            raise ValueError(f"{path}: ddgi.{key} must be finite and nonnegative")
    return config


def model_path():
    relative = "samples/test-harness/data/gltf/cornell/cornell.glb"
    for source in (ROOT / "build/windows-vs2022/_deps/rtxgi_ddgi-src",
                   ROOT / "build/official-ddgi/RTXGI-DDGI-1.3.7"):
        path = source / relative
        if path.is_file():
            return path
    raise FileNotFoundError("Official RTXGI Cornell GLB is missing. Configure the Falcor RTXGI dependency first.")


def build_scene(builder):
    from falcor import Camera, DirectionalLight, PointLight, float3
    config = load_config()
    builder.importScene(str(model_path()))
    for key, name, light_type in (("directionalLight", "Sun", DirectionalLight),
                                  ("ceilingPointLight", "Ceiling Point", PointLight)):
        options = config[key]
        light = light_type(name)
        light.intensity = float3(*options["color"]) * options["intensity"]
        light.active = options["enabled"]
        light.animated = False
        if key == "directionalLight":
            light.direction = float3(*options["direction"])
        else:
            light.position = float3(*options["position"])
        builder.addLight(light)
    options = config["camera"]
    camera = Camera()
    camera.position = float3(*options["position"])
    camera.target = float3(*options["target"])
    camera.up = float3(*options["up"])
    camera.frameHeight = 24.0
    camera.focalLength = 12.0 / math.tan(math.radians(options["verticalFovDegrees"]) / 2.0)
    builder.addCamera(camera)


def configure_graph(graph):
    from falcor import float3, uint3
    settings = load_config()
    config = settings["ddgi"]
    spacing = min((b - a) / (n - 1) for a, b, n in zip(config["gridMin"], config["gridMax"], config["gridCounts"]))
    graph.getPass("DDGI").set_properties({
        "gridCounts": uint3(*config["gridCounts"]),
        "gridMin": float3(*config["gridMin"]), "gridMax": float3(*config["gridMax"]),
        "autoBounds": False, "raysPerProbe": config["raysPerProbe"], "hysteresis": config["hysteresis"],
        "normalBias": config["normalBiasWorld"] / spacing, "viewBias": config["viewBiasWorld"] / spacing,
        "enableRelocation": True, "enableClassification": True, "useWRC": False,
    })
    # Falcor's ACES operator multiplies by 0.6; the official ACESFilm does not.
    # Cancel that factor so the configured stops have the same pre-curve exposure.
    graph.updatePass("Display", {"autoExposure": False, "useSceneMetadata": False,
        "operator": "Aces", "filmSpeed": 100.0, "fNumber": 1.0, "shutter": 1.0,
        "exposureCompensation": settings["display"]["exposureStops"] - math.log2(0.6)})
