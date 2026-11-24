"""Registro dei cataloghi (70 voci dall'Excel) e riconoscimento di una scheda dall'URL.
Porta di sourceForUrl in lib/chains.dart, con lo stesso comportamento (anche i suoi limiti)."""
import json
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(__file__).resolve().parent.parent / "data"


def load_registry() -> list:
    return json.loads((DATA / "registry.json").read_text(encoding="utf-8"))


def registrable(host: str) -> str:
    p = host.lower().split(".")
    return ".".join(p) if len(p) <= 2 else ".".join(p[-2:])


def source_for_url(url: str, registry=None):
    reg = registry if registry is not None else load_registry()
    u = urlparse(url)
    if not u.hostname:
        return None
    host = registrable(u.hostname)
    segs = [s for s in u.path.split("/") if s]
    for s in reg:
        if s["platform"] == "everli" and host == "everli.com":
            if "spesa" in segs:
                i = segs.index("spesa")
                if i + 1 < len(segs) and segs[i + 1] == s["slug"]:
                    return s
        elif s["platform"] == "cosicomodo" and host == "cosicomodo.it":
            if segs and segs[0] == s["slug"]:
                return s
    for s in reg:
        if s["platform"] is None and s["domain"] == host:
            return s
    return None


def sources_for_chain(canonical: str, registry=None) -> list:
    reg = registry if registry is not None else load_registry()
    return [s for s in reg if s["canonical"] == canonical and s["physical"]]


def duplicate_domains(registry=None) -> dict:
    reg = registry if registry is not None else load_registry()
    seen = {}
    for s in reg:
        if s["domain"]:
            seen.setdefault(s["domain"], []).append(s["name"])
    return {d: n for d, n in seen.items() if len(n) > 1}
