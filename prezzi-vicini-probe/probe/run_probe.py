"""Uso:  python -m probe.run_probe [--only sites,off,osm] [--max-sites N] [--products N] [--out results]"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from probe.probe import (Fetcher, probe_off, probe_osm, render_summary, run_sites,  # noqa: E402
                         targets_from_registry)
from pvcore.registry import load_registry  # noqa: E402

EXTRA = [{"name": "Despar Sicilia (shop regionale)", "base": "https://shop.desparsicilia.it/", "kind": "ecommerce"}]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="sites,off,osm")
    ap.add_argument("--max-sites", type=int, default=0)
    ap.add_argument("--products", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "results"))
    ap.add_argument("--min-interval", type=float, default=1.5)
    a = ap.parse_args(argv)
    only = set(a.only.split(","))
    gold = json.loads((ROOT / "data" / "golden.json").read_text(encoding="utf-8"))["prodotti"]
    probe_products = [p for p in gold if p.get("probe")][: a.products]
    f = Fetcher(min_interval=a.min_interval)
    res = {"generato": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "prodotti_provati": [p["gtin"] for p in probe_products]}
    if "off" in only:
        res["off"] = probe_off(gold, f)
    if "osm" in only:
        res["osm"] = probe_osm()
    if "sites" in only:
        t = targets_from_registry(load_registry(), EXTRA)
        if a.max_sites:
            t = t[: a.max_sites]
        res["siti"] = run_sites(t, probe_products, f)
    res["richieste"] = f.requests_made
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary.md").write_text(render_summary(res), encoding="utf-8")
    print(render_summary(res))


if __name__ == "__main__":
    main()
