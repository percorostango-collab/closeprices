"""Rigenera gli esempi di risposta (tests/fixtures/api/*.json) dal server vero.
L'app li legge nel suo controllo di compatibilità: se il formato cambia, il controllo fallisce.
Uso:  python tools/dump_contract.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests" / "srv")]
from helpers import G  # noqa: E402
from scenarios import LAT, LON, env  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "api"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    from contract_cases import CASES as cases  # noqa: E402
    for name, (kw, params) in cases.items():
        with env(**kw) as (c, _):
            (OUT / f"{name}.json").write_text(json.dumps(c.get("/v1/scan", params=params).json(),
                                                          ensure_ascii=False, indent=1), encoding="utf-8")
        print("scritto", name)


if __name__ == "__main__":
    main()
