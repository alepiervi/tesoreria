# Tesoreria di gruppo

Programma di gestione finanziaria per un gruppo di aziende: conti bancari, fatture elettroniche,
riconciliazione, scadenzario, previsione di cassa, pagamenti e accesso controllato per il commercialista.

- **Backend**: Python + FastAPI, database MongoDB (cartella `backend/`)
- **Frontend**: React + Tailwind CSS (cartella `frontend/`)
- Stessa struttura usata da Emergent: tutte le rotte del backend iniziano con `/api`,
  il frontend legge l'indirizzo del backend da `REACT_APP_BACKEND_URL`.

> **Stato attuale:** tutte le funzioni sono complete e funzionanti. I conti si possono già usare con
> **dati veri** importando gli estratti conto dall'home banking (conti manuali). Il collegamento automatico
> alle banche, lo SDI e i pagamenti sono ancora **simulati** ("modalità demo") finché non si attiva un provider
> (vedi "Collegare i servizi reali").

---

## Cosa fa

| Area | Funzioni |
|---|---|
| **Multi-azienda** | Più aziende, vista di gruppo consolidata, ogni utente vede solo le aziende assegnate |
| **Ruoli** | Titolare, Amministrazione, Commercialista, Sola lettura, assegnati azienda per azienda |
| **Accesso** | Login, verifica in due passaggi (app di autenticazione), blocco dopo 5 tentativi falliti, uscita da tutti i dispositivi |
| **Inviti** | Link di invito valido 7 giorni, revoca degli accessi, disattivazione utente |
| **Conti bancari** | Conti manuali con import dell'estratto conto (PDF, CSV, Excel, CAMT.053, CBI) senza doppioni; carte di credito con import dell'estratto carta e addebito sul conto riconosciuto come giroconto; collegamento automatico (open banking) con avviso di scadenza del consenso; un conto manuale si può rendere automatico mantenendo i movimenti |
| **Movimenti** | Elenco con filtri, categorie automatiche modificabili, note |
| **Fatture** | Import XML FatturaPA (anche più file insieme), scarico da SDI, inserimento manuale, download XML |
| **Riconciliazione** | Proposte automatiche con grado di affidabilità (importo, numero fattura, controparte, data), un bonifico per più fatture, abbinamento manuale, movimenti senza fattura, conferma in blocco delle proposte sicure, annullamento |
| **Scadenzario** | Scadenze create in automatico dalle fatture, F24 e scadenze manuali, spese ricorrenti (stipendi, affitto, rate) |
| **Pagamenti** | L'amministrazione prepara, il titolare autorizza; scelta del conto di addebito |
| **Previsione di cassa** | Saldo settimana per settimana fino a 6 mesi, avviso se scende troppo o va in negativo |
| **Commercialista** | Chiarimenti su movimenti (domanda/risposta), archivio documenti (F24, bilanci…), export Excel/CSV/XML |
| **Registro attività** | Chi ha fatto cosa: accessi, pagamenti, export, modifiche ai permessi |
| **Tra le aziende (intercompany)** | Riconosce bonifici tra aziende del gruppo e giroconti tra conti, li esclude dai totali consolidati; trasferimenti netti e fatture aperte tra aziende |
| **Crediti e debiti** | Anzianità (non scaduto, 1-30, 31-60, 61-90, oltre 90 giorni), ritardo medio di pagamento per cliente, solleciti email in 3 toni con fattura XML allegata |
| **Notifiche** | Campanella nel programma, email e WhatsApp: pagamenti in scadenza, crediti scaduti, liquidità in calo, consensi bancari, estratti conto da importare, budget superato, domande del commercialista, pagamenti da autorizzare. Riepilogo settimanale il lunedì e report PDF il primo del mese |
| **IVA stimata** | Liquidazione mensile o trimestrale calcolata dalle fatture, con riporto del credito; crea le scadenze F24 che entrano nella previsione |
| **Regole di categoria** | Quando correggi la categoria di un movimento il programma propone una regola che vale per i movimenti futuri |
| **Budget** | Budget mensile per categoria, confronto con il reale e da inizio anno, proposta automatica dalla media degli ultimi 12 mesi |
| **Finanziamenti e fidi** | Mutui, finanziamenti, leasing con piano di rimborso (rate nella previsione); fidi e anticipi con disponibilità residua |
| **Scenari** | "Cosa succede se": un cliente paga in ritardo, sposti o togli un pagamento, arriva una spesa. Confronto con la previsione reale |
| **Report mensile PDF** | Liquidità, entrate/uscite per categoria, budget, crediti e debiti, previsione, finanziamenti |
| **Assistente** | Domande in italiano sui dati ("quanto ha speso Alfa di carburante?"), aiuto nei movimenti senza abbinamento, lettura scontrini |
| **Scontrini** | Foto o PDF dello scontrino, abbinamento al pagamento con carta, archivio per il commercialista |
| **App sul telefono** | Installabile dalla home del telefono (serve HTTPS); i dati non vengono salvati sul dispositivo |
| **Backup** | Copia automatica giornaliera del database e script di ripristino |
| **Contabilità generale** | Partita doppia con piano dei conti a 3 livelli collegato allo schema CEE; registrazioni automatiche da fatture e movimenti riconciliati (si aggiornano da sole se cambia l'origine); prima nota con modelli (stipendi, TFR, fatture da ricevere, imposte, cassa, saldi iniziali) |
| **Libri e registri** | Libro giornale numerato, mastrini con saldo progressivo, partitari clienti e fornitori, registri IVA vendite e acquisti con protocollo e riepilogo per aliquota |
| **Bilancio** | Stato patrimoniale e conto economico CEE con anno precedente, bilancio di verifica, controlli di quadratura (banche, conto transitorio, conti generici), export Excel e PDF |
| **Fiscale** | Ritenute d'acconto (registrazione e scadenza F24 cod. 1040 automatica), split payment, bollo, liquidazioni IVA in contabilità |
| **Fine anno** | Cespiti con piano di ammortamento e registrazione delle quote, ratei e risconti con storno automatico, chiusura e riapertura dei conti, blocco del periodo chiuso |
| **Centri di costo** | Su fatture, cespiti e righe di prima nota, con ricavi, costi e margine per centro |
| **Bilancio consolidato** | Somma dei bilanci delle aziende con eliminazione di crediti, debiti, vendite e acquisti tra loro; segnala le posizioni tra aziende che non coincidono |
| **Liquidità di gruppo** | Saldo oggi e punto più basso previsto per azienda, riserva minima, proposte di trasferimento tra le aziende (il bonifico va poi autorizzato) |
| **Confronto aziende** | Ricavi, MOL, utile, personale, liquidità, debiti e indici fianco a fianco |
| **Salute dell'azienda** | Segnali di allerta del Codice della crisi (art. 3 e 25-novies: stipendi, fornitori, banche, IVA, INPS, INAIL, Riscossione), DSCR a 6 e 12 mesi, 11 indici di bilancio spiegati con semaforo |
| **Piano a 3 anni** | Conto economico, cassa, debiti e DSCR con le tue ipotesi (crescita, costi, investimenti, nuovi finanziamenti, giorni di incasso e pagamento), export Excel |
| **Centrale Rischi** | Prospetto mensile per banca (accordato, utilizzato, sconfinato), andamento, confronto con i fidi inseriti; lettura dal PDF con l'assistente collegato a Claude |
| **Paghe** | Totali mensili del consulente del lavoro (anche letti dal PDF): registrazione degli stipendi, scadenza del netto e F24 del 16; i bonifici chiudono i debiti verso dipendenti, INPS ed Erario |
| **Chiusura del mese** | Lista dei controlli di fine mese con chi deve farli, spunta manuale, blocco del mese e promemoria dal giorno 10 |
| **Fatture da classificare** | Conto suggerito per le fatture di acquisto sul conto generico (dalle scelte del gruppo e dalle parole della fattura), conferma in blocco |
| **Commesse** | Ricavi e costi per lavoro rispetto al preventivo, avviso se i costi superano il previsto |
| **Rimanenze di magazzino** | Valore al 31/12 (totale o articolo per articolo) con storno automatico al 1° gennaio |
| **Export per il gestionale** | Prima nota in CSV o Excel con colonne, separatore, date e codici conto dello studio; anagrafica clienti e fornitori |
| **Provvigioni sulle attivazioni** | Import giornaliero degli avanzamenti di ogni partner (Fastweb, Vodafone, SKY…; Excel/CSV con colonne diverse, mappatura ricordata) e del file del backoffice; abbinamento codice fiscale + account → codice venditore → struttura collegata o dipendente; listino a importo fisso per offerta; gare a soglie; rendiconti mensili con recupero automatico degli storni e riporto dei saldi negativi; pagamento alle strutture nello scadenzario e bonus dei dipendenti in Excel per il consulente; margine per mese |
| **QR code nei solleciti** | Avviso di pagamento PDF con QR code bancario (standard SEPA): il cliente lo inquadra e il bonifico si compila da solo |

### Cosa può fare ogni ruolo

| | Titolare | Amministrazione | Commercialista | Sola lettura |
|---|:-:|:-:|:-:|:-:|
| Vedere conti, movimenti, fatture, scadenze | ✓ | ✓ | ✓ | ✓ |
| Note e richieste di chiarimento | ✓ | ✓ | ✓ | |
| Caricare documenti, esportare | ✓ | ✓ | ✓ | |
| Riconciliare, categorizzare, gestire fatture e scadenze | ✓ | ✓ | | |
| Collegare conti bancari | ✓ | ✓ | | |
| Preparare un pagamento | ✓ | ✓ | | |
| Inviare solleciti, impostare il budget | ✓ | ✓ | | |
| Usare l'assistente | ✓ | ✓ | ✓ | |
| Vedere prima nota, registri e bilancio | ✓ | ✓ | ✓ | ✓ |
| Registrazioni manuali, piano dei conti, cespiti, ratei | ✓ | ✓ | ✓ | |
| Chiudere e riaprire l'esercizio e i mesi | ✓ | | ✓ | |
| Inserire le paghe | ✓ | ✓ | ✓ | |
| Vedere attivazioni e provvigioni | ✓ | ✓ | ✓ | |
| Importare avanzamenti, listino, approvare provvigioni | ✓ | ✓ | | |
| Salute dell'azienda, piano, consolidato (vedere) | ✓ | ✓ | ✓ | ✓ |
| **Autorizzare un pagamento** (con verifica in due passaggi) | ✓ | | | |
| Gestire utenti, vedere il registro attività | ✓ | | | |

I permessi sono tutti nel file `backend/app/permissions.py`: per cambiarli basta modificare quell'elenco.

---

## Provarlo sul tuo computer

**Il modo più semplice:** installa [Python](https://www.python.org/downloads/) (su Windows spunta «Add python.exe to PATH»)
e [Node.js](https://nodejs.org/) versione LTS, poi fai doppio clic su **`avvia-demo.bat`** (Windows) oppure lancia
**`./avvia-demo.sh`** (Mac/Linux). Si apre il browser su http://localhost:3000 con le 3 aziende di prova: accedi con
`titolare@demo.it` / `Demo2026demo`. I dati sono in memoria e ripartono da capo a ogni avvio.

Se preferisci farlo a mano:

Servono **Python 3.11+**, **Node.js 18+** e, per i dati veri, **MongoDB**.

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # poi apri .env e imposta JWT_SECRET
uvicorn server:app --reload --port 8001
```

Per una prova veloce **senza installare MongoDB**, nel file `.env` metti `MONGO_URL=mock://`:
il database resta in memoria e si azzera a ogni riavvio (solo per provare, mai con dati veri).

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm start
```

Si apre su http://localhost:3000.

### Utenti di prova

Al primo avvio, con `SEED_DEMO=true`, vengono create 3 aziende di esempio e questi utenti
(password per tutti: `Demo2026demo`):

| Email | Ruolo | Aziende |
|---|---|---|
| titolare@demo.it | Titolare | Alfa, Beta, Gamma |
| amministrazione@demo.it | Amministrazione | Alfa, Beta, Gamma |
| commercialista@demo.it | Commercialista | Alfa, Beta |

**Quando passi ai dati veri:** imposta `SEED_DEMO=false` nel backend e `REACT_APP_SHOW_DEMO_LOGIN=false`
nel frontend, poi crea il tuo utente titolare (vedi "Primo avvio con dati veri").

### Test automatici

```bash
cd backend
pytest
```

102 test controllano permessi, inviti, riconciliazione, fatture XML e .p7m, estratti conto, intercompany, crediti e solleciti, notifiche, IVA, budget, finanziamenti, scenari, report, assistente, scontrini, backup, attività automatiche e contabilità (quadratura, ritenute, split payment, ammortamenti, ratei, chiusura e riapertura, blocco del periodo, export) e le funzioni di controllo (consolidato, liquidità di gruppo, indici e allerta, piano, Centrale Rischi, paghe, chiusura del mese, classificazione, commesse, rimanenze, export per il gestionale, QR nei solleciti).

---

## Caricarlo su GitHub e usarlo con Emergent

1. Crea un repository **privato** su GitHub (es. `tesoreria-gruppo`).
2. Carica il contenuto di questa cartella. Da terminale:
   ```bash
   git init
   git add .
   git commit -m "Prima versione"
   git branch -M main
   git remote add origin https://github.com/TUO-UTENTE/tesoreria-gruppo.git
   git push -u origin main
   ```
   Oppure dalla pagina del repository: *Add file → Upload files*, trascinando le cartelle.
   I file `.env` non vanno caricati (sono già esclusi da `.gitignore`).
3. In Emergent collega il tuo account GitHub e importa il repository.
4. Dai all'agente di Emergent il file `EMERGENT.md`: spiega la struttura del progetto e le regole
   da rispettare quando aggiunge funzioni.

---

## Primo avvio con dati veri

1. `SEED_DEMO=false`, `MONGO_URL` con il tuo database MongoDB, `JWT_SECRET` lungo e casuale.
2. Crea il tuo utente titolare:
   ```bash
   cd backend
   python scripts/create_owner.py
   ```
   Lo script chiede email, nome e password.
3. Accedi, vai in **Impostazioni → + Nuova azienda** e inserisci le tue aziende con la **partita IVA corretta**
   (serve per riconoscere le fatture XML).
4. Attiva la verifica in due passaggi in **Impostazioni**.
5. Invita commercialista e collaboratori da **Utenti e accessi**.

---

## Importare gli estratti conto (conti manuali)

È il modo per usare subito il programma con i conti veri, senza costi e senza provider.

1. Nella pagina dell'azienda: **Conti → + Conto manuale** (banca, nome, IBAN, saldo attuale).
2. Nell'home banking scarica la lista movimenti ("Esporta movimenti", "Lista movimenti").
3. Nel programma: **Importa estratto conto**, scegli il file, controlla l'anteprima e conferma.

| Formato | Dove si trova di solito | Note |
|---|---|---|
| **Excel (.xlsx) / CSV** | Home banking di quasi tutte le banche | Le colonne (Data, Descrizione, Importo oppure Dare/Avere, Entrate/Uscite, Saldo) vengono riconosciute da sole; se il file ha nomi insoliti si scelgono a mano nella finestra di import. I vecchi .xls vanno salvati come .xlsx. |
| **CAMT.053 (.xml)** | Corporate banking, servizi CBI | Formato standard europeo: contiene anche IBAN e saldo finale. Il programma avvisa se l'IBAN del file non è quello del conto. |
| **CBI "RH" (.txt)** | Corporate banking (rendicontazione movimenti) | Tracciato a larghezza fissa. **Da verificare con un file reale della tua banca**: le posizioni dei campi sono in `backend/app/services/statements.py` (`parse_cbi`). |

- Si possono caricare periodi che si sovrappongono: i movimenti già presenti non vengono duplicati.
- Se il file contiene il saldo, il saldo del conto si aggiorna da solo; altrimenti lo si scrive nella finestra di import.
- La vista di gruppo avvisa quando un conto manuale non viene aggiornato da più di 7 giorni.
- Quando attiverai il collegamento automatico, **Rendi automatico** trasforma il conto manuale: i movimenti
  importati restano e quelli nuovi arrivano da soli, a partire dal giorno dopo l'ultimo importato.
- Nella cartella `esempi/` ci sono tre file di prova (CSV, CAMT.053, CBI).

---


**PDF**: va bene anche l'estratto conto in PDF. Il programma legge le righe «data … importo» e capisce entrate e uscite
dalle colonne Dare/Avere (o dal segno). Controlla sempre l'anteprima: se i segni sono rovesciati c'è «Inverti i segni».
I PDF scansionati (immagini) si leggono solo con l'assistente collegato a Claude; altrimenti scarica il CSV o l'Excel.

**Carte di credito**: aggiungile con «+ Conto o carta» → Carta di credito, indicando il conto su cui vengono addebitate.
Ogni mese carichi l'estratto della carta: le spese diventano movimenti della carta (da riconciliare con fatture e
scontrini), il saldo è il debito da addebitare. L'addebito mensile sul conto e il «pagamento saldo» sull'estratto carta
sono un giroconto: confermalo in «Tra le aziende» e le spese non contano due volte. File di prova:
`esempi/estratto_conto_esempio.pdf` e `esempi/estratto_carta_esempio.pdf` (rigenerabili con `python scripts/make_sample_pdfs.py`).

## Notifiche, email e WhatsApp

Le notifiche nel programma funzionano sempre. Per email e WhatsApp, nel file `backend/.env`:

- **Email**: `EMAIL_PROVIDER=smtp` e i dati del server di posta (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_FROM`). Va bene la casella della tua azienda (Aruba, Register, Google Workspace,
  Microsoft 365...). Con `EMAIL_PROVIDER=demo` le email non partono e restano visibili in
  **Impostazioni → Casella di prova**.
- **WhatsApp**: `WHATSAPP_PROVIDER=meta` con un account WhatsApp Business Cloud API (Meta): servono il token,
  l'ID del numero e un modello di messaggio approvato (`WHATSAPP_TEMPLATE`) con un parametro di testo.
- Ogni utente sceglie cosa ricevere in **Impostazioni → Notifiche**.

I controlli partono da soli ogni mattina dall'ora `ALERTS_HOUR` (riepilogo il lunedì, report il primo del mese).
Ogni avviso arriva una volta sola. Se il backend gira su più copie, lascia `SCHEDULER_ENABLED=true` su una sola.

## Assistente

- `AI_PROVIDER=demo` (predefinito): risponde alle domande più comuni con i dati del programma, senza servizi esterni.
- `AI_PROVIDER=anthropic` con `ANTHROPIC_API_KEY`: usa Claude, capisce qualsiasi domanda e legge le foto degli scontrini.
  I dati necessari alla risposta vengono inviati al servizio: indicalo nell'informativa privacy.
- `AI_PROVIDER=none`: disattivato.

L'assistente usa solo strumenti di **sola lettura** e vede solo le aziende dell'utente che fa la domanda.

## Contabilità

Menu **Contabilità**: Prima nota · Piano dei conti · Registri IVA · Bilancio · Cespiti · Chiusure e rettifiche.

**Come nascono le registrazioni**
- Ogni fattura importata crea la sua registrazione (FV, FA, note di credito) con IVA, ritenuta, split payment e bollo.
  Il conto di costo si sceglie dal pulsante «Contabilità» nella pagina Fatture e il programma lo ricorda per quel fornitore.
- Ogni movimento riconciliato o «senza fattura» crea l'incasso o il pagamento. I movimenti senza fattura vanno sul conto
  collegato alla loro categoria (modificabile in Piano dei conti → Collegamento categorie). Le rate dei mutui vengono
  divise in capitale e interessi.
- I movimenti ancora da riconciliare **non** sono in contabilità: il controllo «Quadratura banca» lo mostra.
- Le registrazioni automatiche non si modificano a mano: si cambia la fattura o il movimento e si aggiornano da sole.

**Primo avvio con dati veri**: inserisci in prima nota i saldi al 1° gennaio con il modello «Saldi iniziali»
(banche, clienti e fornitori aperti, cespiti, mutui, capitale). Il controllo di quadratura delle banche ti dice se mancano.

**Fine anno**: liquidazioni IVA → ammortamenti → ratei e risconti → stipendi, TFR e imposte dalla prima nota →
controlli → «Chiudi l'esercizio». La chiusura blocca l'anno: fatture, movimenti e registrazioni con quella data non
si possono più cambiare finché non si riapre.

**Cosa resta al commercialista** (il programma prepara i dati, non li sostituisce): dichiarazioni (Redditi, IVA, 770),
calcolo definitivo delle imposte, deposito del bilancio in XBRL, conservazione digitale a norma, elaborazione delle paghe,
rimanenze di magazzino. I dati di esempio contengono riepiloghi mensili dello «storico» per avere un bilancio credibile.

## Controllo, gruppo e automazioni

- **Salute dell'azienda** (menu Controllo e strategia): i segnali seguono le soglie di legge (art. 3 c. 4 e art. 25-novies del
  Codice della crisi). Il programma usa i dati che ha: scadenze non pagate, fatture, paghe, Centrale Rischi, finanziamenti.
  Per un controllo completo inserisci paghe e Centrale Rischi e tieni aggiornate le scadenze F24 (nella descrizione «INPS»,
  «INAIL», «IVA» o «cartella» per riconoscere il creditore). È un supporto: la valutazione resta dell'organo di controllo e del commercialista.
- **Paghe**: dal primo mese inserito, il bonifico «Stipendi» non va più a costo ma chiude il debito verso i dipendenti (il costo è
  nella registrazione delle paghe). La voce ricorrente «Stipendi» non viene contata due volte nella previsione.
- **Chiusura del mese**: chiudere il mese blocca fatture, movimenti e registrazioni fino a fine mese (come la chiusura
  dell'esercizio). Si riapre solo l'ultimo mese chiuso.
- **Liquidità di gruppo**: imposta per ogni azienda la riserva minima (cliccando sull'importo). I trasferimenti proposti
  diventano un pagamento da autorizzare, come gli altri bonifici.
- **Export per il gestionale**: chiedi allo studio il tracciato di importazione (colonne, separatore, codici conto) e impostalo
  una volta in Export e report → «Imposta il formato».

## Provvigioni sulle attivazioni

1. **Listino e venditori → Partner**: un partner per ogni gestore, con il periodo di storno (mesi entro cui, se il cliente cessa, la provvigione si recupera).
2. **Listino**: per ogni offerta il testo che compare nel file del partner («Riconosce»), quanto ti paga il partner e quanto dai a struttura e dipendente.
3. **Strutture e dipendenti**: con i codici venditore che usa il vostro backoffice.
4. **Attivazioni**, ogni giorno: carica il file del backoffice e poi gli avanzamenti di ogni partner. La prima volta, se le colonne non
   vengono riconosciute, le indichi a mano; gli stati nuovi (es. «FASE 7B») si interpretano in Partner e stati.
5. **Rendiconti**, dopo la fine del mese: controlla e approva. Le strutture ricevono il pagamento nello scadenzario (da autorizzare dopo la loro
   fattura); i bonus dei dipendenti si scaricano in Excel per il consulente del lavoro.

File di prova in `esempi/`: `backoffice_vendite_esempio.csv`, `avanzamenti_fastweb_esempio.csv`, `avanzamenti_vodafone_esempio.csv`
(azienda di prova: Azienda Beta Srl).

## Guida e video dentro il programma

Nel menu **Aiuto → Guida e video** ci sono le istruzioni di tutto il programma: 27 guide passo per passo con le immagini
delle schermate e 9 video brevi (da 30 secondi a un minuto). In ogni pagina, in alto, il pulsante «Guida: …» apre la guida di quella pagina.

- I testi stanno in `frontend/src/guide/guides.json` (si possono modificare a mano: titolo, testo di ogni passo).
- Le immagini e i video in `frontend/public/guida/` si creano dal programma vero, con i dati di prova:

```bash
# backend con i dati di prova appena avviato (MONGO_URL=mock://) su :8001, frontend compilato e servito su :3000
pip install playwright && playwright install chromium   # serve anche ffmpeg
python tools/guida/cattura.py               # rifà tutte le guide
python tools/guida/cattura.py carte fatture # solo alcune
```

Dopo una modifica all'interfaccia basta rilanciarlo: lo script segnala i passi in cui non ha trovato un pulsante.

## Backup

- Automatico: imposta `BACKUP_DIR` (una cartella sul server) e ogni giorno viene creata una copia;
  quelle più vecchie di `BACKUP_KEEP_DAYS` giorni si cancellano da sole. Conserva anche una copia fuori dal server.
- A mano: `python scripts/backup.py /percorso/cartella`
- Ripristino: `python scripts/restore.py /percorso/tesoreria_AAAA-MM-GG_HHMM.json.gz` (sostituisce tutti i dati, chiede conferma).
- Se usi MongoDB Atlas o l'hosting di Emergent, attiva anche i loro backup.

## Prima di usare dati veri: controllo finale

1. `SEED_DEMO=false` e `REACT_APP_SHOW_DEMO_LOGIN=false`
2. `JWT_SECRET` lungo e casuale
3. `REQUIRE_2FA_FOR_PAYMENTS=true` (predefinito): chi autorizza i pagamenti deve attivare la verifica in due passaggi
4. Indirizzo con **HTTPS** (necessario anche per installare l'app sul telefono)
5. `BACKUP_DIR` impostato, oppure backup del database attivi presso il fornitore
6. Email configurata (`EMAIL_PROVIDER=smtp`) per solleciti e avvisi
7. In **IVA stimata → Impostazioni IVA**: periodicità corretta e credito di inizio anno per ogni azienda

---

## Collegare i servizi reali

Ogni servizio esterno ha un'interfaccia comune e una versione "demo". Per collegare quello reale si
scrive una nuova classe nello stesso file e la si attiva dal file `.env`.

| Servizio | File | Cosa serve |
|---|---|---|
| **Banche (open banking)** | `backend/app/integrations/banking.py` | Contratto con un aggregatore open banking autorizzato PSD2 (AISP). Il flusso reale manda l'utente sulla pagina di consenso della banca: il frontend è già pronto a gestire il `redirect_url`. |
| **Fatture elettroniche (SDI)** | `backend/app/integrations/sdi.py` | Un intermediario accreditato con API, collegato al codice destinatario di ogni azienda. L'import manuale dei file XML funziona già con fatture vere. |
| **Pagamenti** | `backend/app/integrations/payments.py` | Un servizio di disposizione pagamenti (PISP) o un partner bancario. Di solito la conferma finale avviene con le credenziali della banca (SCA). |

Altri passi consigliati prima dell'uso con dati veri:

- **Inviti via email**: il link di invito oggi si copia a mano; con l'email configurata si può spedire in automatico
  (punto indicato in `backend/app/routers/members.py`).
- **Documenti**: oggi sono salvati in MongoDB (fino a 10 MB l'uno). Con molti file conviene spostarli
  su uno storage come S3.
- **Sessione**: il token di accesso è salvato nel browser; per maggiore sicurezza si può passare a cookie httpOnly.
- **Backup** automatici del database e HTTPS obbligatorio in produzione.

---

## Struttura del progetto

```
backend/
  server.py                  avvio dell'app, elenco delle rotte
  app/
    config.py                impostazioni lette da .env
    permissions.py           ruoli e permessi
    deps.py                  controllo utente e permessi per azienda
    security.py              password, token, verifica in due passaggi
    audit.py                 registro attività
    seed.py                  dati di esempio
    routers/                 rotte API (una per area: auth, banks, invoices, ...)
    services/                logica: riconciliazione, previsione, FatturaPA, export, categorie
    integrations/            banche, SDI, pagamenti, email/WhatsApp, assistente (versioni demo + interfacce)
  scripts/create_owner.py    crea il primo utente titolare
  scripts/backup.py          backup manuale
  scripts/restore.py         ripristino di un backup
  tests/                     test automatici
frontend/
  src/
    App.js                   pagine e percorsi
    lib/                     chiamate al backend, sessione, formattazione
    components/              elementi riutilizzabili (menu, grafici, finestre, note)
    pages/                   una pagina per sezione
```

La documentazione interattiva delle API è su http://localhost:8001/docs con il backend avviato.
