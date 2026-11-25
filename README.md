# Prezzi Vicini — versione 2

Scansioni un codice a barre; l'app ti dice **cosa è stato verificato** su quel prodotto e **dove non sappiamo nulla**.
Leggi prima `docs/LIMITI.md`: dice con chiarezza cosa l'app non fa (per esempio, non mostra il prezzo sullo scaffale
dei negozi) e quanti cataloghi riesce davvero a consultare.

## Com'è fatta
- **Servizio** (`server/`): una sola richiesta per scansione (`GET /v1/scan`), risposta dal database in meno di un secondo.
  Negozi da OpenStreetMap caricati una volta; identità del prodotto da Open Food Facts con correzioni condivise;
  indice dei cataloghi che registra **solo** ciò che il codice a barre nella scheda conferma.
- **App** (`app/`): scanner e posizione come prima, poi una sola chiamata al servizio e una schermata che separa
  *verificato*, *probabile*, *nessuna informazione* e **"Cosa non sappiamo"**.
- **Sonda** (`probe/`): la misura sui cataloghi reali (gira su GitHub Actions, vedi `prezzi-vicini-probe`).

## Stato della verifica (onesto)
| Parte | Come è stata verificata |
|---|---|
| Servizio e logica (`server/`, `pvcore/`) | 171 test automatici contro siti finti in locale; gli scenari del servizio girano su SQLite e su un finto Turso con lo stesso protocollo HTTP; i test sanno fallire (controllati rompendo il codice di proposito) |
| Formato dati servizio ↔ app | l'app (parte Dart pura) legge esempi generati dal servizio vero; il controllo fallisce se un campo cambia |
| Modelli, client e testi dell'app | analizzati e provati con il compilatore Dart |
| Schermate Flutter (`app/lib/screens`) | **non compilate né provate su telefono**: solo controllo di sintassi. È il primo punto da provare |
| Servizio contro i siti reali | **non provato da qui** (rete chiusa): la copertura reale si vede con `coverage` dopo `discover-sites` |

## Avvio rapido
1. Servizio: `docs/RENDER_TURSO.md` (Render + Turso + GitHub Actions, senza computer acceso) oppure `docs/DEPLOY.md` (Docker).
2. App: in `app/` esegui `setup.bat` (Windows) o `setup.sh`, poi configura i permessi (`app/ANDROID_IOS.md`),
   poi `flutter run`. Al primo avvio scrivi l'indirizzo del servizio nelle Impostazioni.

## Test
```
pip install -r requirements.txt
python -m pytest -q                                   # servizio e logica
cd app && dart run tool/contract_check.dart ../tests/fixtures/api    # formato dati con l'app (serve Dart)
python tools/dump_contract.py                         # rigenera gli esempi se cambi il formato
```

## Cartelle
`server/` servizio · `pvcore/` logica senza rete (codici a barre, prove, GS1) · `probe/` sonda e client web ·
`data/` registro dei 70 cataloghi, prefissi GS1 · `app/` Flutter · `tests/` · `docs/`
