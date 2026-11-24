"""Rigenera data/registry.json dal file lib/catalog_sources.dart dell'app.
Uso: python tools/gen_registry.py percorso/catalog_sources.dart"""
import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding="utf-8")
rows = re.findall(r'CatalogSource\("((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)",\s*(null|"[^"]*"),\s*'
                  r'(null|"[^"]*"),\s*(null|"[^"]*"),\s*"([^"]*)",\s*(true|false)\)', src)
n = lambda v: None if v == "null" else v.strip('"')
out = [dict(name=a, canonical=b, domain=n(c), platform=n(d), slug=n(e), kind=f, physical=(g == "true"))
       for a, b, c, d, e, f, g in rows]
Path(__file__).resolve().parent.parent.joinpath("data", "registry.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(out), "voci")
