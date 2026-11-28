"""Tutti i messaggi sui limiti, in un posto solo. L'app li mostra così come sono: niente è nascosto."""

LEVEL_LABELS = {
    1: "Verificato: il codice a barre è nei dati della scheda del catalogo",
    2: "Verificato: il codice a barre compare nella scheda del catalogo",
    3: "Probabile: prodotto a marchio proprio della catena (dal prefisso del codice)",
    5: "Possibile corrispondenza: titolo simile, NON verificata col codice a barre",
}

PRICE_STORE = ("Il prezzo sullo scaffale dei singoli negozi non è un dato pubblico: non lo mostriamo e non lo stimiamo. "
               "Il prezzo di un catalogo è quello del sito online e può essere diverso nel negozio fisico.")
AVAILABILITY = ("Un catalogo che contiene il prodotto non garantisce che il negozio vicino lo abbia in magazzino: "
                "gli assortimenti cambiano da negozio a negozio.")


def build_limits(*, product_state, has_catalogs, indexing, stores_total, position_used, source_error=None,
                 pending=False, chains_total=0, offers_state="non_configurato", offers_error=None, offers_count=0,
                 offers_by_name=0, offers_usage=0, offers_limit=0, name_matches=0):
    L = []

    def add(code, severity, text):
        L.append({"code": code, "severity": severity, "text": text})

    if product_state == "non_riconosciuto":
        add("PRODUCT_NOT_RECOGNIZED", "warning",
            "Prodotto non riconosciuto: questo codice non è in Open Food Facts e nessuna correzione è stata confermata. "
            "Non mostriamo ipotesi sul nome. Puoi proporre tu nome e marca: servono 3 utenti diversi concordi per applicarli.")
    elif product_state == "errore_fonte":
        add("SOURCE_DOWN", "warning",
            f"Open Food Facts non ha risposto ({source_error}). Non possiamo dire se il prodotto sia noto: riprova più tardi.")
    if not has_catalogs:
        add("NO_CATALOG_CONFIRMATION", "warning",
            "Nessun catalogo online ha confermato questo prodotto con il codice a barre. "
            "Non significa che non sia in vendita: significa che non abbiamo una prova.")
    if indexing["state"] == "non_disponibile":
        add("NO_CATALOGS_QUERYABLE", "warning",
            "Al momento nessun catalogo è consultabile in automatico da questo servizio.")
    else:
        add("COVERAGE", "info",
            f"Cataloghi consultabili in automatico: {indexing['chains_consultable']} su {chains_total}. "
            "Le altre bloccano gli accessi automatici, mostrano i prodotti solo con JavaScript o non indicano il "
            "codice a barre: per quelle non possiamo dire nulla.")
    if pending or indexing["state"] == "parziale":
        add("INDEX_PARTIAL", "info",
            "La verifica sui cataloghi non è finita: alcuni risultati potrebbero comparire alla prossima scansione.")
    if not position_used:
        add("NO_POSITION", "warning", "Posizione non indicata: non possiamo mostrare i negozi vicini.")
    elif stores_total == 0:
        add("STORES_EMPTY", "warning",
            "Nessun punto vendita nei dati di questa zona (o i negozi non sono ancora stati caricati).")
    if offers_state == "non_configurato":
        add("OFFERS_NOT_CONFIGURED", "warning",
            "I prezzi online di riferimento non sono attivi: manca la chiave del servizio di ricerca (PV_SERPAPI_KEY).")
    elif offers_state == "quota_esaurita":
        add("OFFERS_QUOTA", "warning",
            f"La quota gratuita mensile di ricerche prezzi è esaurita ({offers_usage}/{offers_limit}): "
            "mostriamo solo i prezzi già salvati.")
    elif offers_state == "errore":
        add("OFFERS_ERROR", "warning", f"Ricerca dei prezzi online non riuscita: {offers_error}.")
    elif offers_count == 0:
        add("OFFERS_NONE", "info", "Nessun prezzo online trovato per questo prodotto.")
    else:
        extra = (f" {offers_by_name} su {offers_count} sono state trovate per somiglianza di nome: controlla che sia lo stesso "
                 "prodotto." if offers_by_name else "")
        add("OFFERS_INFO", "info",
            "I prezzi online sono riferimenti trovati su Google Shopping: spedizione, disponibilità e condizioni "
            "dipendono dal negozio online." + extra)
    if name_matches:
        add("NAME_MATCH_INFO", "info",
            "Le corrispondenze per nome nei cataloghi non sono verificate col codice a barre: controlla che sia lo stesso prodotto.")
    add("STORE_AVAILABILITY", "info", AVAILABILITY)
    add("PRICE_STORE", "info", PRICE_STORE)
    return L
