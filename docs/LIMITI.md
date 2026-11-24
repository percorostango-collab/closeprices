# Cosa sa fare Prezzi Vicini — e cosa no

Questo documento dice le cose come stanno. L'app mostra gli stessi limiti nella schermata di ogni prodotto,
sotto il titolo "Cosa non sappiamo".

## In una frase
Scansioni un codice a barre e l'app ti dice **cosa è stato verificato** su quel prodotto: quale catalogo online lo
contiene (provato dal codice a barre nella scheda), quali negozi vicini appartengono a quelle catene. Dove non ha una
prova, lo scrive: **"non trovato" è una risposta normale, e in molti casi sarà quella che vedrai.**

## Cosa NON fa
1. **Non mostra il prezzo sullo scaffale di un negozio.** Non è un dato pubblico e non lo stimiamo. Il prezzo che a volte
   compare è quello del *catalogo online* della catena, e l'app lo dice ("prezzo del sito online").
2. **Non sa se il negozio vicino ha il prodotto.** Sa solo che il catalogo della catena lo contiene.
   Gli assortimenti cambiano da negozio a negozio, soprattutto nelle catene a franchising.
3. **Non copre tutte le catene.** Misura del 24/11/2026 su 63 siti di catene (sonda in `prezzi-vicini-probe/results`):
   - il codice a barre risulta nella scheda (con prezzo) solo per pochissime catene: Prezzemolo & Vitale, e solo in
     parte Lidl e Carrefour; cercando per codice è stato confermato anche su Todis a Casa;
   - circa 19 siti respingono gli accessi automatici da server esterni;
   - 6 mostrano i prodotti solo con JavaScript;
   - per Esselunga e Pam le schede esistono ma non riportano né codice né prezzo nel testo della pagina;
   - per le altre catene la misura non è stata decisiva.
   Dove il catalogo non è consultabile, l'app non dice nulla su quella catena: non la nasconde, la conta come "non consultabile".
4. **Non riconosce i prodotti che non sono in Open Food Facts.** Li chiama "non riconosciuti" e non propone nomi ipotetici.
   Puoi proporre nome e marca: valgono per tutti solo quando 3 utenti diversi concordano.
5. **I negozi arrivano da OpenStreetMap**, caricati una volta. Per impostazione predefinita sono supermercati e alimentari.
   A Roma e Napoli circa metà dei negozi ha l'identificativo ufficiale della marca; gli altri si riconoscono dal nome e
   quelli che non si riconoscono compaiono tra "altri negozi, nessuna informazione".
   Elettronica, casa e bellezza non sono caricate di default.
6. **I dati invecchiano.** Una conferma di catalogo vale 30 giorni, poi viene rifatta alla scansione successiva.

## Come leggere la fiducia
| Etichetta | Significa | Si mostra |
|---|---|---|
| Verificato (dati strutturati) | il codice a barre è dichiarato nei dati della scheda del catalogo | sempre |
| Verificato (testo della scheda) | il codice compare nella pagina di UN solo prodotto | sempre |
| Probabile | marchio proprio della catena, dal prefisso del codice (oggi solo Eurospin) | con l'etichetta "Probabile" |
| Nessuna informazione | negozio vicino di una catena su cui non sappiamo nulla | in una sezione chiusa |

Una pagina che elenca più prodotti, o che cita il codice in un riquadro "altri prodotti", **non** vale come prova.
Un nome simile **non** vale come prova.

## Come migliorare la copertura (in ordine di costo)
1. Aggiungere connettori mirati per le catene che espongono un'API o una ricerca per codice (servono misure per catena).
2. Un browser automatico per i siti con JavaScript: fragile e al limite dei termini d'uso di molti siti.
3. Dati a pagamento di un fornitore: l'unico modo di avere prezzi di negozio affidabili.
