"""Client di OmniRoute (gateway compatibile con l'API OpenAI): ricerca web, lettura di pagine e chat.

OmniRoute espone, tra l'altro:  POST /v1/search   POST /v1/web/fetch   POST /v1/chat/completions
Le risposte di ricerca e lettura "mantengono lo schema nativo del provider": per questo il lettore è tollerante
(accetta più forme) e, se non riconosce nulla, lo dice con le chiavi trovate: così si corregge in un minuto.

Regola di sicurezza: ciò che arriva da qui è una PROPOSTA. Nessun indirizzo, prezzo o giudizio entra nell'indice
senza essere stato verificato dal nostro codice sul testo della pagina."""
import json
import re

import requests


def _clean(text, key):
    if key:
        text = str(text).replace(key, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1***", str(text))


def _first(d, *names):
    for n in names:
        v = d.get(n)
        if v:
            return v
    return None


def parse_search(j):
    """Accetta le forme più comuni: {'results':[...]}, {'data':[...]}, {'organic':[...]}, {'web':{'results':[...]}}, lista."""
    items = None
    if isinstance(j, list):
        items = j
    elif isinstance(j, dict):
        for k in ("results", "data", "organic", "items", "organic_results", "web"):
            v = j.get(k)
            if isinstance(v, dict):
                v = v.get("results") or v.get("items")
            if isinstance(v, list):
                items = v
                break
    out = []
    for it in items or []:
        if isinstance(it, dict):
            url = _first(it, "url", "link", "href")
            if isinstance(url, str) and url.startswith("http"):
                out.append({"url": url, "title": str(_first(it, "title", "name") or "")[:200],
                            "snippet": str(_first(it, "content", "snippet", "description", "text") or "")[:400]})
    return out


def parse_fetch(j):
    if isinstance(j, str):
        return j
    if isinstance(j, dict):
        for k in ("content", "markdown", "text", "html", "raw_content"):
            if isinstance(j.get(k), str) and j[k].strip():
                return j[k]
        for k in ("data", "result", "results"):
            v = j.get(k)
            if isinstance(v, (dict, list, str)):
                if isinstance(v, list) and v:
                    v = v[0]
                r = parse_fetch(v)
                if r:
                    return r
    return None


def extract_json(text):
    """Il primo oggetto JSON contenuto in un testo (i modelli a volte aggiungono parole o ```)."""
    if not text:
        return None
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


class OmniRoute:
    def __init__(self, settings, session=None):
        base = settings.omni_url.rstrip("/")
        self.base = re.sub(r"/v1$", "", base)
        self.key, self.model = settings.omni_key, settings.llm_model
        self.search_provider, self.fetch_provider = settings.search_provider, settings.fetch_provider
        self.s = session or requests.Session()
        self.calls = {"search": 0, "fetch": 0, "chat": 0}

    def _post(self, path, payload, timeout=40):
        try:
            r = self.s.post(f"{self.base}{path}", json=payload, timeout=timeout,
                            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        except requests.RequestException as e:
            return None, None, _clean(f"{type(e).__name__}: {e}", self.key)[:200]
        try:
            j = r.json()
        except ValueError:
            j = None
        if r.status_code != 200:
            detail = ""
            if isinstance(j, dict):
                e = j.get("error")
                detail = (e.get("message") if isinstance(e, dict) else e) or ""
            return r.status_code, j, _clean(f"HTTP {r.status_code} {detail}", self.key)[:200]
        return r.status_code, j, None

    def search(self, query, max_results=8, country="IT"):
        """-> (lista di {url,title,snippet}, errore)"""
        self.calls["search"] += 1
        payload = {"query": query, "max_results": max_results, "country": country}
        if self.search_provider:
            payload["provider"] = self.search_provider
        _, j, err = self._post("/v1/search", payload)
        if err:
            return [], err
        res = parse_search(j)
        if not res and j is not None:
            keys = list(j.keys())[:8] if isinstance(j, dict) else type(j).__name__
            return [], f"risposta di ricerca non riconosciuta (chiavi: {keys})"
        return res, None

    def fetch_text(self, url):
        """Legge una pagina tramite i provider di OmniRoute (utile quando i nostri server sono bloccati)."""
        self.calls["fetch"] += 1
        payload = {"url": url, "format": "markdown"}
        if self.fetch_provider:
            payload["provider"] = self.fetch_provider
        _, j, err = self._post("/v1/web/fetch", payload, timeout=45)
        return (parse_fetch(j), None) if not err else (None, err)

    def chat_json(self, system, user, max_tokens=500):
        """-> (dizionario JSON o None, errore)"""
        if not self.model:
            return None, "modello non configurato (PV_LLM_MODEL)"
        self.calls["chat"] += 1
        _, j, err = self._post("/v1/chat/completions", {
            "model": self.model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout=60)
        if err:
            return None, err
        try:
            content = j["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None, "risposta della chat non riconosciuta"
        obj = extract_json(content if isinstance(content, str) else json.dumps(content))
        return (obj, None) if obj is not None else (None, "la risposta non contiene JSON")
