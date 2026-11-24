# Mettere in funzione il servizio

Il servizio è un programma Python con un database SQLite. Serve un computer sempre acceso e raggiungibile dal
telefono (un piccolo server a noleggio, o un computer di casa con un indirizzo pubblico). **Costi e requisiti dipendono
dal fornitore: verificali sul suo sito prima di scegliere.** L'app parla con il servizio via internet: in produzione
usa HTTPS.

## Con Docker (consigliato)
1. Copia `.env.example` in `.env` e scrivi la tua email in `PV_CONTACT`.
2. `docker compose up -d --build`
3. Una sola volta, per caricare i dati (il database sta nella cartella `var/`):
   - `docker compose run --rm prezzivicini python -m server.cli load-stores`  (negozi da OpenStreetMap, 20-40 minuti)
   - `docker compose run --rm prezzivicini python -m server.cli discover-sites` (capisce quali cataloghi sono consultabili, circa 10 minuti)
4. Controlla: `curl http://localhost:8000/v1/coverage` e `curl "http://localhost:8000/v1/scan?code=8008490000021&lat=41.9&lon=12.49"`

## Senza Docker
```
pip install -r requirements-server.txt
export PV_CONTACT=tua-email@esempio.it      # su Windows: set PV_CONTACT=...
python -m server.cli init-db
python -m server.cli load-stores
python -m server.cli discover-sites
python -m server.cli serve
```

## Cosa fa da solo
Mentre è acceso, ogni minuto verifica in coda i prodotti scansionati che non hanno fatto in tempo, e ogni giorno
riprova i siti il cui profilo ha più di 14 giorni. I negozi vanno ricaricati ogni mese: `load-stores`.

## Limiti tecnici da conoscere
- Nessuna autenticazione: chiunque conosca l'indirizzo può interrogare il servizio. Per un uso personale va bene;
  per un uso pubblico va aggiunta una chiave e un limite di richieste.
- Un solo processo con SQLite: adatto a poche migliaia di scansioni al giorno, non a un grande pubblico.
- La prima scansione di un prodotto nuovo interroga i cataloghi consultabili (fino a 8 secondi), le successive no.
- Se `PV_CONTACT` non è impostato i siti esterni potrebbero rifiutare le richieste.
