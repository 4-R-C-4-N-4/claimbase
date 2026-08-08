import sys
from pathlib import Path

# src layout without requiring an install step — the seam tests must run on a
# fresh checkout before anything is built.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
