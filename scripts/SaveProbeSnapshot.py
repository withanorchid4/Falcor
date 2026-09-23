"""File > Load Script: capture current static Probe GI view without GUI automation."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_snapshot import save_snapshot
save_snapshot(m,renderFrame)
