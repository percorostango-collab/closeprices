# Render + Turso + GitHub Actions

Architettura: **Render** ospita il servizio (risponde alle scansioni), **Turso** conserva i dati, **GitHub Actions**
fa il lavoro lento (carica i negozi, scopre i cataloghi, verifica i prodotti in coda). Nessun computer tuo acceso.

## 1. Variabili su Render (Environment)
| Nome | Valore |
|---|---|
| `PV_TURSO_URL` | l'indirizzo del database, quello che inizia con `libsql://...turso.io` (va bene così) |
| `PV_TURSO_TOKEN` | un token **del database** (non dell'account): in Turso, scheda del database → *Create token* |
| `PV_CONTACT` | la tua email (viene inviata ai siti che interroghiamo, come chiedono le loro regole) |

Le variabili vanno su **Render** (il servizio) e, come *Secrets*, su **GitHub** (vedi punto 4). Su Turso non si mette nulla.

## 2. Dopo il deploy: apri `/v1/diag`
`https://prezzi-vicini-api.onrender.com/v1/diag` mostra lo stato **senza mai mostrare il token**.
- `"database": "ok"` e un elenco di `tabelle` → tutto a posto.
- `"database": "errore"` → leggi `errore`:
  - *"Turso ha rifiutato il token"* → token sbagliato o scaduto: creane uno nuovo **per il database** e aggiornalo su Render.
  - *"connessione a Turso non riuscita"* → `PV_TURSO_URL` sbagliato (controlla `turso_host` nella stessa pagina).
  - *"Turso ha risposto HTTP 404"* → l'indirizzo non è quello di un database.
  - *"errore SQL"* → copia il testo e mandamelo.
- `turso_url_impostato` / `turso_token_impostato` a `false` → la variabile non è arrivata al servizio (Render → Environment → *Save* → *Manual Deploy*).

`/v1/health` risponde sempre (non usa il database); `/v1/coverage` e `/v1/scan` ora rispondono **503 con il motivo**
quando il database non risponde, invece di un "Internal Server Error" muto.

## 3. Cosa è stato corretto rispetto al pacchetto che mi hai mandato
1. La libreria `libsql` restituisce le righe come tuple, mentre il servizio le legge per nome (`riga["catena"]`):
   ogni query avrebbe dato errore anche con la connessione giusta. Ora il servizio parla con Turso via HTTPS con `requests`
   (nessuna libreria nativa, nessun WebSocket), e le righe si leggono per nome come con SQLite.
2. Lo schema delle tabelle veniva ricreato a ogni richiesta (10 comandi di rete a scansione): ora una volta per avvio.
3. **`server/cli.py` apriva il database senza le impostazioni** (riga 46): la manutenzione su GitHub avrebbe scritto su un
   file locale del computer di GitHub, perso a fine corsa, senza alcun errore e senza mai arrivare su Turso. Corretto, e
   un test controlla che i dati finiscano nel database giusto.

## 4. GitHub Actions
Nel repository: *Settings → Secrets and variables → Actions → New repository secret*, tre volte:
`PV_TURSO_URL`, `PV_TURSO_TOKEN`, `PV_CONTACT` (stessi valori di Render).
Poi **una volta a mano**: *Actions → Manutenzione Prezzi Vicini → Run workflow*. Fa tre cose di seguito
(verifica prodotti in coda, scoperta dei cataloghi, caricamento dei negozi da OpenStreetMap) e può durare un'ora.
Da lì in poi gira da solo: ogni ora la coda dei prodotti, ogni giorno la scoperta dei cataloghi, il primo del mese i negozi.

## 5. Limiti dei piani gratuiti
- **Render gratuito** si addormenta dopo un periodo di inattività: la prima scansione dopo la pausa può richiedere circa
  un minuto (l'app lo spiega e aspetta fino a 100 secondi).
- **Turso gratuito**: le fonti consultate il 24/11/2026 indicano circa 500 milioni di righe lette e 10 milioni scritte al
  mese e 5 GB (qualcuna parla di 9 GB): controlla i numeri sul tuo account. Questo servizio ne usa una frazione minima.
  Superata la quota, le richieste vengono rifiutate: lo vedresti in `/v1/diag`.
- **GitHub Actions**: le esecuzioni programmate non sono puntuali al minuto; nei repository pubblici di norma vengono
  sospese dopo molti giorni senza attività nel repository: se succede, riattivale dalla scheda Actions.
- **Indirizzi dei server**: 19 dei 63 siti di catene respingono i server in cloud (GitHub e, probabilmente, Render).
  È un limite dei siti, non risolvibile da qui.
