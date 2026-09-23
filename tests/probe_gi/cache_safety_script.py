"""Exercise failed atomic replacement against an existing cache, then successful retry."""
from falcor import *
from pathlib import Path
import ctypes as ct
import json
import traceback

output = Path("F:/build/probe-cache-repair")
target = output / "atomic-lock-test.shprobe"
sentinel = b"existing cache must survive a failed replacement\n"
target.write_bytes(sentinel)
handle = None
kernel = ct.WinDLL("kernel32", use_last_error=True)
kernel.CreateFileW.argtypes = [ct.c_wchar_p, ct.c_uint32, ct.c_uint32, ct.c_void_p, ct.c_uint32, ct.c_uint32, ct.c_void_p]
kernel.CreateFileW.restype = ct.c_void_p
kernel.CloseHandle.argtypes = [ct.c_void_p]
kernel.CloseHandle.restype = ct.c_int

try:
    g = RenderGraph("CacheSafety")
    g.addPass(createPass("VBufferRT", {"samplePattern": "Center"}), "Visibility")
    g.addPass(createPass("TraditionalProbeGI", {
        "mode": "manual", "cacheFile": str(target), "gridCounts": uint3(2),
        "samplesPerProbe": 4, "samplesPerFrame": 4,
    }), "Probes")
    g.addEdge("Visibility.vbuffer", "Probes.vbuffer")
    g.markOutput("Probes.color")
    m.addGraph(g)
    m.loadScene("F:/media/test_scenes/cornell_box.pyscene")
    m.clock.pause()
    renderFrame()
    p = g.getPass("Probes")
    # The existing destination may be read, but cannot be deleted/replaced while held.
    handle = kernel.CreateFileW(str(target), 0x80000000, 1, None, 3, 0, None)
    assert handle not in (None, ct.c_void_p(-1).value), ct.get_last_error()
    p.bake()
    renderFrame()
    assert p.ready and "saving failed" in p.status, p.status
    assert target.read_bytes() == sentinel
    assert not list(output.glob(target.name + ".tmp-*"))
    kernel.CloseHandle(handle)
    handle = None
    p.bake()
    renderFrame()
    assert p.ready and "saved" in p.status, p.status
    assert target.read_bytes().startswith(b"FALCOR_PROBE_SH 1\n")
    assert not list(output.glob(target.name + ".tmp-*"))
    p.loadCache()
    renderFrame()
    assert p.ready and "loaded" in p.status, p.status
    (output / "atomic-results.json").write_text(json.dumps({
        "failed_replace_preserves_existing_bytes": True,
        "temporary_files_cleaned": True,
        "successful_retry_replaces_and_loads": True,
    }, indent=2), encoding="utf-8")
    exit()
except Exception:
    traceback.print_exc()
    if "g" in globals(): m.removeGraph(g)
    exit(1)
finally:
    if handle not in (None, ct.c_void_p(-1).value): kernel.CloseHandle(handle)
