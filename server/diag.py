"""Diagnosi del servizio in chiaro, senza mai mostrare segreti. Usata da /v1/diag e da `cli diag`."""
import re
import sys
from urllib.parse import urlparse

from .db import clean_token, connect


def token_shape(tok: str):
    """Com'è fatto il token, senza rivelarlo: solo lunghezze e tipi di caratteri. Un token Turso valido è un JWT:
    tre parti separate da punti, la prima inizia con 'eyJ', lungo in tutto parecchie centinaia di caratteri."""
    if not tok:
        return None
    parts = tok.split(".")
    return {"lunghezza_totale": len(tok), "lunghezze_delle_parti": [len(p) for p in parts],
            "inizia_con_eyJ": tok.startswith("eyJ"),
            "contiene_spazi_o_virgolette": bool(re.search(r"[\s\"'`]", tok)),
            "solo_caratteri_validi": all(re.fullmatch(r"[A-Za-z0-9_-]*", p) for p in parts)}


def diagnose(settings) -> dict:
    host = urlparse(settings.turso_url.replace("libsql://", "https://")).hostname if settings.turso_url else None
    info = {"python": sys.version.split()[0], "database_modo": "turso" if settings.use_turso else "sqlite-locale",
            "turso_url_impostato": bool(settings.turso_url), "turso_token_impostato": bool(settings.turso_token),
            "turso_host": host, "turso_token_forma": token_shape(settings.turso_token),
            "turso_token_dopo_pulizia": token_shape(clean_token(settings.turso_token)),
            "caratteri_tolti_dalla_pulizia": len(settings.turso_token or "") - len(clean_token(settings.turso_token)), "contatto_impostato": settings.contact != "contatto-non-configurato",
            "budget_verifica_s": settings.index_budget_s,
            "serpapi_key_impostata": bool(settings.serpapi_key),
            "omniroute_configurato": settings.omni_enabled, "omniroute_host": (urlparse(settings.omni_url).hostname if settings.omni_url else None),
            "llm_modello": settings.llm_model or None, "limite_mensile_ricerche_prezzi": settings.shopping_monthly_limit}
    try:
        conn = connect(settings.db_path, settings)
        try:
            conn.execute("SELECT 1").fetchone()
            info["database"] = "ok"
            info["tabelle"] = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            info["conteggi"] = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                for t in ("stores", "site_profiles", "products", "evidence", "index_queue")
                                if t in info["tabelle"]}
        finally:
            conn.close()
    except Exception as e:
        msg = str(e)
        for secret in (settings.turso_token,):
            if secret:
                msg = msg.replace(secret, "***")
        info["database"] = "errore"
        info["errore"] = f"{type(e).__name__}: {msg}"[:500]
    return info


def diagnose_omniroute(settings) -> dict:
    """Prova dal vivo (ricerca, lettura, chat) e dice com'è fatta ogni risposta: chiavi e conteggi, mai i contenuti."""
    from .omniroute import OmniRoute, parse_fetch, parse_search
    if not settings.omni_enabled:
        return {"configurato": False, "come": "imposta PV_OMNIROUTE_URL e PV_OMNIROUTE_KEY (e PV_LLM_MODEL per la chat)"}
    o = OmniRoute(settings)
    out = {"configurato": True, "host": urlparse(settings.omni_url).hostname, "modello": settings.llm_model or None}
    status, j, err = o._post("/v1/search", {"query": "De Cecco mezzi rigatoni n.26 500 g prezzo", "max_results": 3, "country": "IT"})
    out["ricerca"] = {"http": status, "errore": err, "chiavi_risposta": list(j.keys())[:10] if isinstance(j, dict) else type(j).__name__,
                      "risultati_letti": len(parse_search(j)) if err is None else 0}
    status, j, err = o._post("/v1/web/fetch", {"url": "https://example.com", "format": "markdown"}, timeout=45)
    out["lettura_pagina"] = {"http": status, "errore": err, "chiavi_risposta": list(j.keys())[:10] if isinstance(j, dict) else type(j).__name__,
                             "testo_letto": bool(parse_fetch(j)) if err is None else False}
    ans, err = o.chat_json("Rispondi solo con JSON.", 'Rispondi con {"ok": true}', max_tokens=30)
    out["chat"] = {"errore": err, "json_valido": ans is not None}
    return out
