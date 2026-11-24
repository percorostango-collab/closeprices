"""Punti vendita: caricati UNA volta da OpenStreetMap nel database. La scansione fa solo una query."""
import json
import math
import time
from collections import Counter, defaultdict

import requests

from .chains import FOOD, classify
from .db import now_iso

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
# Italia a tessere di 2 gradi: ogni richiesta resta piccola e riprovabile
ITALY = (35.4, 6.5, 47.2, 18.9)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _addr(t):
    street = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
    city = t.get("addr:city")
    return ", ".join(x for x in (street, city) if x) or None


def parse_overpass(data) -> list:
    out = []
    for e in data.get("elements", []):
        t = e.get("tags") or {}
        lat = e.get("lat") if e.get("type") == "node" else (e.get("center") or {}).get("lat")
        lon = e.get("lon") if e.get("type") == "node" else (e.get("center") or {}).get("lon")
        if lat is None or lon is None or e.get("id") is None:
            continue
        if not (t.get("name") or t.get("brand")):
            continue          # senza nome né marca non possiamo dire di che negozio si tratta
        out.append({"osm_type": e["type"], "osm_id": e["id"], "name": t.get("name"), "brand": t.get("brand"),
                    "wikidata": t.get("brand:wikidata"), "shop": t.get("shop"),
                    "chain": classify(t.get("brand"), t.get("name")), "lat": lat, "lon": lon,
                    "address": _addr(t), "opening_hours": t.get("opening_hours")})
    return out


def upsert(conn, rows) -> int:
    conn.executemany(
        "INSERT INTO stores(osm_type,osm_id,name,brand,wikidata,chain,shop,lat,lon,address,opening_hours) "
        "VALUES(:osm_type,:osm_id,:name,:brand,:wikidata,:chain,:shop,:lat,:lon,:address,:opening_hours) "
        "ON CONFLICT(osm_type,osm_id) DO UPDATE SET name=excluded.name,brand=excluded.brand,wikidata=excluded.wikidata,"
        "chain=excluded.chain,shop=excluded.shop,lat=excluded.lat,lon=excluded.lon,address=excluded.address,"
        "opening_hours=excluded.opening_hours", rows)
    return len(rows)


def propagate_wikidata(conn, min_share=0.8, min_members=3) -> int:
    """L'identificativo ufficiale della marca (brand:wikidata) si impara dai dati: se almeno l'80% dei negozi
    con quell'identificativo è già riconosciuto come una catena, gli altri sono di quella catena."""
    groups = defaultdict(list)
    for r in conn.execute("SELECT osm_type,osm_id,chain,wikidata FROM stores WHERE wikidata IS NOT NULL"):
        groups[r["wikidata"]].append((r["osm_type"], r["osm_id"], r["chain"]))
    changed = 0
    for wd, members in groups.items():
        known = Counter(c for _, _, c in members if c)
        if len(members) < min_members or not known:
            continue
        chain, n = known.most_common(1)[0]
        if n / sum(known.values()) >= min_share and n / len(members) >= 0.3:
            for t, i, c in members:
                if c is None:
                    conn.execute("UPDATE stores SET chain=? WHERE osm_type=? AND osm_id=?", (chain, t, i))
                    changed += 1
    return changed


def overpass_query(s, w, n, e, shops=FOOD) -> str:
    return f'[out:json][timeout:180];nwr["shop"~"^({shops})$"]({s},{w},{n},{e});out center tags;'


def tiles(bbox=ITALY, step=2.0):
    s0, w0, n0, e0 = bbox
    s = s0
    while s < n0:
        w = w0
        while w < e0:
            yield (round(s, 3), round(w, 3), round(min(s + step, n0), 3), round(min(w + step, e0), 3))
            w += step
        s += step


def fetch_tile(query, ua, endpoints=OVERPASS, retries=2, pause=8):
    last = "nessun tentativo"
    for _ in range(retries):
        for ep in endpoints:
            try:
                r = requests.post(ep, data={"data": query}, headers={"User-Agent": ua}, timeout=240)
                if r.status_code == 200:
                    return r.json(), None
                last = f"{ep.split('/')[2]} HTTP {r.status_code}"
            except Exception as ex:
                last = f"{ep.split('/')[2]} {type(ex).__name__}"
        time.sleep(pause)
    return None, last


def load_from_overpass(conn, ua, bbox=ITALY, step=2.0, pause=10, log=print) -> dict:
    total, failed = 0, []
    for t in tiles(bbox, step):
        data, err = fetch_tile(overpass_query(*t), ua)
        if data is None:
            failed.append((t, err))
            log(f"tessera {t}: FALLITA ({err})")
        else:
            total += upsert(conn, parse_overpass(data))
            conn.commit()
            log(f"tessera {t}: ok (totale {total})")
        time.sleep(pause)
    learned = propagate_wikidata(conn)
    conn.commit()
    return {"negozi": total, "tessere_fallite": failed, "riconosciuti_dal_wikidata": learned}


def load_from_file(conn, path) -> dict:
    data = json.load(open(path, encoding="utf-8"))
    n = upsert(conn, parse_overpass(data))
    learned = propagate_wikidata(conn)
    conn.commit()
    return {"negozi": n, "riconosciuti_dal_wikidata": learned}


def nearby(conn, lat, lon, radius_km, chains=None, limit=500) -> list:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    sql = "SELECT * FROM stores WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
    args = [lat - dlat, lat + dlat, lon - dlon, lon + dlon]
    if chains is not None:
        if not chains:
            return []
        sql += " AND chain IN (%s)" % ",".join("?" * len(chains))
        args += list(chains)
    out = []
    for r in conn.execute(sql, args):
        d = haversine_m(lat, lon, r["lat"], r["lon"])
        if d <= radius_km * 1000:
            out.append(dict(r, distance_m=round(d)))
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit]


def count_stores(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
    known = conn.execute("SELECT COUNT(*) FROM stores WHERE chain IS NOT NULL").fetchone()[0]
    return {"totale": total, "con_catena_riconosciuta": known}
