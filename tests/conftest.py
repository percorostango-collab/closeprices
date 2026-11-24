import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).resolve().parent / "fixtures" / "pages"


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")
