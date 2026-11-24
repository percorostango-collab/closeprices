"""Tutti i messaggi sui limiti, in un posto solo. L'app li mostra così come sono: niente è nascosto."""

LEVEL_LABELS = {
    1: "Verificato: il codice a barre è nei dati della scheda del catalogo",
    2: "Verificato: il codice a barre compare nella scheda del catalogo",
    3: "Probabile: prodotto a marchio proprio della catena (dal prefisso del codice)",
}

PRICE_STORE = ("Il prezzo sullo scaffale dei singoli negozi non è un dato pubblico: non lo mostriamo e non lo stimiamo. "
               "Il prezzo di un catalogo è quello del sito online e può essere diverso nel negozio fisico.")
AVAILABILITY = ("Un catalogo che contiene il prodotto non garantisce che il negozio vicino lo abbia in magazzino: "
                "gli assortimenti cambiano da negozio a negozio.")


def build_limits(*, product_state, has_catalogs, indexing, stores_total, position_used, source_error=None,
                 pending=False, chains_total=0):
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
            f"Cataloghi consultabili in automatico: {indexing['chains_consultable']} su {chains_total} catene. "
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
    add("STORE_AVAILABILITY", "info", AVAILABILITY)
    add("PRICE_STORE", "info", PRICE_STORE)
    return L
