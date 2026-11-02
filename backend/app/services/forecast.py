"""Previsione dei flussi di cassa a settimane.

Parte dal saldo attuale dei conti e aggiunge:
- incassi attesi (scadenze di fatture attive ancora aperte)
- pagamenti previsti (fatture passive, F24 e IVA stimata, scadenze manuali)
- spese/entrate ricorrenti (stipendi, affitto...)
- rate di mutui, leasing e finanziamenti
Le scadenze già passate e non saldate vengono messe nella prima settimana.

Scenari ("cosa succede se..."): `adjustments` permette di spostare incassi o pagamenti,
toglierli o aggiungere entrate/uscite ipotetiche, senza modificare i dati veri.
"""
from .invoices import payable
import calendar
from datetime import date, timedelta

from ..utils import parse_date, today
from .loans import CREDIT_LINES, installments_between

OPEN = {"aperta", "da_pagare", "in_attesa_autorizzazione", "inviato"}


def _monthly_occurrences(day_of_month: int, start: date, end: date):
    """Date del giorno N di ogni mese tra start (incluso) ed end (escluso)."""
    y, m = start.year, start.month
    while True:
        last = calendar.monthrange(y, m)[1]
        d = date(y, m, min(day_of_month, last))
        if d >= end:
            break
        if d >= start:
            yield d
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _index_adjustments(adjustments: list[dict] | None):
    delays, skips, party_delays, extras = {}, set(), [], []
    for a in adjustments or []:
        t = a.get("type")
        if t == "delay" and a.get("deadline_id"):
            delays[a["deadline_id"]] = int(a.get("days") or 0)
        elif t == "skip" and a.get("deadline_id"):
            skips.add(a["deadline_id"])
        elif t == "delay_party" and a.get("name"):
            party_delays.append((a["name"].lower(), int(a.get("days") or 0), a.get("kind", "incasso")))
        elif t == "extra" and a.get("date") and a.get("amount_cents"):
            extras.append(a)
    return delays, skips, party_delays, extras


async def weekly_forecast(db, company_ids: list[str], weeks: int = 8, adjustments: list[dict] | None = None) -> dict:
    start = today()
    end = start + timedelta(days=7 * weeks)
    delays, skips, party_delays, extras = _index_adjustments(adjustments)
    accounts = await db.bank_accounts.find({"company_id": {"$in": company_ids}, "status": {"$ne": "scollegato"}},
                                           {"_id": 0}).to_list(500)
    opening = sum(a.get("balance_cents", 0) for a in accounts)

    buckets = []
    for i in range(weeks):
        ws = start + timedelta(days=7 * i)
        buckets.append({"week": i + 1, "start": ws.isoformat(), "end": (ws + timedelta(days=6)).isoformat(),
                        "inflow_cents": 0, "outflow_cents": 0, "items": []})

    def bucket_for(d: date):
        if d < start:
            return buckets[0]
        idx = (d - start).days // 7
        return buckets[idx] if idx < weeks else None

    def add(d: date, item: dict, inflow: bool):
        b = bucket_for(d)
        if b is None:
            return
        if inflow:
            b["inflow_cents"] += item["amount_cents"]
        else:
            b["outflow_cents"] += item["amount_cents"]
        b["items"].append(item)

    # Le scadenze spostate in avanti dagli scenari possono arrivare da oltre l'orizzonte: si leggono tutte
    max_delay = max([0, *delays.values(), *[d for _, d, _ in party_delays]])
    query_end = end if not max_delay else end + timedelta(days=1)
    deadlines = await db.deadlines.find(
        {"company_id": {"$in": company_ids}, "status": {"$in": list(OPEN)}, "due_date": {"$lt": query_end.isoformat()}},
        {"_id": 0}).to_list(5000)
    invoice_ids = [d["invoice_id"] for d in deadlines if d.get("invoice_id")]
    invoices = {i["id"]: i for i in await db.invoices.find({"id": {"$in": invoice_ids}}, {"_id": 0}).to_list(5000)}

    for d in deadlines:
        if d["id"] in skips:
            continue
        amount = d["amount_cents"]
        inv = invoices.get(d.get("invoice_id"))
        if inv and inv.get("paid_cents"):
            # Fattura pagata in parte: conta solo il residuo
            amount = min(amount, payable(inv) - inv.get("paid_cents", 0))
        if amount <= 0:
            continue
        due = parse_date(d["due_date"])
        overdue = due < start
        shift = delays.get(d["id"], 0)
        for name, days, kind in party_delays:
            if (d["kind"] == "incasso") == (kind == "incasso") and name in (d.get("description", "") + " " + d.get("beneficiary", "")).lower():
                shift = max(shift, days)
        if shift:
            due = max(due, start) + timedelta(days=shift)
        item = {"description": d["description"], "amount_cents": amount, "due_date": due.isoformat(),
                "kind": d["kind"], "company_id": d["company_id"], "overdue": overdue and not shift,
                "estimate": d.get("estimate", False), "moved": bool(shift), "deadline_id": d["id"]}
        add(due, item, d["kind"] == "incasso")

    recurring = await db.recurring.find({"company_id": {"$in": company_ids}, "active": True}, {"_id": 0}).to_list(1000)
    # mesi in cui gli stipendi sono già una scadenza creata dalle paghe: la voce ricorrente non va contata due volte
    payroll_months = {(d["company_id"], d.get("payroll_month")) async for d in db.deadlines.find(
        {"company_id": {"$in": company_ids}, "payroll_role": "netto"}, {"company_id": 1, "payroll_month": 1})}
    for r in recurring:
        is_salary = "stipend" in r["description"].lower()
        for d in _monthly_occurrences(int(r["day_of_month"]), start, end):
            if is_salary and (r["company_id"], d.isoformat()[:7]) in payroll_months:
                continue
            add(d, {"description": r["description"] + " (ricorrente)", "amount_cents": r["amount_cents"],
                    "due_date": d.isoformat(), "kind": r["kind"], "company_id": r["company_id"], "overdue": False},
                r["kind"] == "entrata")

    loans = await db.loans.find({"company_id": {"$in": company_ids}, "active": {"$ne": False}}, {"_id": 0}).to_list(500)
    credit_available = 0
    for loan in loans:
        if loan["kind"] in CREDIT_LINES:
            credit_available += max(0, int(loan.get("limit_cents") or 0) - int(loan.get("used_cents") or 0))
            continue
        for row in installments_between(loan, start.isoformat(), end.isoformat()):
            add(parse_date(row["date"]), {"description": f"Rata {row['n']} · {loan['lender']} {loan.get('description', '')}".strip(),
                                          "amount_cents": row["installment_cents"], "due_date": row["date"], "kind": "rata",
                                          "company_id": loan["company_id"], "overdue": False}, False)

    for x in extras:
        d = parse_date(x["date"])
        amt = int(x["amount_cents"])
        add(max(d, start), {"description": (x.get("description") or "Movimento ipotetico") + " (scenario)",
                            "amount_cents": abs(amt), "due_date": d.isoformat(), "kind": "entrata" if amt > 0 else "uscita",
                            "company_id": x.get("company_id"), "overdue": False, "scenario": True}, amt > 0)

    balance = opening
    lowest = {"balance_cents": opening, "week": 0}
    for b in buckets:
        balance += b["inflow_cents"] - b["outflow_cents"]
        b["balance_end_cents"] = balance
        b["items"].sort(key=lambda x: x["due_date"])
        if balance < lowest["balance_cents"]:
            lowest = {"balance_cents": balance, "week": b["week"], "start": b["start"]}

    return {"opening_balance_cents": opening, "weeks": buckets, "lowest": lowest,
            "goes_negative": any(b["balance_end_cents"] < 0 for b in buckets),
            "credit_available_cents": credit_available,
            "uses_credit_lines": lowest["balance_cents"] < 0 and -lowest["balance_cents"] <= credit_available}
