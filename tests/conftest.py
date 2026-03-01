"""Pytest configuration — add scripts/ to sys.path so `import conclave` works."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
