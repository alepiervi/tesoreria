"""Funzioni di gruppo: bilancio consolidato, liquidità di gruppo (cash pooling), confronto tra aziende."""
from collections import defaultdict

from ..utils import today
from .accounting_reports import _statement_balances, build_statements, chart_of
from .invoices import norm_vat

BANK_CODE = "20.05.10"


# ------------------------------------------------------------------ consolidato

async def _intercompany_invoice_lines(db, company_id: str, date_from: str, date_to: str, accounts: dict) -> dict:
    """Costi e ricavi registrati da fatture tra aziende del gruppo, per conto (da eliminare nel consolidato)."""
    ids = [i["id"] async for i in db.invoices.find({"company_id": company_id, "intercompany_company_id": {"$ne": None}}, {"id": 1})]
    out: dict[str, int] = defaultdict(int)
    if not ids:
        return out
    async for e in db.entries.find({"company_id": company_id, "source_key": {"$in": [f"inv:{i}" for i in ids]},
                                    "date": {"$gte": date_from, "$lte": date_to}}, {"lines": 1}):
        for l in e["lines"]:
            acc = accounts.get(l["account"])
            if acc and acc["kind"] in {"costo", "ricavo"}:
                out[l["account"]] += l["dare"] - l["avere"]
    return out


async def consolidated(db, companies: list[dict], year: int) -> dict:
    """Bilancio aggregato del gruppo con eliminazione di crediti, debiti, costi e ricavi tra le aziende.

    Si eliminano: crediti e debiti verso società del gruppo (conti 20.02.02 e 40.03.01) e i costi e ricavi delle fatture
    tra aziende. Non si eliminano le partecipazioni contro il patrimonio delle controllate né gli utili interni
    sulle rimanenze o sui cespiti: per il consolidato ufficiale servono i dati del commercialista.
    """
    merged_accounts: dict[str, dict] = {}
    totals = {k: defaultdict(lambda: {"dare": 0, "avere": 0, "saldo": 0}) for k in ("sp", "ce", "sp_p", "ce_p")}
    per_company = []
    elim = {"crediti": 0, "debiti": 0, "ricavi": 0, "costi": 0, "crediti_p": 0, "debiti_p": 0, "ricavi_p": 0, "costi_p": 0}
    group_vats = {norm_vat(c.get("vat_number")): c for c in companies if c.get("vat_number")}
    pair_check: dict[tuple, dict] = {}

    for c in companies:
        accounts = await chart_of(db, c["id"])
        bank_codes = {code for code, a in accounts.items() if (a.get("key") or "").startswith("banca:")}
        key_code = {a["key"]: code for code, a in accounts.items() if a.get("key")}
        for code, a in accounts.items():
            if code in bank_codes:
                merged_accounts.setdefault(BANK_CODE, {**a, "code": BANK_CODE, "name": "Banche (tutte le aziende)", "key": "banche"})
            else:
                merged_accounts.setdefault(code, a)
        sp, ce = await _statement_balances(db, c["id"], year, f"{year}-12-31")
        sp_p, ce_p = await _statement_balances(db, c["id"], year - 1, f"{year - 1}-12-31")
        ic_lines = await _intercompany_invoice_lines(db, c["id"], f"{year}-01-01", f"{year}-12-31", accounts)
        ic_lines_p = await _intercompany_invoice_lines(db, c["id"], f"{year - 1}-01-01", f"{year - 1}-12-31", accounts)
        gc, gd = key_code.get("gruppo_crediti"), key_code.get("gruppo_debiti")

        for bucket, src, ic, suffix in (("sp", sp, None, ""), ("ce", ce, ic_lines, ""), ("sp_p", sp_p, None, "_p"), ("ce_p", ce_p, ic_lines_p, "_p")):
            for code, b in src.items():
                target = BANK_CODE if code in bank_codes else code
                saldo = b["saldo"]
                if bucket.startswith("sp") and code == gc:
                    elim["crediti" + suffix] += saldo
                    continue
                if bucket.startswith("sp") and code == gd:
                    elim["debiti" + suffix] += -saldo
                    continue
                if ic and code in ic:
                    removed = ic[code]
                    acc = accounts.get(code, {})
                    if acc.get("kind") == "ricavo":
                        elim["ricavi" + suffix] += -removed
                    else:
                        elim["costi" + suffix] += removed
                    saldo -= removed
                t = totals[bucket][target]
                t["saldo"] += saldo
                t["dare"] += max(saldo, 0)
                t["avere"] += max(-saldo, 0)

        # posizioni reciproche (per controllare che coincidano)
        for code in (gc, gd):
            if not code:
                continue
            async for e in db.entries.find({"company_id": c["id"], "lines.account": code, "date": {"$lte": f"{year}-12-31"},
                                            "source": {"$ne": "chiusura"}}, {"lines": 1}):
                for l in e["lines"]:
                    if l["account"] != code:
                        continue
                    other = group_vats.get(l.get("party_key") or "")
                    if not other:
                        continue
                    a, b = sorted([c["id"], other["id"]])
                    p = pair_check.setdefault((a, b), {"a": a, "b": b, "a_name": "", "b_name": "", "a_vs_b": 0, "b_vs_a": 0})
                    amount = l["dare"] - l["avere"]  # credito netto di c verso other (negativo se è un debito)
                    if c["id"] == a:
                        p["a_vs_b"] += amount
                    else:
                        p["b_vs_a"] += amount
        st = build_statements(accounts, sp, ce, sp_p, ce_p)
        per_company.append({"id": c["id"], "name": c["name"], "totale_attivo": st["totale_attivo"],
                            "utile": st["sintesi"]["utile"], "valore_produzione": st["sintesi"]["valore_produzione"],
                            "quadra": st["quadra"]})

    names = {c["id"]: c["name"] for c in companies}
    mismatches = []
    for p in pair_check.values():
        diff = p["a_vs_b"] + p["b_vs_a"]  # il credito di A verso B deve essere uguale al debito di B verso A
        if p["a_vs_b"] or p["b_vs_a"]:
            mismatches.append({"a": names[p["a"]], "b": names[p["b"]], "a_vs_b_cents": p["a_vs_b"], "b_vs_a_cents": p["b_vs_a"],
                               "difference_cents": diff})

    # differenza di consolidamento: rende il bilancio coerente quando le posizioni reciproche non coincidono
    diff = -elim["crediti"] + elim["debiti"] + (elim["ricavi"] - elim["costi"])
    diff_p = -elim["crediti_p"] + elim["debiti_p"] + (elim["ricavi_p"] - elim["costi_p"])
    extra = {"SP.P.A.VI": ("Differenza da consolidamento (posizioni tra aziende non coincidenti)", diff)}
    extra_p = {"SP.P.A.VI": ("Differenza da consolidamento", diff_p)}
    st = build_statements(merged_accounts, totals["sp"], totals["ce"], totals["sp_p"], totals["ce_p"], extra, extra_p)
    return {**st, "year": year, "companies": per_company, "eliminations": {
        "crediti_gruppo_cents": elim["crediti"], "debiti_gruppo_cents": elim["debiti"],
        "ricavi_gruppo_cents": elim["ricavi"], "costi_gruppo_cents": elim["costi"], "differenza_cents": diff},
        "mismatches": sorted(mismatches, key=lambda m: -abs(m["difference_cents"])),
        "aggregated_result_cents": sum(c["utile"] for c in per_company),
        "note": "Consolidato gestionale: somma dei bilanci con eliminazione delle operazioni tra le aziende del gruppo. "
                "Non elimina le partecipazioni né gli utili interni su magazzino e cespiti."}


# ------------------------------------------------------------------ liquidità di gruppo

async def group_liquidity(db, companies: list[dict], min_buffer: dict[str, int] | None = None, weeks: int = 13) -> dict:
    """Liquidità per azienda, punto più basso previsto e proposte di trasferimento tra le aziende."""
    from .forecast import weekly_forecast
    rows = []
    for c in companies:
        fc = await weekly_forecast(db, [c["id"]], weeks=weeks)
        banks = await db.bank_accounts.find({"company_id": c["id"], "status": {"$ne": "scollegato"}}, {"_id": 0}).to_list(50)
        buffer = (min_buffer or {}).get(c["id"], c.get("cash_buffer_cents", 0) or 0)
        low = fc["lowest"]["balance_cents"]
        rows.append({"id": c["id"], "name": c["name"], "balance_cents": fc["opening_balance_cents"],
                     "lowest_cents": low, "lowest_week_start": fc["lowest"].get("start"),
                     "end_cents": fc["weeks"][-1]["balance_end_cents"] if fc["weeks"] else fc["opening_balance_cents"],
                     "credit_available_cents": fc["credit_available_cents"], "buffer_cents": buffer,
                     # quanto può dare senza scendere sotto la riserva nel punto più basso, quanto le manca
                     "surplus_cents": max(0, min(fc["opening_balance_cents"], low) - buffer),
                     "need_cents": max(0, buffer - low),
                     "banks": [{"id": b["id"], "label": f"{b['bank_name']} {b.get('label', '')}".strip(), "iban": b.get("iban", ""),
                                "balance_cents": b.get("balance_cents", 0)} for b in banks]})
    proposals = []
    givers = sorted([r for r in rows if r["surplus_cents"] > 0], key=lambda r: -r["surplus_cents"])
    surplus = {r["id"]: r["surplus_cents"] for r in givers}
    for r in sorted([r for r in rows if r["need_cents"] > 0], key=lambda r: -r["need_cents"]):
        need = r["need_cents"]
        for g in givers:
            if need <= 0:
                break
            avail = surplus[g["id"]]
            if avail <= 0:
                continue
            amount = min(avail, need)
            amount = -(-amount // 100_000) * 100_000  # arrotondato per eccesso ai 1.000 €
            amount = min(amount, avail)
            surplus[g["id"]] -= amount
            need -= amount
            proposals.append({"from_id": g["id"], "from_name": g["name"], "to_id": r["id"], "to_name": r["name"],
                              "amount_cents": amount, "by_date": r["lowest_week_start"],
                              "reason": f"{r['name']} scende a {r['lowest_cents'] / 100:,.0f} € (riserva minima {r['buffer_cents'] / 100:,.0f} €)".replace(",", ".")})
        if need > 0:
            r["uncovered_cents"] = need
    total = sum(r["balance_cents"] for r in rows)
    return {"companies": rows, "proposals": proposals, "total_cents": total,
            "total_lowest_cents": sum(r["lowest_cents"] for r in rows), "weeks": weeks}


async def intercompany_balances(db, companies: list[dict]) -> list[dict]:
    """Crediti e debiti tra le aziende dalla contabilità (finanziamenti tra società e fatture non pagate)."""
    group_vats = {norm_vat(c.get("vat_number")): c for c in companies if c.get("vat_number")}
    out = []
    t = today().isoformat()
    for c in companies:
        accounts = await chart_of(db, c["id"])
        gc = next((code for code, a in accounts.items() if a.get("key") == "gruppo_crediti"), None)
        if not gc:
            continue
        per: dict[str, int] = defaultdict(int)
        async for e in db.entries.find({"company_id": c["id"], "lines.account": gc, "date": {"$lte": t}, "source": {"$ne": "chiusura"}},
                                       {"lines": 1}):
            for l in e["lines"]:
                if l["account"] == gc and l.get("party_key") in group_vats:
                    per[l["party_key"]] += l["dare"] - l["avere"]
        for vat, amount in per.items():
            if amount:
                out.append({"creditor": c["name"], "creditor_id": c["id"], "debtor": group_vats[vat]["name"],
                            "debtor_id": group_vats[vat]["id"], "amount_cents": amount})
    return sorted(out, key=lambda r: -r["amount_cents"])


# ------------------------------------------------------------------ confronto

async def compare(db, companies: list[dict], year: int) -> dict:
    from .analysis import ratios
    rows = []
    for c in companies:
        r = await ratios(db, c, year)
        v = r["values"]
        personale = v["personale"]
        banks = await db.bank_accounts.find({"company_id": c["id"], "status": {"$ne": "scollegato"}}, {"balance_cents": 1}).to_list(50)
        open_rec = 0
        async for d in db.deadlines.find({"company_id": c["id"], "kind": "incasso", "status": "aperta", "due_date": {"$lt": today().isoformat()}},
                                         {"amount_cents": 1}):
            open_rec += d["amount_cents"]
        rows.append({"id": c["id"], "name": c["name"], "ricavi": v["ricavi"], "ebitda": v["ebitda"], "utile": v["utile"],
                     "personale": personale, "personale_su_ricavi": personale / v["ricavi"] if v["ricavi"] else None,
                     "liquidita": sum(b.get("balance_cents", 0) for b in banks), "pfn": v["pfn"], "pn": v["pn"],
                     "crediti_scaduti": open_rec,
                     "indici": {i["id"]: {"value": i["value"], "status": i["status"], "format": i["format"]} for i in r["items"]}})
    labels = {i["id"]: i["label"] for i in (await ratios(db, companies[0], year))["items"]} if companies else {}
    return {"year": year, "rows": rows, "labels": labels,
            "annualized": bool(companies) and year == today().year}
