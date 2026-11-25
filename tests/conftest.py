import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).resolve().parent / "fixtures" / "pages"


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---- fixture per gli scenari del servizio: ogni scenario gira su SQLite e su (finto) Turso ----
sys.path.insert(0, str(Path(__file__).resolve().parent / "srv"))

import pytest  # noqa: E402


@pytest.fixture(params=["sqlite", "turso"])
def db_mode(request, monkeypatch):
    import scenarios
    from fake_turso import FakeTurso
    ft = None
    if request.param == "turso":
        ft = FakeTurso()
        monkeypatch.setenv("PV_TURSO_URL", ft.url)
        monkeypatch.setenv("PV_TURSO_TOKEN", ft.token)
        scenarios.MODE = {"turso": ft}
    else:
        monkeypatch.delenv("PV_TURSO_URL", raising=False)
        monkeypatch.delenv("PV_TURSO_TOKEN", raising=False)
        scenarios.MODE = {}
    yield request.param
    scenarios.MODE = {}
    if ft:
        ft.close()
