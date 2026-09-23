"""Standard-library-only checks for SH math, probe cache and Falcor EXR captures.

Usage: python tests/probe_gi/check_results.py [output-dir] [cache-file]
Uses ctypes and Falcor's existing FreeImage.dll to read FrameCapture EXRs.
"""
import array
import json
import math
from pathlib import Path
import struct
import sys


def read_exr(path, require_finite=True):
    # Use the same bundled image library as Falcor; supports its PIZ EXR output.
    import ctypes as ct
    import os
    dll_dir = Path(__file__).resolve().parents[2] / 'build/windows-vs2022/bin/Release'
    with os.add_dll_directory(str(dll_dir)):
        lib = ct.WinDLL(str(dll_dir / 'FreeImage.dll'))
        signatures = {
            'FreeImage_GetFileTypeU': ([ct.c_wchar_p, ct.c_int], ct.c_int),
            'FreeImage_LoadU': ([ct.c_int, ct.c_wchar_p, ct.c_int], ct.c_void_p),
            'FreeImage_Unload': ([ct.c_void_p], None),
            'FreeImage_GetWidth': ([ct.c_void_p], ct.c_uint),
            'FreeImage_GetHeight': ([ct.c_void_p], ct.c_uint),
            'FreeImage_GetPitch': ([ct.c_void_p], ct.c_uint),
            'FreeImage_GetImageType': ([ct.c_void_p], ct.c_int),
            'FreeImage_GetBits': ([ct.c_void_p], ct.c_void_p),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, result
        filename = str(Path(path).resolve())
        fmt = lib.FreeImage_GetFileTypeU(filename, 0)
        bitmap = lib.FreeImage_LoadU(fmt, filename, 0)
        assert bitmap, f'Cannot read EXR: {path}'
        try:
            w, h = lib.FreeImage_GetWidth(bitmap), lib.FreeImage_GetHeight(bitmap)
            typ = lib.FreeImage_GetImageType(bitmap)
            assert typ in (11, 12), f'Expected RGBF/RGBAF, got {typ}'
            channels = 3 if typ == 11 else 4
            pitch, ptr = lib.FreeImage_GetPitch(bitmap), lib.FreeImage_GetBits(bitmap)
            rgb = [array.array('f') for _ in range(3)]
            for row in range(h):
                values = struct.unpack(f'<{w*channels}f', ct.string_at(ptr + row*pitch, w*channels*4))
                for k in range(3):
                    rgb[k].extend(values[k::channels])
            result = [v for channel in rgb for v in channel]
            if require_finite:
                assert all(math.isfinite(v) for v in result), f'Non-finite pixels: {path}'
            return w, h, result
        finally:
            lib.FreeImage_Unload(bitmap)

def check_math():
    # Analytic constant-environment SH: only c00 = L * sqrt(4*pi) is nonzero.
    irradiance = math.sqrt(4 * math.pi) * 0.2820947918 * math.pi
    assert abs(irradiance - math.pi) < 1e-8
    # Independently integrate the real basis with deterministic sphere quadrature.
    sums = [0.0] * 9
    n = 20000
    for i in range(n):
        z = 1 - 2 * (i + 0.5) / n
        phi = i * math.pi * (3 - math.sqrt(5))
        r = math.sqrt(1 - z * z)
        x, y = r * math.cos(phi), r * math.sin(phi)
        b = [0.2820947918, .4886025119*y, .4886025119*z, .4886025119*x,
             1.0925484306*x*y, 1.0925484306*y*z, .3153915653*(3*z*z-1),
             1.0925484306*x*z, .5462742153*(x*x-y*y)]
        for k in range(9):
            sums[k] += b[k] * 4 * math.pi / n
    assert abs(sums[0] - math.sqrt(4 * math.pi)) < 1e-7
    assert max(map(abs, sums[1:])) < 1e-4
    for t in ((0, 0, 0), (1, 1, 1), (.1, .9, .5), (1, .5, 0)):
        weights = [math.prod(t[a] if (c >> a) & 1 else 1-t[a] for a in range(3)) for c in range(8)]
        assert min(weights) >= 0 and abs(sum(weights)-1) < 1e-12
    return "constant SH / cosine convolution / sphere integration / trilinear boundary weights passed"


def check_cache(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "FALCOR_PROBE_SH 1"
    nx, ny, nz, samples, bounces = map(int, lines[4].split())
    assert all(2 <= v <= 32 for v in (nx, ny, nz))
    coeff = [float(v) for line in lines[6:] for v in line.split()]
    assert len(coeff) == nx * ny * nz * 27
    assert all(math.isfinite(v) for v in coeff) and max(map(abs, coeff)) > 0
    return {"probes": nx*ny*nz, "samples": samples, "bounces": bounces,
            "bytes": Path(path).stat().st_size, "max_abs_coefficient": max(map(abs, coeff))}


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "build/probe-validation")
    cache = Path(sys.argv[2] if len(sys.argv) > 2 else "build/probes/cornell.shprobe")
    report = {"math": check_math(), "cache": check_cache(cache)}
    def read(tag, channel):
        files = list(output.glob(f"{tag}.{channel}.*.exr"))
        assert len(files) == 1, (tag, channel, files)
        return read_exr(files[0])[2]
    baked = read("bake", "Probes.color")
    loaded = read("load", "Probes.color")
    off = read("off", "Probes.color")
    probes = read("load", "Probes.probeLighting")
    assert len(baked) == len(loaded) == len(off)
    difference = max(abs(a-b) for a, b in zip(baked, loaded))
    assert difference < 2e-5, difference
    mean_contribution = sum(a-b for a, b in zip(loaded, off)) / len(off)
    assert mean_contribution > 0 and max(probes) > 0
    report.update({"bake_load_max_abs_error": difference, "mean_probe_contribution": mean_contribution,
                   "max_probe_lighting": max(probes), "all_hdr_finite": True})
    refs = list(output.glob("reference.Accum.output.*.exr"))
    if refs:
        reference = read_exr(refs[0])[2]
        assert len(reference) == len(loaded)
        report["reference_rmse"] = math.sqrt(sum((a-b)**2 for a, b in zip(reference, loaded))/len(loaded))
    print(json.dumps(report, indent=2))
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
