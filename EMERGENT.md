# Istruzioni per l'agente (Emergent o altri)

Questo è un progetto esistente e funzionante. Prima di modificarlo leggi `README.md`.
Continua a sviluppare sopra il codice esistente: **non riscriverlo e non cambiare stack**.

## Stack e convenzioni

- Backend FastAPI in `backend/`, avvio `uvicorn server:app --port 8001`. Database MongoDB con `motor`.
- Variabili: `MONGO_URL`, `DB_NAME`, `JWT_SECRET` (backend) e `REACT_APP_BACKEND_URL` (frontend).
- Tutte le rotte sotto `/api` (router in `backend/app/routers/`, registrati in `server.py`).
- Frontend React (Create React App) + Tailwind in `frontend/`. Chiamate al backend sempre tramite
  `src/lib/api.js` (aggiunge il token). Componenti comuni in `src/components/ui.js`.
- Interfaccia e messaggi in **italiano**.

## Regole da rispettare

1. **Permessi**: ogni rotta che legge o modifica dati di un'azienda deve chiamare
   `require(user, company_id, "<permesso>")` (o `load(...)` in `routers/common.py`).
   I permessi sono in `backend/app/permissions.py`. Un utente non deve mai vedere aziende
   su cui non ha una membership: in quel caso si risponde 404, non 403.
2. **Importi** sempre in **centesimi interi** (`*_cents`), mai float. Il frontend li formatta con `eur()`.
3. **ID** sono stringhe UUID nel campo `id`; non esporre mai `_id` di MongoDB (usa la proiezione `{"_id": 0}`).
4. **Date** di business come stringhe `YYYY-MM-DD`; date/ore di sistema in ISO UTC.
5. **Registro attività**: ogni azione importante (pagamenti, permessi, export, eliminazioni) chiama `audit.log(...)`.
6. **Servizi esterni** (banche, SDI, pagamenti, email) vanno dietro le interfacce in `backend/app/integrations/`,
   scelte dal `.env`. Non mettere chiamate dirette ai provider dentro i router.
7. **IBAN completi** non vanno mai restituiti al frontend per i conti dell'azienda (si usa `iban_masked`).
8. Dopo ogni modifica al backend esegui `cd backend && pytest` e aggiungi test per le nuove funzioni.
9. Non salvare segreti nel codice: solo nel `.env`.

## Conti manuali ed estratti conto

- I conti con `provider: "manuale"` si aggiornano solo con l'import (`routers/banks.py`, `services/statements.py`).
- Ogni movimento importato ha un `external_id` calcolato dall'impronta (data, importo, descrizione): non cambiarne
  la formula, altrimenti i reimport creerebbero doppioni.
- Il tracciato CBI in `parse_cbi` va verificato con file reali delle banche dell'utente.

## Altre regole

- **Intercompany**: i movimenti tra aziende del gruppo hanno categoria `Intercompany` (o `Giroconti`) e il campo
  `intercompany`. Le categorie in `NEUTRAL_CATEGORIES` vanno sempre escluse da totali, grafici, budget e report.
- **Notifiche**: per avvisare qualcuno usa `services/notifications.notify(...)` con una `key` se l'avviso non deve
  ripetersi. Email e WhatsApp passano solo da `integrations/messaging.py`.
- **Attività automatiche**: si aggiungono in `services/scheduler.tick()` con `_once(...)`, mai con cicli propri.
- **Assistente**: può usare solo gli strumenti di sola lettura in `services/assistant_tools.py`, sempre filtrati
  sulle aziende dell'utente. Non dare all'assistente strumenti che modificano dati o fanno pagamenti.
  Per usare la chiave LLM di Emergent si può aggiungere un provider in `integrations/ai.py` al posto di `AnthropicAI`.
- **IVA e scenari sono stime**: non presentarle mai come calcoli fiscali definitivi.
- **Pagamenti**: l'autorizzazione richiede la verifica in due passaggi (`REQUIRE_2FA_FOR_PAYMENTS`). Non rimuovere il controllo.

## Contabilità (partita doppia)

- Le registrazioni stanno in `entries` con righe `{account, dare, avere, party_key, party_name, cost_center_id}` in centesimi:
  dare e avere devono **sempre** pareggiare (`services/accounting.validate_lines`).
- Registrazioni automatiche: `source="auto"` e `source_key` (`inv:<id>`, `tx:<id>`). Dopo ogni modifica a fatture o
  movimenti chiama `services/accounting.sync_source(db, "invoice"|"transaction", id)`; non scriverle a mano.
- Procedure di fine periodo: `source="rettifica"` (`amm:<anno>`, `rat:<id>`, `liqiva:<periodo>`), chiusure
  `source="chiusura"/"apertura"`. Prima nota: `source="manuale"`.
- Periodo chiuso: `companies.accounting_lock_date`. Ogni rotta che modifica fatture o movimenti deve chiamare
  `routers/common.assert_open(company_id, data)`.
- Il residuo da pagare di una fattura è `services/invoices.payable(inv)` (totale − ritenuta − IVA in split payment),
  mai `total_cents`.
- Piano dei conti di partenza e schema CEE in `services/chart.py`; i conti si cercano per `key`, non per codice.
- Permessi: `view_accounting`, `manage_accounting`, `close_fiscal_year`.
- Non sono previsti (e non vanno presentati come presenti): dichiarativi, XBRL, conservazione sostitutiva, paghe.

## Controllo, gruppo e automazioni

- Servizi: `services/analysis.py` (indici, DSCR, segnali di allerta; soglie di legge nei testi `rule`), `services/group.py`
  (consolidato, liquidità di gruppo, confronto), `services/plan.py`, `services/central_risk.py`, `services/payroll.py`,
  `services/month_close.py`, `services/account_suggest.py`, `services/inventory.py`, `services/epc.py`.
  Rotte in `routers/control.py` e `routers/operations.py`.
- `build_statements()` in `accounting_reports.py` costruisce SP e CE da saldi per conto: riusalo invece di ricalcolare.
- Le scadenze hanno il campo facoltativo `creditor` (fornitori, dipendenti, inps, inail, iva, erario, riscossione, gruppo):
  usalo quando ne crei di nuove, serve ai segnali di allerta (`analysis.creditor_of`).
- Le paghe registrano con `source="paghe"` e `source_key="paghe:<id>"`; le scadenze collegate hanno `payroll_id` e `payroll_role`.
- Commesse = `cost_centers` con `kind="commessa"`: si collegano ovunque si usa `cost_center_id`.
- Permesso nuovo: `manage_payroll`. Le pagine di analisi usano `view_accounting`.
- Non presentare indici, segnali e piano come giudizi definitivi: sono strumenti di supporto.

## Provvigioni

- Servizio `services/commissions.py`, rotte `routers/commissions.py`, permessi `view_commissions` / `manage_commissions`.
- Le attivazioni si identificano per (azienda, partner, codice pratica): un nuovo import aggiorna lo stato e aggiunge alla `history`.
- Il pagamento è un registro: una pratica entra in un rendiconto con `paid_statement_id`; lo storno con `storno_statement_id`.
  Non ricalcolare i rendiconti approvati: si riaprono con `reopen()` (solo l'ultimo del percettore).
- Stati normalizzati: `in_lavorazione`, `attiva`, `ko`, `cessata` (mappa per partner in `status_map`).

## Guida

- Testi in `frontend/src/guide/guides.json` (sezioni, guide, passi con azioni `do` e `highlight` per Playwright); `pages` collega la guida
  alle rotte per il pulsante contestuale in `Layout.js`. Se cambi un'etichetta di pulsante usata in un `highlight`, aggiorna la guida.
- Media generati da `tools/guida/cattura.py` in `frontend/public/guida/` e indicizzati in `frontend/src/guide/media.json`.

## Prossime funzioni previste

- Collegamento reale open banking (interfaccia in `integrations/banking.py`, il frontend gestisce già `redirect_url`)
- Intermediario SDI reale (`integrations/sdi.py`) e invio delle fatture attive
- Pagamenti reali con conferma SCA (`integrations/payments.py`)
- Invio automatico via email del link di invito
- Documenti su storage esterno (S3)
- Contabilità: rimanenze di magazzino, export verso i gestionali dei commercialisti, IVA per cassa e reverse charge, consolidato di gruppo
