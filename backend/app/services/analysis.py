"""Salute dell'azienda: indici di bilancio, DSCR e segnali di allerta del Codice della crisi.

Riferimenti normativi (D.Lgs. 14/2019, Codice della crisi d'impresa e dell'insolvenza):
- art. 2086 c.c. e art. 3 CCII: adeguati assetti organizzativi, amministrativi e contabili per rilevare
  per tempo gli squilibri e verificare la sostenibilità dei debiti nei 12 mesi successivi;
- art. 3, comma 4: segnali di allarme (retribuzioni, fornitori, banche, creditori pubblici);
- art. 25-novies: soglie oltre le quali INPS, INAIL, Agenzia delle Entrate e Agenzia Riscossione segnalano.
Le soglie sono riportate così come sono nel testo di legge; il programma usa i dati che ha e dice quando ne mancano.
"""
from datetime import date, timedelta

from ..utils import parse_date, today
from .accounting_reports import financial_statements
from .categories import NEUTRAL_CATEGORIES
from .invoices import payable
from .loans import CREDIT_LINES, installments_between, schedule

GREEN, YELLOW, RED, GRAY = "verde", "giallo", "rosso", "grigio"


def _sum(voci: dict, prefix: str) -> int:
    return sum(v for c, v in voci.items() if c == prefix or c.startswith(prefix + ".") or
               (len(c) == len(prefix) + 1 and c.startswith(prefix) and c[-1] in "abc"))


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def _grade(value, green, yellow, higher_is_better=True):
    if value is None:
        return GRAY
    if higher_is_better:
        return GREEN if value >= green else YELLOW if value >= yellow else RED
    return GREEN if value <= green else YELLOW if value <= yellow else RED


async def loan_split(db, company_id: str, ref: date) -> dict:
    """Debiti per finanziamenti: quota entro 12 mesi e oltre, servizio del debito a 6 e 12 mesi."""
    out = {"short": 0, "long": 0, "service_6": 0, "service_12": 0, "credit_used": 0, "credit_limit": 0}
    start = ref.isoformat()
    in6 = (ref + timedelta(days=182)).isoformat()
    in12 = (ref + timedelta(days=365)).isoformat()
    async for loan in db.loans.find({"company_id": company_id, "active": {"$ne": False}}, {"_id": 0}):
        if loan["kind"] in CREDIT_LINES:
            out["credit_used"] += int(loan.get("used_cents") or 0)
            out["credit_limit"] += int(loan.get("limit_cents") or 0)
            continue
        rows = schedule(loan)
        future = [r for r in rows if r["date"] >= start]
        principal_future = sum(r["principal_cents"] for r in future) if loan.get("principal_cents") else 0
        next12 = sum(r["principal_cents"] for r in future if r["date"] < in12) if loan.get("principal_cents") else 0
        out["short"] += next12
        out["long"] += principal_future - next12
        out["service_6"] += sum(r["installment_cents"] for r in installments_between(loan, start, in6))
        out["service_12"] += sum(r["installment_cents"] for r in installments_between(loan, start, in12))
    return out


async def ratios(db, company: dict, year: int | None = None) -> dict:
    """Indici di bilancio con spiegazione e semaforo. I flussi dell'anno in corso sono riportati a 12 mesi."""
    t = today()
    year = year or t.year
    st = await financial_statements(db, company["id"], year)
    sp, ce = st["voci"]["sp"], st["voci"]["ce"]
    year_end = date(year, 12, 31)
    ref = min(t, year_end)
    elapsed = (ref - date(year, 1, 1)).days + 1
    factor = 365 / elapsed if year == t.year and elapsed < 365 else 1.0

    ricavi = _sum(ce, "CE.A.1")
    valore = _sum(ce, "CE.A")
    costi = _sum(ce, "CE.B")
    amm = _sum(ce, "CE.B.10")
    acquisti = _sum(ce, "CE.B.6") + _sum(ce, "CE.B.7") + _sum(ce, "CE.B.8")
    oneri_fin = _sum(ce, "CE.C.17")
    ebitda = valore - costi + amm
    ebit = valore - costi
    utile = st["sintesi"]["utile"]

    liquidita = _sum(sp, "SP.A.C.IV")
    crediti = _sum(sp, "SP.A.C.II")
    crediti_clienti = _sum(sp, "SP.A.C.II.1")
    rimanenze = _sum(sp, "SP.A.C.I")
    circolante = _sum(sp, "SP.A.C") + _sum(sp, "SP.A.D")
    debiti = _sum(sp, "SP.P.D") + _sum(sp, "SP.P.E")
    fornitori = _sum(sp, "SP.P.D.7")
    debiti_banche = _sum(sp, "SP.P.D.4")
    pn = _sum(sp, "SP.P.A")
    totale = st["totale_passivo"]
    loans = await loan_split(db, company["id"], ref)
    debiti_breve = max(0, debiti - loans["long"])
    pfn = debiti_banche - liquidita
    ebitda_y = round(ebitda * factor)

    def item(id_, label, value, fmt, grade, formula, meaning, detail=""):
        return {"id": id_, "label": label, "value": value, "format": fmt, "status": grade,
                "formula": formula, "meaning": meaning, "detail": detail}

    cr = _ratio(circolante, debiti_breve)
    acid = _ratio(liquidita + crediti, debiti_breve)
    aut = _ratio(pn, totale)
    margin = _ratio(ebitda, ricavi)
    ros = _ratio(ebit, ricavi)
    roe = _ratio(round(utile * factor), pn) if pn > 0 else None
    dso = (crediti_clienti / (ricavi * factor * 1.22) * 365) if ricavi > 0 else None
    dpo = (fornitori / (acquisti * factor * 1.22) * 365) if acquisti > 0 else None
    fin = _ratio(oneri_fin, ricavi)
    if pfn <= 0:
        pfn_ebitda = None
        pfn_grade = GREEN
    elif ebitda_y > 0:
        pfn_ebitda = pfn / ebitda_y
        pfn_grade = _grade(pfn_ebitda, 3, 5, higher_is_better=False)
    else:
        pfn_ebitda = None
        pfn_grade = GREEN if pfn <= 0 else RED

    items = [
        item("patrimonio", "Patrimonio netto", pn, "eur", GREEN if pn > 0 else RED,
             "Capitale + riserve + risultato dell'anno",
             "Se è negativo l'azienda ha perso più di quanto ha: è il primo segnale di crisi e obbliga a intervenire "
             "(ricapitalizzazione o altri provvedimenti previsti dal codice civile)."),
        item("liquidita_corrente", "Liquidità corrente", cr, "x", _grade(cr, 1.2, 1.0),
             "Attivo circolante ÷ debiti da pagare entro 12 mesi",
             "Quante volte i soldi e i crediti a breve coprono i debiti a breve. Sotto 1 i debiti a breve superano le risorse a breve."),
        item("acid_test", "Liquidità immediata", acid, "x", _grade(acid, 1.0, 0.8),
             "(Banche e cassa + crediti) ÷ debiti a breve",
             "Come la precedente ma senza il magazzino, che non si trasforma subito in denaro."),
        item("autonomia", "Autonomia finanziaria", aut, "%", _grade(aut, 0.3, 0.15),
             "Patrimonio netto ÷ totale delle fonti",
             "Quanta parte dell'azienda è finanziata con mezzi propri invece che con debiti. Le banche guardano molto questo dato."),
        item("pfn_ebitda", "Debito finanziario netto / MOL", pfn_ebitda, "x", pfn_grade,
             "(Debiti verso banche − liquidità) ÷ margine operativo lordo annuo",
             "In quanti anni il margine operativo ripagherebbe i debiti finanziari. Oltre 5 anni è considerato pesante.",
             f"Debito finanziario netto {pfn / 100:,.0f} €".replace(",", ".") if pfn > 0 else
             f"Nessun debito netto: la liquidità supera i debiti verso banche di {-pfn / 100:,.0f} €".replace(",", ".")),
        item("ebitda_margin", "Margine operativo lordo (MOL) sui ricavi", margin, "%", _grade(margin, 0.10, 0.05),
             "(Valore della produzione − costi della produzione + ammortamenti) ÷ ricavi",
             "Quanto resta di ogni 100 € di vendite dopo i costi di gestione, prima di ammortamenti, interessi e imposte.",
             f"MOL {ebitda / 100:,.0f} €".replace(",", ".")),
        item("ros", "Redditività delle vendite (ROS)", ros, "%", _grade(ros, 0.05, 0.0),
             "Risultato operativo ÷ ricavi", "Quanto guadagna l'attività caratteristica su ogni 100 € venduti."),
        item("roe", "Redditività del capitale proprio (ROE)", roe, "%", _grade(roe, 0.08, 0.0) if roe is not None else (RED if pn <= 0 else GRAY),
             "Utile annuo ÷ patrimonio netto", "Il rendimento dei soldi messi dai soci."),
        item("dso", "Giorni medi di incasso", dso, "gg", _grade(dso, 60, 90, higher_is_better=False),
             "Crediti verso clienti ÷ vendite annue (IVA compresa) × 365",
             "Quanti giorni passano in media tra la fattura e l'incasso."),
        item("dpo", "Giorni medi di pagamento", dpo, "gg", _grade(dpo, 90, 120, higher_is_better=False),
             "Debiti verso fornitori ÷ acquisti annui (IVA compresa) × 365",
             "Quanti giorni passano in media prima di pagare i fornitori. Se è molto più alto dei giorni di incasso "
             "l'azienda si sta finanziando con i fornitori."),
        item("oneri_finanziari", "Oneri finanziari sui ricavi", fin, "%", _grade(fin, 0.02, 0.05, higher_is_better=False),
             "Interessi e oneri finanziari ÷ ricavi", "Quanto pesano gli interessi sulle vendite."),
    ]
    return {"year": year, "annualized": factor != 1.0, "elapsed_days": elapsed, "items": items,
            "values": {"ricavi": ricavi, "ebitda": ebitda, "ebit": ebit, "utile": utile, "pn": pn, "liquidita": liquidita,
                       "debiti_breve": debiti_breve, "pfn": pfn, "rimanenze": rimanenze, "totale": totale,
                       "personale": _sum(ce, "CE.B.9")},
            "statements_ok": st["quadra"]}


# ------------------------------------------------------------------ flussi e DSCR

async def operating_cash_flow(db, company_id: str, months: int = 6) -> dict:
    """Flusso di cassa medio mensile della gestione (esclusi giroconti, intercompany e rate dei finanziamenti)."""
    t = today()
    end = t.replace(day=1)
    y, m = end.year, end.month - months
    while m <= 0:
        m += 12
        y -= 1
    start = date(y, m, 1)
    total = 0
    async for tx in db.transactions.find({"company_id": company_id, "date": {"$gte": start.isoformat(), "$lt": end.isoformat()}},
                                         {"amount_cents": 1, "category": 1}):
        if tx.get("category") in NEUTRAL_CATEGORIES or tx.get("category") == "Leasing e finanziamenti":
            continue
        total += tx["amount_cents"]
    return {"from": start.isoformat(), "to": (end - timedelta(days=1)).isoformat(), "months": months,
            "total_cents": total, "monthly_cents": round(total / months)}


DEBT_KEYWORDS = {
    "inps": ("inps", "contribut"), "inail": ("inail",), "riscossione": ("riscossione", "cartell", "rottamaz", "ader"),
    "iva": ("iva",), "erario": ("f24", "erario", "agenzia entrate", "ritenut", "ires", "irap"),
    "dipendenti": ("stipend", "retribuz", "cedolin"),
}


def creditor_of(d: dict) -> str:
    """Tipo di creditore di una scadenza di pagamento: dal campo esplicito o dalle parole della descrizione."""
    if d.get("creditor"):
        return d["creditor"]
    if d.get("auto_vat_period"):
        return "iva"
    if d.get("auto_withholding_period"):
        return "erario"
    if d.get("payroll_role") == "netto":
        return "dipendenti"
    if d.get("payroll_role") == "f24":
        return "inps"
    if d.get("invoice_id"):
        return "fornitori"
    text = f"{d.get('description', '')} {d.get('beneficiary', '')}".lower()
    for key, words in DEBT_KEYWORDS.items():
        if any(w in text for w in words):
            return key
    return "fornitori" if d["kind"] == "pagamento" else "erario"


async def overdue_debts(db, company_id: str) -> dict:
    """Debiti scaduti per tipo di creditore e per anzianità."""
    t = today()
    out: dict = {}
    async for d in db.deadlines.find({"company_id": company_id, "kind": {"$ne": "incasso"},
                                      "status": {"$in": ["da_pagare", "in_attesa_autorizzazione"]}}, {"_id": 0}):
        amount = d["amount_cents"]
        if d.get("invoice_id"):
            inv = await db.invoices.find_one({"id": d["invoice_id"]}, {"_id": 0})
            if inv and inv.get("paid_cents"):
                amount = min(amount, payable(inv) - inv["paid_cents"])
        if amount <= 0:
            continue
        days = (t - parse_date(d["due_date"])).days
        b = out.setdefault(creditor_of(d), {"not_due": 0, "overdue": 0, "over30": 0, "over60": 0, "over90": 0, "items": 0})
        if days <= 0:
            b["not_due"] += amount
            continue
        b["overdue"] += amount
        b["items"] += 1
        if days >= 30:
            b["over30"] += amount
        if days > 60:
            b["over60"] += amount
        if days > 90:
            b["over90"] += amount
    return out


async def dscr(db, company: dict) -> dict:
    """DSCR prospettico a 6 e 12 mesi (metodo semplificato, basato sui flussi di cassa).

    Numeratore: liquidità di oggi + flusso medio mensile della gestione × mesi − debiti già scaduti.
    Denominatore: rate di mutui, finanziamenti e leasing in scadenza nel periodo (capitale + interessi).
    """
    banks = await db.bank_accounts.find({"company_id": company["id"], "status": {"$ne": "scollegato"}}, {"balance_cents": 1}).to_list(100)
    cash = sum(b.get("balance_cents", 0) for b in banks)
    flow = await operating_cash_flow(db, company["id"])
    debts = await overdue_debts(db, company["id"])
    overdue = sum(b["overdue"] for b in debts.values())
    loans = await loan_split(db, company["id"], today())
    out = {"cash_cents": cash, "monthly_flow_cents": flow["monthly_cents"], "flow_period": flow,
           "overdue_debts_cents": overdue, "periods": []}
    for months, service in ((6, loans["service_6"]), (12, loans["service_12"])):
        available = cash + flow["monthly_cents"] * months - overdue
        value = available / service if service else None
        status = GREEN if value is None and available >= 0 else _grade(value, 1.2, 1.0) if value is not None else RED
        out["periods"].append({"months": months, "available_cents": available, "debt_service_cents": service,
                               "value": value, "status": status})
    return out


# ------------------------------------------------------------------ segnali di allerta

def legal_form(company: dict) -> str:
    if company.get("legal_form"):
        return company["legal_form"]
    name = company.get("name", "").lower().replace(".", "")
    if any(w in name.split() for w in ("srl", "spa", "srls", "sapa", "scarl", "scrl")) or "srl" in name or "spa" in name:
        return "capitali"
    if any(w in name.split() for w in ("snc", "sas", "ss")):
        return "persone"
    return "individuale"


def _signal(id_, title, status, detail, rule, amount=None, link=None):
    return {"id": id_, "title": title, "status": status, "detail": detail, "rule": rule, "amount_cents": amount, "link": link}


def _eur(c: int) -> str:
    return f"{c / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


async def warning_signals(db, company: dict) -> dict:
    t = today()
    cid = company["id"]
    debts = await overdue_debts(db, cid)
    empty = {"not_due": 0, "overdue": 0, "over30": 0, "over60": 0, "over90": 0, "items": 0}
    signals = []

    # 1. Retribuzioni: scadute da almeno 30 giorni, oltre metà del monte retribuzioni mensile
    pay = debts.get("dipendenti", empty)
    last = await db.payrolls.find_one({"company_id": cid}, {"_id": 0}, sort=[("month", -1)])
    monthly = last["netto_cents"] if last else 0
    if not monthly:
        rec = await db.recurring.find_one({"company_id": cid, "active": True, "description": {"$regex": "stipend", "$options": "i"}})
        monthly = rec["amount_cents"] if rec else 0
    if pay["over30"] and monthly:
        st = RED if pay["over30"] > monthly / 2 else YELLOW
    else:
        st = YELLOW if pay["over30"] else GREEN
    signals.append(_signal("retribuzioni", "Stipendi non pagati", st,
                           f"Scaduti da almeno 30 giorni: {_eur(pay['over30'])}" + (f" · monte stipendi mensile {_eur(monthly)}" if monthly else
                                                                                   " · inserisci le paghe per avere il confronto"),
                           "Art. 3 c. 4 a) CCII: debiti per retribuzioni scaduti da almeno 30 giorni pari a oltre la metà "
                           "dell'ammontare complessivo mensile delle retribuzioni.", pay["over30"], "/scadenze"))

    # 2. Fornitori: scaduti da almeno 90 giorni superiori ai debiti non ancora scaduti
    sup = debts.get("fornitori", empty)
    st = RED if sup["over90"] and sup["over90"] > sup["not_due"] else YELLOW if sup["over60"] else GREEN
    signals.append(_signal("fornitori", "Fornitori pagati in forte ritardo", st,
                           f"Scaduti da oltre 90 giorni {_eur(sup['over90'])} · non ancora scaduti {_eur(sup['not_due'])} · "
                           f"totale scaduto {_eur(sup['overdue'])}",
                           "Art. 3 c. 4 b) CCII: debiti verso fornitori scaduti da almeno 90 giorni di ammontare superiore "
                           "a quello dei debiti non scaduti.", sup["over90"], "/crediti"))

    # 3. Banche: sconfinamenti da almeno 60 giorni pari ad almeno il 5% delle esposizioni
    cr = await db.central_risk.find({"company_id": cid}, {"_id": 0}).sort("month", -1).to_list(500)
    months = sorted({r["month"] for r in cr}, reverse=True)
    exposure = over = 0
    persistent = False
    if months:
        latest = [r for r in cr if r["month"] == months[0]]
        exposure = sum(r.get("used_cents", 0) for r in latest)
        over = sum(r.get("overdraft_cents", 0) + r.get("past_due_cents", 0) for r in latest)
        if len(months) > 1 and over:
            prev = [r for r in cr if r["month"] == months[1]]
            persistent = sum(r.get("overdraft_cents", 0) + r.get("past_due_cents", 0) for r in prev) > 0
    async for loan in db.loans.find({"company_id": cid, "kind": {"$in": list(CREDIT_LINES)}, "active": {"$ne": False}}):
        excess = int(loan.get("used_cents") or 0) - int(loan.get("limit_cents") or 0)
        if excess > 0 and not months:
            over += excess
            exposure += int(loan.get("used_cents") or 0)
    share = over / exposure if exposure else 0
    st = RED if over and persistent and share >= 0.05 else YELLOW if over else GREEN
    signals.append(_signal("banche", "Sconfinamenti e rate scadute con le banche", st,
                           (f"Sconfinamenti e scaduti {_eur(over)} su esposizioni per {_eur(exposure)} ({share:.0%})"
                            + (" · presenti da almeno due mesi" if persistent else "")) if over else
                           ("Nessuno sconfinamento" + (f" nella Centrale Rischi di {months[0][5:]}/{months[0][:4]}" if months else
                                                       " (aggiungi i dati della Centrale Rischi per un controllo completo)")),
                           "Art. 3 c. 4 c) CCII: esposizioni verso banche scadute da più di 60 giorni o oltre il limite degli "
                           "affidamenti da almeno 60 giorni, se pari almeno al 5% del totale delle esposizioni.", over, "/centrale-rischi"))

    # 4. Creditori pubblici qualificati (art. 25-novies CCII)
    prev_year = t.year - 1
    vol = 0
    async for inv in db.invoices.find({"company_id": cid, "direction": "attiva", "date": {"$gte": f"{prev_year}-01-01",
                                                                                        "$lte": f"{prev_year}-12-31"}},
                                      {"taxable_cents": 1}):
        vol += inv.get("taxable_cents") or 0
    iva = debts.get("iva", empty)["overdue"]
    iva_threshold_hit = iva > 2_000_000 or (iva > 500_000 and (vol == 0 or iva >= vol * 0.10))
    st = RED if iva_threshold_hit else YELLOW if iva else GREEN
    signals.append(_signal("iva", "IVA non versata", st,
                           f"IVA scaduta e non versata {_eur(iva)}" + (f" · volume d'affari {prev_year} {_eur(vol)}" if vol else
                                                                      f" · volume d'affari {prev_year} non disponibile nel programma"),
                           "Art. 25-novies c. 1 c) CCII: l'Agenzia delle Entrate segnala un debito IVA scaduto oltre 5.000 € e "
                           "non inferiore al 10% del volume d'affari dell'anno precedente; in ogni caso oltre 20.000 €.", iva, "/iva"))

    inps = debts.get("inps", empty)["over90"]
    contrib_prev = 0
    async for p in db.payrolls.find({"company_id": cid, "month": {"$regex": f"^{prev_year}-"}}):
        contrib_prev += p.get("contributi_ditta_cents", 0) + p.get("contributi_dipendente_cents", 0)
    has_staff = bool(monthly) or bool(last)
    if has_staff:
        hit = inps > 1_500_000 and (not contrib_prev or inps > contrib_prev * 0.30)
    else:
        hit = inps > 500_000
    st = RED if hit else YELLOW if inps or debts.get("inps", empty)["overdue"] else GREEN
    signals.append(_signal("inps", "Contributi INPS non versati", st,
                           f"Scaduti da oltre 90 giorni {_eur(inps)}" + (f" · contributi {prev_year} {_eur(contrib_prev)}" if contrib_prev else ""),
                           "Art. 25-novies c. 1 a) CCII: ritardo oltre 90 giorni superiore al 30% dei contributi dell'anno "
                           "precedente e a 15.000 € (5.000 € per imprese senza dipendenti).", inps, "/scadenze"))

    inail = debts.get("inail", empty)["over90"]
    signals.append(_signal("inail", "Premi INAIL non versati", RED if inail > 500_000 else YELLOW if inail else GREEN,
                           f"Scaduti da oltre 90 giorni {_eur(inail)}",
                           "Art. 25-novies c. 1 b) CCII: premi scaduti da oltre 90 giorni e superiori a 5.000 €.", inail, "/scadenze"))

    form = legal_form(company)
    limit = {"individuale": 10_000_000, "persone": 20_000_000}.get(form, 50_000_000)
    ader = debts.get("riscossione", empty)["over90"]
    signals.append(_signal("riscossione", "Cartelle dell'Agenzia Riscossione", RED if ader > limit else YELLOW if ader else GREEN,
                           f"Scadute da oltre 90 giorni {_eur(ader)} · soglia per la tua forma giuridica {_eur(limit)}",
                           "Art. 25-novies c. 1 d) CCII: carichi scaduti da oltre 90 giorni oltre 100.000 € (imprese individuali), "
                           "200.000 € (società di persone), 500.000 € (altre società).", ader, "/scadenze"))

    # 5. Sostenibilità dei debiti nei 12 mesi e cassa prevista
    d = await dscr(db, company)
    p12 = d["periods"][1]
    signals.append(_signal("dscr", "Sostenibilità dei debiti a 12 mesi (DSCR)", p12["status"],
                           (f"DSCR {p12['value']:.2f}".replace(".", ",") if p12["value"] is not None else "Nessuna rata di finanziamento nei 12 mesi")
                           + f" · risorse disponibili {_eur(p12['available_cents'])} · rate {_eur(p12['debt_service_cents'])}",
                           "Art. 3 c. 3 CCII: gli assetti devono permettere di verificare la sostenibilità dei debiti per "
                           "almeno i 12 mesi successivi. Sotto 1 i flussi previsti non bastano a pagare le rate.", None, "/salute"))
    from .forecast import weekly_forecast
    fc = await weekly_forecast(db, [cid], weeks=13)
    low = fc["lowest"]
    st = RED if low["balance_cents"] < 0 and not fc["uses_credit_lines"] else YELLOW if low["balance_cents"] < 0 else GREEN
    signals.append(_signal("cassa", "Cassa prevista nelle prossime 13 settimane", st,
                           f"Saldo più basso previsto {_eur(low['balance_cents'])}" + (f" nella settimana del {low.get('start', '')[8:10]}/{low.get('start', '')[5:7]}" if low.get("start") else "")
                           + (" · coperto dai fidi disponibili" if fc["uses_credit_lines"] else ""),
                           "Previsione dalle scadenze note (fatture, F24, rate, spese ricorrenti): gli incassi non ancora "
                           "fatturati non sono compresi, quindi è prudente.", low["balance_cents"], "/"))

    order = {RED: 0, YELLOW: 1, GREEN: 2, GRAY: 3}
    overall = min((s["status"] for s in signals), key=lambda s: order[s])
    return {"overall": overall, "signals": signals, "dscr": d, "legal_form": form,
            "note": "Valutazione automatica sui dati del programma: non sostituisce il giudizio dell'organo di controllo e del commercialista."}
