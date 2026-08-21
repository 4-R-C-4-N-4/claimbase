import os
import sys
from pathlib import Path

# src layout without requiring an install step — the seam tests must run on a
# fresh checkout before anything is built.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# The MCP query log is testing data harvested from real agent traffic. Test
# traffic must not land in it (the sandbox probe already polluted the live
# store once — findings 2026-08-12). The MCP tests spawn the server with an
# inherited environment, so disabling here covers the subprocess too.
os.environ["CLAIMBASE_QUERY_LOG"] = ""
