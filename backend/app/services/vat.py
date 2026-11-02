"""Liquidazione IVA stimata a partire dalle fatture registrate.

È una STIMA per la pianificazione della cassa, non sostituisce il calcolo del commercialista:
- IVA a debito = IVA delle fatture emesse nel periodo (escluse quelle in split payment)
- IVA a credito = IVA delle fatture ricevute con data nel periodo
- il credito di un periodo passa al successivo; importi sotto 25,82 € si rinviano al periodo dopo
- trimestrali: +1% di interessi sui primi tre trimestri; il quarto si versa a marzo con la dichiarazione
Non considera: acconto di dicembre, reverse charge, pro-rata, plafond, IVA per cassa.
Per ogni periodo con IVA da versare crea (o aggiorna) una scadenza F24 "IVA stimata",
che entra da sola nella previsione di cassa.
"""
from datetime import date, timedelta

from ..utils import new_id, now_iso, today

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
          "ottobre", "novembre", "dicembre"]
MIN_PAYMENT = 2582  # 25,82 €


def _next_workday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def periods_for(year: int, mode: str) -> list[dict]:
    out = []
    if mode == "trimestrale":
        dues = [date(year, 5, 16), date(year, 8, 20), date(year, 11, 16), date(year + 1, 3, 16)]
        for q in range(4):
            start = date(year, q * 3 + 1, 1)
            end = (date(year, q * 3 + 4, 1) if q < 3 else date(year + 1, 1, 1)) - timedelta(days=1)
            out.append({"key": f"{year}-T{q + 1}", "label": f"{q + 1}° trimestre {year}", "start": start, "end": end,
                        "due": _next_workday(dues[q]), "interest": q < 3})
    else:
        for m in range(1, 13):
            start = date(year, m, 1)
            end = (date(year + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
            due = date(year + (m == 12), m % 12 + 1, 16)
            out.append({"key": f"{year}-{m:02d}", "label": f"{MONTHS[m - 1]} {year}", "start": start, "end": end,
                        "due": _next_workday(due), "interest": False})
    return out


async def compute(db, company: dict, year: int) -> dict:
    mode = company.get("vat_period", "mensile")
    periods = periods_for(year, mode)
    q = {"company_id": company["id"], "date": {"$gte": f"{year}-01-01", "$lte": f"{year}-12-31"}}
    invoices = await db.invoices.find(q, {"_id": 0, "date": 1, "direction": 1, "vat_cents": 1, "split_payment": 1,
                                          "total_cents": 1}).to_list(100000)
    deadlines = {d["auto_vat_period"]: d async for d in db.deadlines.find(
        {"company_id": company["id"], "auto_vat_period": {"$regex": f"^{year}-"}}, {"_id": 0})}
    carry = company.get("vat_opening_credit_cents", 0) if year == today().year else 0
    t = today()
    rows = []
    for p in periods:
        s, e = p["start"].isoformat(), p["end"].isoformat()
        inside = [i for i in invoices if s <= i["date"] <= e]
        sales = sum(i.get("vat_cents") or 0 for i in inside if i["direction"] == "attiva" and not i.get("split_payment"))
        purchases = sum(i.get("vat_cents") or 0 for i in inside if i["direction"] == "passiva")
        balance = sales - purchases - carry
        to_pay = 0
        if balance >= MIN_PAYMENT:
            to_pay = round(balance * 1.01) if p["interest"] else balance
        state = "futuro" if p["start"] > t else ("in_corso" if p["end"] >= t else "chiuso")
        dl = deadlines.get(p["key"])
        rows.append({
            "key": p["key"], "label": p["label"], "start": s, "end": e, "due_date": p["due"].isoformat(),
            "sales_vat_cents": sales, "purchases_vat_cents": purchases, "carry_in_cents": carry,
            "balance_cents": balance, "to_pay_cents": to_pay, "credit_out_cents": max(0, -balance) if not to_pay else 0,
            "state": state, "deadline_id": dl["id"] if dl else None, "deadline_status": dl["status"] if dl else None,
            "invoices_count": len(inside),
        })
        # carry > 0 = credito che riduce il periodo dopo; carry < 0 = debito sotto soglia che si aggiunge
        carry = 0 if to_pay else -balance
    return {"year": year, "mode": mode, "periods": rows,
            "total_to_pay_cents": sum(r["to_pay_cents"] for r in rows),
            "note": "Stima basata sulle fatture registrate nel programma: verificala con il commercialista."}


async def sync_vat_deadlines(db, company: dict, year: int | None = None) -> int:
    """Crea o aggiorna le scadenze F24 'IVA stimata' (solo quelle non ancora pagate)."""
    year = year or today().year
    data = await compute(db, company, year)
    changed = 0
    for r in data["periods"]:
        if r["state"] == "futuro":
            continue
        if r["due_date"] < today().isoformat():
            # periodo già scaduto: probabilmente versato fuori dal programma, non si crea una scadenza arretrata
            continue
        existing = await db.deadlines.find_one({"company_id": company["id"], "auto_vat_period": r["key"]})
        if existing and existing["status"] != "da_pagare":
            continue  # già pagata o in pagamento: non si tocca
        desc = f"IVA stimata {r['label']}" + (" (periodo in corso)" if r["state"] == "in_corso" else "")
        if r["to_pay_cents"] <= 0:
            if existing:
                await db.deadlines.delete_one({"id": existing["id"]})
                changed += 1
            continue
        fields = {"description": desc, "due_date": r["due_date"], "amount_cents": r["to_pay_cents"]}
        if existing:
            if any(existing.get(k) != v for k, v in fields.items()):
                await db.deadlines.update_one({"id": existing["id"]}, {"$set": fields})
                changed += 1
        else:
            await db.deadlines.insert_one({
                "id": new_id(), "company_id": company["id"], "kind": "f24", **fields, "invoice_id": None,
                "beneficiary": "Agenzia delle Entrate", "iban": "", "status": "da_pagare", "manual": False,
                "estimate": True, "auto_vat_period": r["key"], "created_at": now_iso()})
            changed += 1
    return changed


async def sync_all_vat(db) -> int:
    total = 0
    async for c in db.companies.find({}, {"_id": 0}):
        if c.get("vat_auto", True):
            total += await sync_vat_deadlines(db, c)
    return total
