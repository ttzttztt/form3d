"""Worker modules are standalone scripts that import their siblings by bare name."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "workers", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
