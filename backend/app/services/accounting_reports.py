"""Libri e prospetti contabili: libro giornale, mastrini, partitari, bilancio di verifica,
stato patrimoniale e conto economico (schema CEE), centri di costo, registri IVA, controlli."""
from collections import defaultdict

from ..utils import parse_date, today
from .accounting import balances, ensure_chart
from .chart import CE_SCHEMA, SP_ATTIVO, SP_PASSIVO
from .invoices import payable


async def chart_of(db, company_id: str) -> dict[str, dict]:
    await ensure_chart(db, company_id)
    return {a["code"]: a for a in await db.accounts.find({"company_id": company_id}, {"_id": 0}).sort("code", 1).to_list(5000)}


# ------------------------------------------------------------------ libro giornale

async def journal(db, company_id: str, date_from: str, date_to: str, account: str | None = None, q: str | None = None,
                  source: str | None = None, limit: int = 300, offset: int = 0, newest_first: bool = False) -> dict:
    accounts = await chart_of(db, company_id)
    year_start = f"{date_from[:4]}-01-01"
    # numerazione progressiva dell'anno: ordine per data e poi per inserimento
    ordered = await db.entries.find({"company_id": company_id, "date": {"$gte": year_start, "$lte": date_to}},
                                    {"id": 1, "date": 1, "created_at": 1}).to_list(200000)
    ordered.sort(key=lambda e: (e["date"], e.get("created_at", "")))
    numbers = {e["id"]: n for n, e in enumerate(ordered, start=1)}
    query: dict = {"company_id": company_id, "date": {"$gte": date_from, "$lte": date_to}}
    if account:
        query["lines.account"] = account
    if source:
        query["source"] = source
    entries = await db.entries.find(query, {"_id": 0}).to_list(200000)
    if q:
        ql = q.lower()
        entries = [e for e in entries if ql in (e.get("description") or "").lower() or ql in (e.get("doc_number") or "").lower()]
    entries.sort(key=lambda e: (e["date"], e.get("created_at", "")))
    tot_d = tot_a = 0
    for e in entries:
        e["number"] = numbers.get(e["id"])
        for l in e["lines"]:
            l["account_name"] = accounts.get(l["account"], {}).get("name", "?")
            tot_d += l["dare"]
            tot_a += l["avere"]
    if newest_first:
        entries.reverse()
    return {"total": len(entries), "items": entries[offset:offset + limit], "totals": {"dare": tot_d, "avere": tot_a}}


# ------------------------------------------------------------------ mastrino e partitari

async def ledger(db, company_id: str, account: str, date_from: str, date_to: str, party_key: str | None = None) -> dict:
    accounts = await chart_of(db, company_id)
    acc = accounts.get(account)
    if not acc:
        raise ValueError("Conto non trovato.")
    prefix = account if not acc.get("postable") else None

    def match(l):
        if prefix:
            return l["account"].startswith(prefix + ".")
        return l["account"] == account and (not party_key or l.get("party_key") == party_key)

    opening = 0
    rows = []
    async for e in db.entries.find({"company_id": company_id, "date": {"$lte": date_to}}, {"_id": 0}):
        for l in e["lines"]:
            if not match(l):
                continue
            if e["date"] < date_from:
                opening += l["dare"] - l["avere"]
            else:
                rows.append({"entry_id": e["id"], "date": e["date"], "causale": e["causale"], "description": l.get("description") or e["description"],
                             "doc_number": e.get("doc_number"), "party_name": l.get("party_name"), "dare": l["dare"], "avere": l["avere"],
                             "source": e["source"], "created_at": e.get("created_at", "")})
    rows.sort(key=lambda r: (r["date"], r["created_at"]))
    bal = opening
    for r in rows:
        bal += r["dare"] - r["avere"]
        r["balance"] = bal
    return {"account": acc, "opening": opening, "rows": rows, "closing": bal,
            "totals": {"dare": sum(r["dare"] for r in rows), "avere": sum(r["avere"] for r in rows)}}


async def parties(db, company_id: str, account: str, date_to: str) -> list[dict]:
    """Saldi per controparte di un conto con partitario (clienti, fornitori, società del gruppo)."""
    out: dict[str, dict] = {}
    async for e in db.entries.find({"company_id": company_id, "date": {"$lte": date_to}, "lines.account": account}, {"lines": 1}):
        for l in e["lines"]:
            if l["account"] != account:
                continue
            key = l.get("party_key") or "-"
            p = out.setdefault(key, {"party_key": key, "party_name": l.get("party_name") or "Senza controparte", "dare": 0, "avere": 0})
            p["dare"] += l["dare"]
            p["avere"] += l["avere"]
    rows = [{**p, "saldo": p["dare"] - p["avere"]} for p in out.values()]
    return sorted([r for r in rows if r["saldo"]], key=lambda r: -abs(r["saldo"]))


# ------------------------------------------------------------------ bilancio di verifica

async def trial_balance(db, company_id: str, date_from: str, date_to: str) -> dict:
    accounts = await chart_of(db, company_id)
    bal = await balances(db, company_id, date_from, date_to)
    rows = []
    groups: dict[str, dict] = defaultdict(lambda: {"dare": 0, "avere": 0})
    for code, b in bal.items():
        parts = code.split(".")
        for i in range(1, len(parts)):
            g = groups[".".join(parts[:i])]
            g["dare"] += b["dare"]
            g["avere"] += b["avere"]
    for code, acc in accounts.items():
        b = bal.get(code) if acc.get("postable") else groups.get(code)
        if not b or (not b["dare"] and not b["avere"]):
            continue
        rows.append({"code": code, "name": acc["name"], "level": acc["level"], "kind": acc["kind"],
                     "dare": b["dare"], "avere": b["avere"], "saldo": b["dare"] - b["avere"]})
    leaf = [r for r in rows if accounts[r["code"]].get("postable")]
    td, ta = sum(r["dare"] for r in leaf), sum(r["avere"] for r in leaf)
    return {"rows": rows, "totals": {"dare": td, "avere": ta, "balanced": td == ta},
            "saldi": {"dare": sum(r["saldo"] for r in leaf if r["saldo"] > 0), "avere": -sum(r["saldo"] for r in leaf if r["saldo"] < 0)}}


# ------------------------------------------------------------------ stato patrimoniale e conto economico

async def _statement_balances(db, company_id: str, year: int, date_to: str) -> tuple[dict, dict]:
    """Saldi per SP (cumulati) e per CE (dell'esercizio), escludendo le registrazioni di chiusura."""
    year_start = f"{year}-01-01"
    has_opening = await db.entries.find_one({"company_id": company_id, "source": "apertura", "year": year})
    if has_opening:
        sp = await balances(db, company_id, year_start, date_to, exclude_sources=("chiusura",))
    else:
        sp = await balances(db, company_id, None, date_to, exclude_sources=("chiusura", "apertura"))
    ce = await balances(db, company_id, year_start, date_to, exclude_sources=("chiusura",))
    return sp, ce


async def financial_statements(db, company_id: str, year: int, date_to: str | None = None,
                               cost_center_id: str | None = None) -> dict:
    accounts = await chart_of(db, company_id)
    date_to = date_to or f"{year}-12-31"
    sp_bal, ce_bal = await _statement_balances(db, company_id, year, date_to)
    sp_prev, ce_prev = await _statement_balances(db, company_id, year - 1, f"{year - 1}-12-31")
    out = build_statements(accounts, sp_bal, ce_bal, sp_prev, ce_prev)
    by_cc = None
    if cost_center_id is not None:
        by_cc = await cost_center_report(db, company_id, f"{year}-01-01", date_to)
    out.update({"year": year, "date_to": date_to, "centri_di_costo": by_cc})
    return out


def build_statements(accounts: dict, sp_bal: dict, ce_bal: dict, sp_prev: dict, ce_prev: dict,
                     extra_sp: dict | None = None, extra_sp_prev: dict | None = None) -> dict:
    """Stato patrimoniale e conto economico CEE dai saldi per conto. extra_sp: importi aggiuntivi per voce
    (usati dal consolidato per le differenze di consolidamento)."""

    def ce_amounts(bal):
        voce = defaultdict(int)
        details = defaultdict(list)
        ricavi = costi = 0
        for code, b in bal.items():
            acc = accounts.get(code)
            if not acc or acc["kind"] not in {"costo", "ricavo"} or not acc.get("cee"):
                continue
            amount = -b["saldo"] if acc["kind"] == "ricavo" else b["saldo"]
            if not amount:
                continue
            voce[acc["cee"]] += amount
            details[acc["cee"]].append({"code": code, "name": acc["name"], "amount": amount})
            if acc["kind"] == "ricavo":
                ricavi += amount
            else:
                costi += amount
        return voce, details, ricavi - costi

    def sp_amounts(bal, result, extra):
        voce = defaultdict(int)
        details = defaultdict(list)
        for code, b in bal.items():
            acc = accounts.get(code)
            if not acc or acc["kind"] not in {"attivo", "passivo"} or not acc.get("cee"):
                continue
            s = b["saldo"]
            if not s:
                continue
            if acc["kind"] == "attivo":
                target, amount = (acc["cee_neg"], -s) if s < 0 and acc.get("cee_neg") else (acc["cee"], s)
            else:
                target, amount = (acc["cee_neg"], s) if s > 0 and acc.get("cee_neg") else (acc["cee"], -s)
            voce[target] += amount
            details[target].append({"code": code, "name": acc["name"], "amount": amount})
        voce["SP.P.A.IX"] += result
        if result:
            details["SP.P.A.IX"].append({"code": "", "name": "Risultato dell'esercizio in corso", "amount": result})
        for target, (label, amount) in (extra or {}).items():
            if amount:
                voce[target] += amount
                details[target].append({"code": "", "name": label, "amount": amount})
        return voce, details

    ce_voce, ce_det, result = ce_amounts(ce_bal)
    ce_voce_p, _, result_p = ce_amounts(ce_prev)
    sp_voce, sp_det = sp_amounts(sp_bal, result, extra_sp)
    sp_voce_p, _ = sp_amounts(sp_prev, result_p, extra_sp_prev)

    def under(c: str, code: str) -> bool:
        return c == code or c.startswith(code + ".") or (len(c) == len(code) + 1 and c.startswith(code) and c[-1] in "abc")

    def tree(schema, voce, voce_p, details, with_sign=False):
        rows = []
        for item in schema:
            code, label, level = item[0], item[1], item[2]
            amount = sum(v for c, v in voce.items() if under(c, code))
            prev = sum(v for c, v in voce_p.items() if under(c, code))
            row = {"code": code, "label": label, "level": level, "amount": amount, "previous": prev,
                   "accounts": sorted(details.get(code, []), key=lambda d: d["code"])}
            if with_sign:
                row["sign"] = item[3]
            if amount or prev or level == 0:
                rows.append(row)
        return rows

    attivo = tree(SP_ATTIVO, sp_voce, sp_voce_p, sp_det)
    passivo = tree(SP_PASSIVO, sp_voce, sp_voce_p, sp_det)
    tot_att = sum(v for c, v in sp_voce.items() if c.startswith("SP.A."))
    tot_pas = sum(v for c, v in sp_voce.items() if c.startswith("SP.P."))
    ce_rows = tree(CE_SCHEMA, ce_voce, ce_voce_p, ce_det, with_sign=True)

    def total(prefixes, voce):
        return sum(v for c, v in voce.items() if any(c.startswith(p) for p in prefixes))
    a_val, b_cost = total(["CE.A"], ce_voce), total(["CE.B"], ce_voce)
    c_fin = total(["CE.C.16"], ce_voce) - total(["CE.C.17"], ce_voce)
    taxes = total(["CE.20"], ce_voce)
    summary = {"valore_produzione": a_val, "costi_produzione": b_cost, "differenza": a_val - b_cost,
               "proventi_oneri_finanziari": c_fin, "risultato_ante_imposte": a_val - b_cost + c_fin,
               "imposte": taxes, "utile": result, "utile_precedente": result_p}
    return {"attivo": attivo, "passivo": passivo, "totale_attivo": tot_att, "totale_passivo": tot_pas,
            "quadra": tot_att == tot_pas, "conto_economico": ce_rows, "sintesi": summary,
            "voci": {"sp": dict(sp_voce), "ce": dict(ce_voce), "sp_prev": dict(sp_voce_p), "ce_prev": dict(ce_voce_p)}}


async def cost_center_report(db, company_id: str, date_from: str, date_to: str) -> dict:
    accounts = await chart_of(db, company_id)
    centers = {c["id"]: c["name"] for c in await db.cost_centers.find({"company_id": company_id}, {"_id": 0}).to_list(200)}
    data: dict[str, dict] = defaultdict(lambda: {"ricavi": 0, "costi": 0})
    async for e in db.entries.find({"company_id": company_id, "date": {"$gte": date_from, "$lte": date_to},
                                    "source": {"$ne": "chiusura"}}, {"lines": 1}):
        for l in e["lines"]:
            acc = accounts.get(l["account"])
            if not acc or acc["kind"] not in {"costo", "ricavo"}:
                continue
            key = l.get("cost_center_id") or ""
            if acc["kind"] == "ricavo":
                data[key]["ricavi"] += l["avere"] - l["dare"]
            else:
                data[key]["costi"] += l["dare"] - l["avere"]
    rows = [{"id": k or None, "name": centers.get(k, "Senza centro di costo") if k else "Senza centro di costo",
             "ricavi": v["ricavi"], "costi": v["costi"], "margine": v["ricavi"] - v["costi"]} for k, v in data.items()]
    rows.sort(key=lambda r: (r["id"] is None, -r["margine"]))
    return {"rows": rows}


# ------------------------------------------------------------------ registri IVA

async def vat_registers(db, company_id: str, direction: str, date_from: str, date_to: str) -> dict:
    year_start = f"{date_from[:4]}-01-01"
    all_year = await db.invoices.find({"company_id": company_id, "direction": direction}, {"_id": 0}).to_list(100000)
    reg_date = lambda i: i.get("registration_date") or i["date"]
    in_year = sorted([i for i in all_year if year_start <= reg_date(i) <= f"{date_from[:4]}-12-31"],
                     key=lambda i: (reg_date(i), i.get("created_at", "")))
    protocol = {i["id"]: n for n, i in enumerate(in_year, start=1)}
    rows = []
    by_rate: dict[str, dict] = defaultdict(lambda: {"taxable": 0, "vat": 0})
    for inv in in_year:
        if not date_from <= reg_date(inv) <= date_to:
            continue
        lines = inv.get("vat_breakdown") or [{"rate": 22.0, "nature": "", "taxable_cents": inv.get("taxable_cents") or 0,
                                              "vat_cents": inv.get("vat_cents") or 0}]
        for b in lines:
            label = f"{b['rate']:g}%" if b["rate"] else f"Esente/non imponibile {b.get('nature') or ''}".strip()
            if inv.get("split_payment") and direction == "attiva":
                label += " (split payment)"
            by_rate[label]["taxable"] += b["taxable_cents"]
            by_rate[label]["vat"] += 0 if (inv.get("split_payment") and direction == "attiva") else b["vat_cents"]
        rows.append({
            "protocol": protocol[inv["id"]], "registration_date": reg_date(inv), "date": inv["date"], "number": inv["number"],
            "doc_type": inv.get("doc_type"), "party": inv.get("counterparty_name"), "vat_number": inv.get("counterparty_vat"),
            "taxable_cents": inv.get("taxable_cents") or 0, "vat_cents": inv.get("vat_cents") or 0, "total_cents": inv["total_cents"],
            "withholding_cents": inv.get("withholding_cents") or 0, "split_payment": inv.get("split_payment", False),
            "rates": [{"rate": b["rate"], "nature": b.get("nature"), "taxable_cents": b["taxable_cents"], "vat_cents": b["vat_cents"]} for b in lines],
        })
    summary = [{"label": k, "taxable_cents": v["taxable"], "vat_cents": v["vat"]} for k, v in sorted(by_rate.items())]
    return {"direction": direction, "rows": rows, "summary": summary,
            "totals": {"taxable_cents": sum(r["taxable_cents"] for r in rows), "vat_cents": sum(s["vat_cents"] for s in summary),
                       "total_cents": sum(r["total_cents"] for r in rows)}}


# ------------------------------------------------------------------ controlli di quadratura

def _eur(cents: int) -> str:
    return f"{cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


async def checks(db, company_id: str) -> list[dict]:
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    accounts = await chart_of(db, company_id)
    by_key = {a["key"]: a for a in accounts.values() if a.get("key")}
    out = []
    unbalanced = 0
    async for e in db.entries.find({"company_id": company_id}, {"lines": 1}):
        if sum(l["dare"] for l in e["lines"]) != sum(l["avere"] for l in e["lines"]):
            unbalanced += 1
    out.append({"id": "quadratura", "ok": unbalanced == 0, "title": "Dare e avere quadrano",
                "detail": "Tutte le registrazioni sono in pareggio." if not unbalanced else f"{unbalanced} registrazioni non quadrano."})

    bal = await balances(db, company_id)
    for bank in await db.bank_accounts.find({"company_id": company_id, "status": {"$ne": "scollegato"}}, {"_id": 0}).to_list(100):
        acc = by_key.get(f"banca:{bank['id']}")
        book = bal.get(acc["code"], {}).get("saldo", 0) if acc else 0
        pending = 0
        async for t in db.transactions.find({"account_id": bank["id"], "status": "da_riconciliare"}, {"amount_cents": 1}):
            pending += t["amount_cents"]
        diff = bank.get("balance_cents", 0) - book
        out.append({"id": f"banca:{bank['id']}", "ok": diff == pending, "title": f"Quadratura {bank['bank_name']} {bank['iban_masked']}",
                    "detail": (f"Saldo banca {_eur(bank.get('balance_cents', 0))} · in contabilità {_eur(book)} · "
                               f"movimenti ancora da riconciliare {_eur(pending)}"
                               + ("" if diff == pending else f" · differenza non spiegata {_eur(diff - pending)} (saldi iniziali?)")),
                    "link": "/riconciliazione" if pending else None})
    trans = by_key.get("transitorio")
    t_bal = bal.get(trans["code"], {}).get("saldo", 0) if trans else 0
    out.append({"id": "transitorio", "ok": t_bal == 0, "title": "Movimenti da attribuire",
                "detail": "Nessun importo in sospeso." if not t_bal else
                f"Sul conto {trans['code']} restano {_eur(abs(t_bal))} da attribuire al conto giusto (es. incassi POS, spese senza fattura).", "link": f"/contabilita/piano-conti?conto={trans['code']}" if t_bal else None})
    pending_all = await db.transactions.count_documents({"company_id": company_id, "status": "da_riconciliare"})
    out.append({"id": "da_riconciliare", "ok": pending_all == 0, "title": "Movimenti bancari non ancora registrati",
                "detail": f"{pending_all} movimenti da riconciliare: finché non sono sistemati non entrano in contabilità." if pending_all
                else "Tutti i movimenti sono registrati.", "link": "/riconciliazione" if pending_all else None})
    no_account = await db.supplier_accounts.count_documents({"company_id": company_id})
    generic = by_key.get("costi_generici")
    g_bal = bal.get(generic["code"], {}).get("saldo", 0) if generic else 0
    out.append({"id": "costi_generici", "ok": g_bal == 0, "title": "Fatture di acquisto su conto generico",
                "detail": f"{_eur(g_bal)} di costi sono su \"{generic['name']}\": indica il conto giusto dalle fatture (il programma lo ricorda per fornitore). {no_account} fornitori già impostati."
                if g_bal else "Nessun costo sul conto generico.", "link": "/fatture" if g_bal else None})
    lock = company.get("accounting_lock_date")
    out.append({"id": "blocco", "ok": True, "title": "Periodo chiuso",
                "detail": f"Registrazioni bloccate fino al {parse_date(lock).strftime('%d/%m/%Y')}." if lock else "Nessun periodo chiuso."})
    return out


async def open_items_check(db, company_id: str) -> dict:
    """Confronto tra partitario clienti/fornitori e fatture aperte (devono coincidere)."""
    inv_open = defaultdict(int)
    async for i in db.invoices.find({"company_id": company_id, "status": {"$in": ["aperta", "parziale"]}}, {"_id": 0}):
        inv_open[i["direction"]] += payable(i) - i.get("paid_cents", 0)
    return {"clienti_da_fatture": inv_open["attiva"], "fornitori_da_fatture": inv_open["passiva"], "al": today().isoformat()}
