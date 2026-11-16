"""Check sky energy, diffuse double counting, WRC, fallback, and RTXDI defaults on GPU."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from check_rtxdi_results import read_exr


def check(out):
    def read(tag, channel):
        paths = list(out.glob(f"{tag}.{channel}.*.exr"))
        assert len(paths) == 1, (tag, channel, paths)
        return read_exr(paths[0])[2]

    for path in out.glob("*.exr"):
        read_exr(path)  # Reject non-finite values in every captured channel.
    reflectance = read("original", "DirectLighting.diffuseReflectance")
    size = len(reflectance) // 3
    surface = [i for i in range(size) if reflectance[i] > 0.1]
    background = [i for i in range(size) if reflectance[i] == 0]
    assert surface and background

    def surface_mean(values):
        return sum(values[c * size + i] for c in range(3) for i in surface) / (3 * len(surface))

    report = {}
    for tag in ("original", "wrc-bypass", "wrc"):
        indirect = read(tag, "DDGI.indirect")
        direct = read(tag, "DirectModulate.output")
        color = read(tag, "DDGI.color")
        diffuse = read(tag, "DirectLighting.diffuseIllumination")
        assert max(map(abs, diffuse)) < 1e-6, (tag, "Sky diffuse counted in direct lighting")
        # DDGI must receive sky energy; this is a routing test, not an angular accuracy test.
        energy = surface_mean(indirect)
        assert energy > 0.01, (tag, "Missing sky diffuse energy", energy)
        error = max(abs(a - b - c) for a, b, c in zip(color, direct, indirect))
        assert error < 1e-5, (tag, "Composition", error)
        specular = surface_mean(read(tag, "DirectLighting.specularIllumination"))
        assert specular > 1e-5, (tag, "Lost environment specular")
        emission = read(tag, "DirectLighting.emission")
        assert abs(sum(emission[i] for i in background) / len(background) - 1) < 1e-4
        report[tag] = {"sky_diffuse_mean": energy, "composition_error": error,
                       "environment_specular_mean": specular}
    original = read("original", "DDGI.indirect")
    bypass = read("wrc-bypass", "DDGI.indirect")
    report["bypass_max_error"] = max(abs(a - b) for a, b in zip(original, bypass))
    assert report["bypass_max_error"] < 1e-5, report
    dim_ratio = surface_mean(read("dim-sky", "DDGI.indirect")) / report["wrc"]["sky_diffuse_mean"]
    assert abs(dim_ratio - 0.25) < 0.01, ("Sky intensity response", dim_ratio)
    report["sky_quarter_intensity_ratio"] = dim_ratio
    fallback = read("fallback", "DDGI.color")
    indirect = read("fallback", "DDGI.indirect")
    assert surface_mean(indirect) > 0.01, "Fallback lost DDGI sky lighting"
    # A second diffuse sky term would add about 0.5; only specular may remain here.
    residual = surface_mean([a - b for a, b in zip(fallback, indirect)])
    assert 0 <= residual < 0.2, ("Fallback duplicated sky diffuse", residual)
    assert max(abs(a - b) for a, b in zip(read("indirect-only", "DDGI.color"),
                                         read("indirect-only", "DDGI.indirect"))) < 1e-6
    assert surface_mean(read("rtxdi-default", "DirectLighting.diffuseIllumination")) > 0.1
    assert max(map(abs, read("black-sky", "DDGI.color"))) < 1e-6
    report["fallback_specular_mean"] = residual
    report["passed"] = True
    (out / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("F:/"))
    parser.add_argument("--reuse-renders", type=Path)
    args = parser.parse_args()
    out = args.reuse_renders
    if out is None:
        root = args.root
        out = root / "build/ddgi-environment-validation" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        out.mkdir(parents=True)
        # Small, uncompressed Radiance RGBE image: constant linear white, no external asset.
        (out / "unit-sky.hdr").write_bytes(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 2 +X 4\n" + bytes([128, 128, 128, 129]) * 8)
        (out / "sky-plane.pyscene").write_text('''from falcor import *
material = StandardMaterial("Grey")
material.baseColor = float4(0.5, 0.5, 0.5, 1)
material.roughness = 0.5
sceneBuilder.addMeshInstance(sceneBuilder.addNode("Floor", Transform(scaling=float3(8, 1, 8))),
    sceneBuilder.addTriangleMesh(TriangleMesh.createQuad(), material))
sceneBuilder.envMap = EnvMap("unit-sky.hdr")
camera = Camera()
camera.position = float3(0, 2, 4)
camera.target = float3(0, 0.6, 0)
camera.up = float3(0, 1, 0)
camera.focalLength = 25
sceneBuilder.addCamera(camera)
''', encoding="utf-8")
        env = os.environ.copy()
        env.update({"DDGI_ENV_VALIDATION_OUTPUT": str(out), "FALCOR_MEDIA_FOLDERS": str(root / "media")})
        command = [str(root / "build/windows-vs2022/bin/Release/Mogwai.exe"), "--device-type", "d3d12",
                   "--headless", "--deferred", "--script", str(root / "tests/ddgi/environment_integration.py"),
                   "--width", "160", "--height", "120", "--logfile", str(out / "mogwai.log")]
        print("Environment validation: " + str(out), flush=True)
        with (out / "console.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, (result.returncode, out)
    failure = out / "failure.txt"
    assert not failure.exists(), failure.read_text(encoding="utf-8") if failure.exists() else ""
    assert (out / "integration.json").is_file(), out
    assert "(Error)" not in (out / "mogwai.log").read_text(encoding="utf-8", errors="replace")
    check(out)


if __name__ == "__main__":
    main()
