"""Run without uv or project dependencies: python scripts/local-chat.py setup|start|account."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from modam.local_setup import main  # noqa: E402

main(root)
