"""Run isolated RTXDI + NRD + DDGI D3D12 checks with the Release build."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("F:/"))
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--reuse-renders", type=Path)
    args = parser.parse_args()
    root = args.root
    if args.reuse_renders:
        out = args.reuse_renders
    else:
        out = root / "build/nrd-ddgi-validation" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        out.mkdir(parents=True)
        env = os.environ.copy()
        env.update({"NRD_DDGI_VALIDATION_OUTPUT": str(out), "FALCOR_MEDIA_FOLDERS": str(root / "media"),
                    "FALCOR_SCENE_FOLDER": str(root / "media")})
        executable = root / "build/windows-vs2022/bin/Release/Mogwai.exe"
        command = [str(executable), "--device-type", "d3d12", "--headless", "--deferred",
                   "--script", str(root / "tests/ddgi/nrd_integration.py"), "--width", "320", "--height", "240",
                   "--logfile", str(out / "mogwai.log")]
        print("RTXDI + NRD + DDGI validation output: " + str(out), flush=True)
        with (out / "console.log").open("w", encoding="utf-8") as stream:
            result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=args.timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        failure = out / "failure.txt"
        if failure.exists():
            print(failure.read_text(encoding="utf-8"), flush=True)
        assert result.returncode == 0 and not failure.exists(), (result.returncode, str(out))
        assert (out / "integration.json").is_file(), "Missing completion record: " + str(out)
        log = (out / "mogwai.log").read_text(encoding="utf-8", errors="replace")
        assert "(Error)" not in log, "GPU/compilation error in " + str(out / "mogwai.log")
    subprocess.run([sys.executable, str(root / "tests/ddgi/check_nrd_results.py"), str(out)], cwd=root, check=True)


if __name__ == "__main__":
    main()
