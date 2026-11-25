"""Ambiente completo per gli scenari: server finto Open Food Facts, catalogo finto, negozi a Roma."""
import contextlib
import json
import os
import tempfile

from fastapi.testclient import TestClient
from helpers import G, catalog_router, off_router, serve2
from probe.probe import Fetcher, Robots
from server import catalogs, products, stores
from server.app import create_app
from server.config import Settings
from server.db import connect

LAT, LON = 41.9028, 12.4964
MODE = {}          # impostato dalla fixture db_mode: {} = SQLite, {'turso': FakeTurso} = Turso finto


def el(i, name, brand=None, dlat=0.0, dlon=0.0):
    tags = {"shop": "supermarket", "name": name, "addr:street": "Via Prova", "addr:housenumber": str(i)}
    if brand:
        tags["brand"] = brand
    return {"type": "node", "id": i, "lat": LAT + dlat, "lon": LON + dlon, "tags": tags}


STORES = [el(1, "Conad City", "Conad", 0.0027), el(2, "Conad Superstore", "Conad", 0.0081), el(3, "Conad Lontano", "Conad", 0.018),
          el(4, "Lidl", None, 0.0, 0.006), el(5, "Eurospin", None, -0.009), el(6, "Da Mario", None, 0.0018),
          el(7, "Esselunga", None, -0.018)]
OFF_PRODUCT = {G: {"product_name": "Acqua Minerale Naturale", "brands": "Uliveto", "quantity": "1,5 L",
                   "image_front_small_url": "http://img.example/uliveto.jpg"}}


@contextlib.contextmanager
def env(mode="json", delay=0.0, with_profile=True, budget=5.0, stores_on=True, off_products=None, chain="Conad"):
    tmp = tempfile.mkdtemp()
    cat_router, cat_hits = catalog_router(mode, G, delay=delay)
    off_r, off_hits = off_router(OFF_PRODUCT if off_products is None else off_products)
    cat_srv, cat_base = serve2(cat_router)
    off_srv, off_base = serve2(off_r)
    s = Settings(db_path=os.path.join(tmp, "t.db"), off_base=off_base.rstrip("/"), request_interval_s=0,
                 index_budget_s=budget, contact="test@example.org",
                 turso_url=MODE["turso"].url if MODE.get("turso") else "",
                 turso_token=MODE["turso"].token if MODE.get("turso") else "")
    conn = connect(s.db_path, s)
    if stores_on:
        stores.upsert(conn, stores.parse_overpass({"elements": STORES}))
    f = Fetcher(min_interval=0, timeout=3, ua=s.user_agent)
    if with_profile:
        t = {"chain": chain, "name": chain, "base": cat_base}
        catalogs.save_profile(conn, t, catalogs.discover_site(t, f, Robots(f)))
    conn.commit()
    conn.close()
    client = TestClient(create_app(s, f))
    try:
        yield client, {"catalog": cat_hits, "off": off_hits, "settings": s}
    finally:
        cat_srv.shutdown()
        off_srv.shutdown()


def shape(x):
    """Struttura di un JSON (chiavi e tipi), ignorando i valori: serve a tenere server e app allineati."""
    if isinstance(x, dict):
        return {k: shape(v) for k, v in sorted(x.items())}
    if isinstance(x, list):
        return [shape(x[0])] if x else []
    return "null" if x is None else type(x).__name__
