"""Operazioni di fine periodo: liquidazioni IVA, cespiti e ammortamenti, ratei e risconti,
chiusura e riapertura dei conti, modelli di registrazione."""
from datetime import timedelta

from ..utils import new_id, now_iso, parse_date
from .accounting import AccountingError, Lines, balances, is_locked, load_chart, upsert_auto_entry, validate_lines

# ------------------------------------------------------------------ cespiti

ASSET_CATEGORIES = {
    "software": ("Software e licenze", 33.33, "imm_software", "fondo_software", "amm_immateriali"),
    "fabbricati": ("Fabbricati", 3.0, "imm_fabbricati", "fondo_fabbricati", "amm_materiali"),
    "impianti": ("Impianti e macchinari", 15.0, "imm_impianti", "fondo_impianti", "amm_materiali"),
    "attrezzature": ("Attrezzature", 15.0, "imm_attrezzature", "fondo_attrezzature", "amm_materiali"),
    "mobili": ("Mobili e arredi", 12.0, "imm_mobili", "fondo_mobili", "amm_materiali"),
    "elettroniche": ("Macchine d'ufficio elettroniche", 20.0, "imm_elettroniche", "fondo_elettroniche", "amm_materiali"),
    "automezzi": ("Automezzi", 20.0, "imm_automezzi", "fondo_automezzi", "amm_materiali"),
}


def asset_schedule(asset: dict, until_year: int | None = None) -> list[dict]:
    """Piano di ammortamento per anno. Il primo anno, se richiesto, la quota è dimezzata (prassi fiscale)."""
    cost = asset["cost_cents"]
    rate = float(asset["rate"])
    start = int(asset["purchase_date"][:4])
    acc = int(asset.get("accumulated_before_cents") or 0)
    from_year = int(asset.get("accumulated_before_year") or start - 1) + 1
    disposed = int(asset["disposed_date"][:4]) if asset.get("disposed_date") else None
    rows = []
    year = from_year
    while acc < cost and year <= (until_year or start + 200):
        if disposed and year > disposed:
            break
        quota = round(cost * rate / 100)
        if year == start and asset.get("first_year_half", True):
            quota = round(quota / 2)
        quota = min(quota, cost - acc)
        acc += quota
        rows.append({"year": year, "quota_cents": quota, "fund_cents": acc, "residual_cents": cost - acc})
        year += 1
    return rows


def asset_summary(asset: dict, year: int) -> dict:
    rows = asset_schedule(asset, year)
    this = next((r for r in rows if r["year"] == year), None)
    fund = rows[-1]["fund_cents"] if rows else int(asset.get("accumulated_before_cents") or 0)
    return {**{k: v for k, v in asset.items() if k != "_id"}, "category_label": ASSET_CATEGORIES[asset["category"]][0],
            "quota_cents": this["quota_cents"] if this else 0, "fund_cents": fund, "residual_cents": asset["cost_cents"] - fund}


async def post_depreciation(db, company: dict, year: int) -> dict:
    chart = await load_chart(db, company)
    assets = await db.assets.find({"company_id": company["id"]}, {"_id": 0}).to_list(2000)
    L = Lines()
    total = 0
    for a in assets:
        if int(a["purchase_date"][:4]) > year:
            continue
        row = next((r for r in asset_schedule(a, year) if r["year"] == year), None)
        if not row or not row["quota_cents"]:
            continue
        _, _, _, fund_key, exp_key = ASSET_CATEGORIES[a["category"]]
        L.add(chart.k(exp_key), row["quota_cents"], "D", cost_center_id=a.get("cost_center_id"), description=f"Ammortamento {a['name']}")
        L.add(chart.k(fund_key), row["quota_cents"], "A", description=a["name"])
        total += row["quota_cents"]
    entry = None
    if L.items:
        entry = {"date": f"{year}-12-31", "causale": "AMM", "description": f"Ammortamenti dell'esercizio {year}",
                 "doc_number": None, "doc_date": None, "lines": L.items}
        validate_lines(entry["lines"], chart)
    result = await upsert_auto_entry(db, company, f"amm:{year}", entry, source="rettifica")
    if result == "bloccata":
        raise AccountingError(f"Il {year} è chiuso: gli ammortamenti non si possono più modificare.")
    return {"result": result, "total_cents": total, "assets": len([a for a in assets if int(a["purchase_date"][:4]) <= year])}


# ------------------------------------------------------------------ ratei e risconti

ACCRUAL_KINDS = {
    "risconto_attivo": ("Risconto attivo", "risconti_attivi", "costo"),
    "rateo_passivo": ("Rateo passivo", "ratei_passivi", "costo"),
    "risconto_passivo": ("Risconto passivo", "risconti_passivi", "ricavo"),
    "rateo_attivo": ("Rateo attivo", "ratei_attivi", "ricavo"),
}


def accrual_amount(kind: str, amount: int, start: str, end: str, year_end: str) -> int:
    s, e, y = parse_date(start), parse_date(end), parse_date(year_end)
    days = (e - s).days + 1
    if days <= 0:
        raise AccountingError("La data di fine deve essere successiva a quella di inizio.")
    before = max(0, min((y - s).days + 1, days))  # giorni che appartengono all'esercizio
    after = days - before
    if kind.startswith("risconto"):
        return round(amount * after / days)  # quota rinviata all'anno dopo
    return round(amount * before / days)  # quota maturata ma non ancora registrata


async def post_accrual(db, company: dict, acc: dict) -> None:
    chart = await load_chart(db, company)
    label, bs_key, _ = ACCRUAL_KINDS[acc["kind"]]
    pl = acc["account_code"]
    if pl not in chart.by_code:
        raise AccountingError("Conto di costo o ricavo non valido.")
    amt = acc["portion_cents"]
    L, R = Lines(), Lines()
    bs = chart.k(bs_key)
    if acc["kind"] in {"risconto_attivo", "rateo_attivo"}:
        L.add(bs, amt, "D")
        L.add(pl, amt, "A", cost_center_id=acc.get("cost_center_id"))
    else:
        L.add(pl, amt, "D", cost_center_id=acc.get("cost_center_id"))
        L.add(bs, amt, "A")
    for l in L.items:
        R.add(l["account"], l["dare"] or -l["avere"], "A", cost_center_id=l.get("cost_center_id"))
    y = acc["year_end"]
    nxt = (parse_date(y) + timedelta(days=1)).isoformat()
    r1 = await upsert_auto_entry(db, company, f"rat:{acc['id']}", {
        "date": y, "causale": "RAT", "description": f"{label}: {acc['description']}", "doc_number": None, "doc_date": None,
        "lines": L.items}, source="rettifica")
    if r1 == "bloccata":
        raise AccountingError("L'esercizio è chiuso.")
    await upsert_auto_entry(db, company, f"rat:{acc['id']}:storno", {
        "date": nxt, "causale": "STO", "description": f"Storno {label.lower()}: {acc['description']}", "doc_number": None,
        "doc_date": None, "lines": R.items}, source="rettifica")


# ------------------------------------------------------------------ liquidazione IVA

async def post_vat_settlements(db, company: dict, year: int) -> int:
    """Per ogni periodo chiuso: giroconto di IVA vendite e IVA acquisti a Erario c/IVA."""
    from .vat import compute
    chart = await load_chart(db, company)
    data = await compute(db, company, year)
    done = 0
    for p in data["periods"]:
        if p["state"] != "chiuso" or (not p["sales_vat_cents"] and not p["purchases_vat_cents"]):
            continue
        L = Lines()
        L.add(chart.k("iva_debito"), p["sales_vat_cents"], "D")
        L.add(chart.k("iva_credito"), p["purchases_vat_cents"], "A")
        L.add(chart.k("erario_iva"), p["sales_vat_cents"] - p["purchases_vat_cents"], "A")
        entry = {"date": p["end"], "causale": "GEN", "description": f"Liquidazione IVA {p['label']}", "doc_number": None,
                 "doc_date": None, "lines": [l for l in L.items if l["dare"] or l["avere"]]}
        if len(entry["lines"]) < 2:
            continue
        if await upsert_auto_entry(db, company, f"liqiva:{p['key']}", entry, source="rettifica") in {"creata", "aggiornata"}:
            done += 1
    return done


# ------------------------------------------------------------------ chiusura e apertura dei conti

async def close_year(db, company: dict, year: int, user: dict) -> dict:
    from .accounting_reports import _statement_balances
    if company.get("accounting_lock_date") and company["accounting_lock_date"] >= f"{year}-12-31":
        raise AccountingError(f"Il {year} è già chiuso.")
    prev_lock = company.get("accounting_lock_date") or ""
    if prev_lock < f"{year - 1}-12-31" and await db.entries.find_one({"company_id": company["id"], "year": year - 1,
                                                                       "source": {"$ne": "apertura"}}):
        raise AccountingError(f"Prima va chiuso il {year - 1}.")
    chart = await load_chart(db, company)
    sp_bal, ce_bal = await _statement_balances(db, company["id"], year, f"{year}-12-31")
    unbalanced = sum(b["saldo"] for b in sp_bal.values())
    if unbalanced:
        raise AccountingError("Il bilancio di verifica non quadra: correggi prima le registrazioni.")
    y_end = f"{year}-12-31"
    ce_code, utile_code = chart.k("ce_epilogo"), chart.k("utile_esercizio")

    # 1. epilogo dei costi e ricavi a Conto economico
    L1 = Lines()
    result = 0
    for code, b in sorted(ce_bal.items()):
        acc = chart.by_code.get(code)
        if not acc or acc["kind"] not in {"costo", "ricavo"} or not b["saldo"]:
            continue
        L1.add(code, b["saldo"], "A")  # azzera il conto
        L1.add(ce_code, b["saldo"], "D")
        result -= b["saldo"]  # ricavi (saldo avere, negativo) aumentano l'utile
    # 2. risultato a Utile (perdita) d'esercizio
    L2 = Lines()
    L2.add(ce_code, result, "D")
    L2.add(utile_code, result, "A")
    # 3. chiusura dei conti patrimoniali
    L3 = Lines()
    sp_after = {c: dict(b) for c, b in sp_bal.items()}
    sp_after.setdefault(utile_code, {"saldo": 0})
    sp_after[utile_code]["saldo"] = sp_after[utile_code].get("saldo", 0) - result
    party_bal = await _party_balances(db, company["id"], year, y_end)
    for code, b in sorted(sp_after.items()):
        acc = chart.by_code.get(code)
        if not acc or acc["kind"] not in {"attivo", "passivo"} or not b.get("saldo"):
            continue
        if acc.get("party") and party_bal.get(code):
            # i conti clienti/fornitori si chiudono controparte per controparte, così il partitario riparte giusto
            for (pkey, pname), ps in party_bal[code].items():
                L3.add(code, ps, "A", party=(pkey, pname) if pkey else None)
        else:
            L3.add(code, b["saldo"], "A")
        L3.add(chart.k("sp_chiusura"), b["saldo"], "D")
    # 4. riapertura al 1° gennaio
    L4 = Lines()
    for l in L3.items:
        L4.add(chart.k("sp_apertura") if l["account"] == chart.k("sp_chiusura") else l["account"],
               l["avere"] or -l["dare"], "D", party=(l["party_key"], l["party_name"]) if l.get("party_key") else None)

    def merge(lines):  # le righe sul conto di chiusura si sommano in una
        out, tech = [], {}
        for l in lines:
            if l["account"].startswith("99."):
                t = tech.setdefault(l["account"], {**l, "dare": 0, "avere": 0})
                t["dare"] += l["dare"]
                t["avere"] += l["avere"]
            else:
                out.append(l)
        for t in tech.values():
            net = t["dare"] - t["avere"]
            if net:
                out.append({**t, "dare": max(net, 0), "avere": max(-net, 0)})
        return out

    nxt = f"{year + 1}-01-01"
    entries = [
        (f"close:{year}:ce", y_end, "CHI", f"Chiusura dei conti economici {year}", merge(L1.items), "chiusura", year),
        (f"close:{year}:utile", y_end, "CHI", f"Rilevazione del risultato d'esercizio {year}", L2.items, "chiusura", year),
        (f"close:{year}:sp", y_end, "CHI", f"Chiusura dei conti patrimoniali {year}", merge(L3.items), "chiusura", year),
        (f"open:{year + 1}", nxt, "APE", f"Riapertura dei conti al 1° gennaio {year + 1}", merge(L4.items), "apertura", year + 1),
    ]
    for key, d, causale, desc, lines, source, y in entries:
        if len(lines) < 2:
            continue
        validate_lines(lines, chart)
        await db.entries.delete_many({"company_id": company["id"], "source_key": key})
        await db.entries.insert_one({"id": new_id(), "company_id": company["id"], "date": d, "year": y, "causale": causale,
                                     "description": desc, "doc_number": None, "doc_date": None, "lines": lines,
                                     "source": source, "source_key": key, "created_at": now_iso(), "created_by": user["id"],
                                     "updated_at": now_iso()})
    await db.companies.update_one({"id": company["id"]}, {"$set": {"accounting_lock_date": y_end}})
    return {"result_cents": result, "locked_until": y_end}


async def _party_balances(db, company_id: str, year: int, y_end: str) -> dict:
    has_opening = await db.entries.find_one({"company_id": company_id, "source": "apertura", "year": year})
    q = {"company_id": company_id, "date": {"$lte": y_end}}
    if has_opening:
        q["date"]["$gte"] = f"{year}-01-01"
        q["source"] = {"$ne": "chiusura"}
    else:
        q["source"] = {"$nin": ["chiusura", "apertura"]}
    out: dict = {}
    async for e in db.entries.find(q, {"lines": 1}):
        for l in e["lines"]:
            k = (l.get("party_key"), l.get("party_name"))
            acc = out.setdefault(l["account"], {})
            acc[k] = acc.get(k, 0) + l["dare"] - l["avere"]
    return {code: {k: v for k, v in parties.items() if v} for code, parties in out.items()}


async def reopen_year(db, company: dict, year: int) -> None:
    if company.get("accounting_lock_date") != f"{year}-12-31":
        raise AccountingError(f"Si può riaprire solo l'ultimo esercizio chiuso ({(company.get('accounting_lock_date') or '')[:4] or 'nessuno'}).")
    await db.entries.delete_many({"company_id": company["id"], "source_key": {"$in": [
        f"close:{year}:ce", f"close:{year}:utile", f"close:{year}:sp", f"open:{year + 1}"]}})
    prev = await db.entries.find_one({"company_id": company["id"], "source_key": f"close:{year - 1}:sp"})
    await db.companies.update_one({"id": company["id"]}, {"$set": {"accounting_lock_date": f"{year - 1}-12-31" if prev else None}})


async def fiscal_years(db, company: dict) -> list[dict]:
    years = sorted({e["year"] async for e in db.entries.find({"company_id": company["id"]}, {"year": 1})})
    lock = company.get("accounting_lock_date") or ""
    out = []
    for y in years:
        closed = bool(await db.entries.find_one({"company_id": company["id"], "source_key": f"close:{y}:sp"}))
        out.append({"year": y, "closed": closed, "locked": lock >= f"{y}-12-31",
                    "depreciation_posted": bool(await db.entries.find_one({"company_id": company["id"], "source_key": f"amm:{y}"}))})
    return out


# ------------------------------------------------------------------ modelli per la prima nota

TEMPLATES = [
    {"id": "generica", "label": "Registrazione generica", "causale": "GEN", "lines": []},
    {"id": "stipendi", "label": "Stipendi del mese (dal cedolino)", "causale": "STIP", "lines": [
        ("costi_stipendi", "D"), ("costi_oneri_sociali", "D"), ("debiti_dipendenti", "A"), ("debiti_inps", "A"), ("ritenute_da_versare", "A")]},
    {"id": "tfr", "label": "Accantonamento TFR", "causale": "GEN", "lines": [("costi_tfr", "D"), ("fondo_tfr", "A")]},
    {"id": "fatture_da_ricevere", "label": "Fattura da ricevere (costo di competenza)", "causale": "GEN", "lines": [
        ("costi_generici", "D"), ("fatture_da_ricevere", "A")]},
    {"id": "imposte", "label": "Imposte dell'esercizio (IRES e IRAP)", "causale": "GEN", "lines": [
        ("ires", "D"), ("irap", "D"), ("debiti_imposte", "A")]},
    {"id": "cassa", "label": "Spesa pagata in contanti", "causale": "GEN", "lines": [("costi_altri", "D"), ("cassa", "A")]},
    {"id": "apertura", "label": "Saldi iniziali (inizio uso del programma)", "causale": "APE", "lines": [
        ("cassa", "D"), ("clienti", "D"), ("fornitori", "A"), ("capitale", "A"), ("utili_a_nuovo", "A")]},
]


async def templates_for(db, company: dict) -> list[dict]:
    chart = await load_chart(db, company)
    out = []
    for t in TEMPLATES:
        lines = [{"account": chart.k(k), "account_name": chart.name(chart.k(k)), "side": side} for k, side in t["lines"]]
        if t["id"] == "apertura":
            for bank_key, code in chart.by_key.items():
                if bank_key.startswith("banca:"):
                    lines.insert(0, {"account": code, "account_name": chart.name(code), "side": "D"})
        out.append({**t, "lines": lines})
    return out


def check_open(company: dict, d: str) -> None:
    if is_locked(company, d):
        raise AccountingError(f"Il periodo fino al {parse_date(company['accounting_lock_date']).strftime('%d/%m/%Y')} è chiuso in contabilità.")

