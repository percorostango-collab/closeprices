# Prezzi Vicini — test e sonda

Due cose in un repository:

1. **Test offline** (`tests/`): la logica che decide se un prodotto è proprio quello, con siti finti in locale. 81 test + 4 limiti noti.
   Girano da soli su GitHub a ogni caricamento (scheda *Actions* → "Test").
2. **Sonda sui cataloghi reali** (`probe/`): misura, senza SerpApi, quanti cataloghi del registro permettono
   di trovare la scheda di un prodotto e di **confermarne il codice a barre**. Scrive l'esito in
   `results/summary.md`. Gira da sola al primo caricamento e poi ogni lunedì.

## Cosa fare (una volta, senza eseguire nulla)

1. Su github.com crea un repository **pubblico** (es. `prezzi-vicini-probe`). Pubblico serve perché Claude possa leggere l'esito.
2. Decomprimi lo zip e, da *Add file → Upload files*, **trascina il contenuto** della cartella
   (compresa `.github`, che Windows mostra e macOS nasconde: su Mac premi Cmd+Maiusc+.). Poi *Commit changes*.
3. Scrivi a Claude il nome del repository. Fine.

Se nella scheda *Actions* non compare nulla, la cartella `.github` non è stata caricata: ricaricala.

## Come leggere l'esito (`results/summary.md`)
La sezione **"misura decisiva"** dice, catena per catena, se le schede prodotto (prese dalla sitemap, senza cercare nulla)
espongono un **codice a barre valido** e un **prezzo**. Esiti: `codice_e_prezzo` (ottimo), `solo_codice`, `solo_prezzo`,
`ne_codice_ne_prezzo`, `schede_bloccate`, `nessuna_scheda_in_sitemap`, `sitemap_non_leggibile`.
`bloccato_waf_o_robots_illeggibile` = il firewall del sito respinge i server di GitHub (non è un divieto scritto).
Il campione di prodotti è automatico: italiani (prefisso GS1 800-839) più scansionati su Open Food Facts.

## Come si comporta la sonda con i siti
- Si identifica (User-Agent con il nome del repository) e rispetta `robots.txt`: se vieta la ricerca, non la fa.
- Al massimo 1 richiesta ogni 1,5 s per sito; circa 10 richieste per sito a settimana.
- Nessun login, nessun aggiramento dei blocchi: se un sito blocca, lo scrive nell'esito e basta.
- Non scarica cataloghi: una ricerca per prodotto e al massimo una scheda.

## Cosa NON prova
- Le fixture in `tests/fixtures/pages/` sono **sintetiche**: provano la logica, non la copertura dei siti.
- La sonda non esegue JavaScript: i siti che mostrano i prodotti solo via JavaScript risulteranno
  "js_senza_form_ricerca". Sono un dato utile (servirebbe un connettore dedicato), non un errore.
- Gli indirizzi dei server GitHub possono essere bloccati da alcuni siti: comparirà come "bloccato".

## Contenuto
- `pvcore/` — logica senza rete: codici a barre, controllo della pagina, scala di fiducia, GS1, correzioni, identità per testo, registro.
- `probe/` — la sonda. `data/` — registro (70 voci), prefissi GS1, set di prodotti (`golden.json`).
- `tools/gen_registry.py` — rigenera il registro da `catalog_sources.dart`.

## Aggiungere un caso reale
In `data/golden.json` aggiungi il prodotto con il codice verificato (marca, nome, formato). Il test lo controlla
(cifra di controllo, formato leggibile) e, con `"probe": true`, la sonda lo cerca nei cataloghi.
