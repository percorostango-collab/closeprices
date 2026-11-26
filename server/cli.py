"""Comandi:  python -m server.cli <comando>
  init-db            crea il database
  load-stores        carica i negozi da OpenStreetMap (una volta, poi ogni mese)   [--file overpass.json]
  discover-sites     capisce quali cataloghi sono consultabili (una volta, poi ogni 2 settimane)
  index              verifica in coda i prodotti scansionati
  coverage           mostra cosa copre il servizio
  diag               stato del database e delle impostazioni, senza segreti
  serve              avvia il servizio (con manutenzione automatica in background)"""
import argparse
import json
import threading
import time

from probe.probe import Robots

from . import catalogs, products, stores
from .config import Settings
from .db import connect


def maintenance(settings, fetcher, robots, stop=None):
    """Ogni minuto svuota la coda di verifica; ogni giorno riprova i siti il cui profilo è vecchio."""
    last_discover = 0
    while not (stop and stop.is_set()):
        try:
            conn = connect(settings.db_path, settings)
            lookup = lambda g: products.lookup(conn, g, settings, fetcher)  # noqa: E731
            catalogs.process_queue(conn, settings, fetcher, robots, lookup, limit=5, budget_s=60)
            if time.time() - last_discover > 86400:
                catalogs.discover_all(conn, fetcher, robots, only_stale_days=14, log=lambda *_: None)
                last_discover = time.time()
            conn.close()
        except Exception as e:  # il servizio non si ferma per un errore di manutenzione
            print("manutenzione:", type(e).__name__, e)
        time.sleep(60)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init-db", "load-stores", "discover-sites", "index", "coverage", "diag", "serve"])
    ap.add_argument("--file")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--bbox", help='load-stores: solo queste aree, "sud,ovest,nord,est" (piu\' aree separate da ";")')
    ap.add_argument("--step", type=float, default=2.0, help="load-stores: lato delle tessere in gradi (piu piccolo = richieste piu leggere)")
    a = ap.parse_args(argv)
    s = Settings()
    if a.cmd == "diag":
        from .diag import diagnose
        print(json.dumps(diagnose(s), ensure_ascii=False, indent=1))
        return
    conn = connect(s.db_path, s)
    fetcher = products.make_fetcher(s)
    robots = Robots(fetcher)
    if a.cmd == "init-db":
        print("database pronto:", s.db_path)
    elif a.cmd == "load-stores":
        if a.file:
            out = stores.load_from_file(conn, a.file)
        elif a.bbox:
            out = {"aree": []}
            for part in a.bbox.split(";"):
                box = tuple(float(x) for x in part.split(","))
                if len(box) != 4:
                    raise SystemExit(f"--bbox non valido: {part!r} (servono 4 numeri: sud,ovest,nord,est)")
                out["aree"].append({"bbox": box, **stores.load_from_overpass(conn, s.user_agent, bbox=box, step=a.step)})
        else:
            out = stores.load_from_overpass(conn, s.user_agent, step=a.step)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    elif a.cmd == "discover-sites":
        print(catalogs.discover_all(conn, fetcher, robots))
    elif a.cmd == "index":
        lookup = lambda g: products.lookup(conn, g, s, fetcher)  # noqa: E731
        print("prodotti verificati:", catalogs.process_queue(conn, s, fetcher, robots, lookup, limit=a.limit))
    elif a.cmd == "coverage":
        print(json.dumps({"cataloghi": catalogs.coverage(conn), "negozi": stores.count_stores(conn)},
                         ensure_ascii=False, indent=1))
    elif a.cmd == "serve":
        import uvicorn
        from .app import create_app
        conn.close()
        threading.Thread(target=maintenance, args=(s, fetcher, robots), daemon=True).start()
        uvicorn.run(create_app(s, fetcher), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
