"""Regenerate the synthetic OPENFRMT sample: python tools/generate_sample.py [out_root]"""
import sys
from pathlib import Path

from mabat.sampledata import write_sample

if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "sample"
    print(write_sample(root))
