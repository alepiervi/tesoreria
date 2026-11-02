"""Ritenute d'acconto sulle fatture dei professionisti: quando si paga la fattura, la ritenuta va versata
con F24 (codice tributo 1040) entro il 16 del mese successivo. Qui si crea la scadenza in automatico."""
from datetime import date

from ..utils import new_id, now_iso, parse_date, today
from .invoices import payable

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
          "ottobre", "novembre", "dicembre"]


def _due(month_key: str) -> date:
    y, m = int(month_key[:4]), int(month_key[5:7])
    d = date(y + (m == 12), m % 12 + 1, 16)
    while d.weekday() >= 5:
        d = date.fromordinal(d.toordinal() + 1)
    return d


async def sync_withholding_deadlines(db, company: dict) -> int:
    totals: dict[str, int] = {}
    async for inv in db.invoices.find({"company_id": company["id"], "direction": "passiva",
                                       "withholding_cents": {"$gt": 0}, "paid_cents": {"$gt": 0}}):
        # la ritenuta matura in proporzione a quanto pagato; si attribuisce al mese del pagamento (o di oggi)
        month = (inv.get("paid_at") or today().isoformat())[:7]
        share = round(inv["withholding_cents"] * min(inv["paid_cents"], payable(inv)) / payable(inv)) if payable(inv) else 0
        totals[month] = totals.get(month, 0) + share
    changed = 0
    for month, amount in totals.items():
        due = _due(month)
        existing = await db.deadlines.find_one({"company_id": company["id"], "auto_withholding_period": month})
        if existing and existing["status"] != "da_pagare":
            continue
        if due < today() and not existing:
            continue  # scadenza già passata: probabilmente versata fuori dal programma
        label = f"Ritenute d'acconto {MONTHS[int(month[5:7]) - 1]} {month[:4]} (cod. 1040)"
        if existing:
            if existing["amount_cents"] != amount:
                await db.deadlines.update_one({"id": existing["id"]}, {"$set": {"amount_cents": amount}})
                changed += 1
        elif amount > 0:
            await db.deadlines.insert_one({
                "id": new_id(), "company_id": company["id"], "kind": "f24", "description": label,
                "due_date": due.isoformat(), "amount_cents": amount, "invoice_id": None, "beneficiary": "Agenzia delle Entrate",
                "iban": "", "status": "da_pagare", "manual": False, "auto_withholding_period": month,
                "created_at": now_iso()})
            changed += 1
    return changed
