from datetime import date, timedelta

from fastapi import APIRouter, Depends

from ..db import get_db
from ..deps import get_current_user, require
from ..services.categories import NEUTRAL_CATEGORIES
from ..services.forecast import weekly_forecast
from ..utils import parse_date, today
from .common import companies_with

router = APIRouter(tags=["dashboard"])

MONTHS_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
CONSENT_WARNING_DAYS = 30
STALE_IMPORT_DAYS = 7  # oltre questi giorni un conto manuale va aggiornato con un nuovo estratto conto


def _month_starts(n: int) -> list[date]:
    t = today().replace(day=1)
    out = []
    y, m = t.year, t.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


async def _monthly_series(db, company_ids: list[str], months: int = 6) -> list[dict]:
    starts = _month_starts(months)
    series = {s.strftime("%Y-%m"): {"month": s.strftime("%Y-%m"), "label": MONTHS_IT[s.month - 1],
                                    "inflow_cents": 0, "outflow_cents": 0} for s in starts}
    cursor = get_db().transactions.find(
        {"company_id": {"$in": company_ids}, "date": {"$gte": starts[0].isoformat()},
         "category": {"$nin": list(NEUTRAL_CATEGORIES)}}, {"date": 1, "amount_cents": 1})
    async for t in cursor:
        bucket = series.get(t["date"][:7])
        if not bucket:
            continue
        if t["amount_cents"] > 0:
            bucket["inflow_cents"] += t["amount_cents"]
        else:
            bucket["outflow_cents"] += -t["amount_cents"]
    return list(series.values())


async def _company_card(db, cid: str, name: str) -> dict:
    accounts = await db.bank_accounts.find({"company_id": cid, "status": {"$ne": "scollegato"}}, {"_id": 0}).to_list(100)
    month = today().strftime("%Y-%m")
    inflow = outflow = 0
    async for t in db.transactions.find({"company_id": cid, "date": {"$regex": f"^{month}"},
                                         "category": {"$nin": list(NEUTRAL_CATEGORIES)}}, {"amount_cents": 1}):
        if t["amount_cents"] > 0:
            inflow += t["amount_cents"]
        else:
            outflow -= t["amount_cents"]
    warnings, stale = [], []
    for a in accounts:
        if a.get("provider") == "manuale":
            last = a.get("last_import_to")
            days = (today() - parse_date(last)).days if last else None
            if days is None or days > STALE_IMPORT_DAYS:
                stale.append({"account_id": a["id"], "bank_name": a["bank_name"], "iban_masked": a["iban_masked"],
                              "last_import_to": last, "days": days})
            continue
        if a.get("consent_expires_at"):
            days = (parse_date(a["consent_expires_at"]) - today()).days
            if days <= CONSENT_WARNING_DAYS:
                warnings.append({"account_id": a["id"], "bank_name": a["bank_name"],
                                 "iban_masked": a["iban_masked"], "days_left": days})
    return {
        "id": cid, "name": name,
        "balance_cents": sum(a.get("balance_cents", 0) for a in accounts),
        "accounts_count": len(accounts),
        "month_inflow_cents": inflow, "month_outflow_cents": outflow,
        "to_reconcile": await db.transactions.count_documents({"company_id": cid, "status": "da_riconciliare"}),
        "open_questions": await db.notes.count_documents({"company_id": cid, "is_question": True, "resolved": False}),
        "consent_warnings": warnings,
        "stale_imports": stale,
    }


async def _upcoming(db, company_ids: list[str], names: dict, days: int = 14) -> list[dict]:
    limit_date = (today() + timedelta(days=days)).isoformat()
    items = await db.deadlines.find(
        {"company_id": {"$in": company_ids}, "status": {"$in": ["aperta", "da_pagare", "in_attesa_autorizzazione"]},
         "due_date": {"$lte": limit_date}}, {"_id": 0}).sort("due_date", 1).to_list(20)
    t = today().isoformat()
    for d in items:
        d["company_name"] = names.get(d["company_id"], "")
        d["overdue"] = d["due_date"] < t
    return items


async def _internal_transfers(db, ids: list[str]) -> int:
    """Trasferimenti tra aziende del gruppo nel mese (esclusi dai totali consolidati)."""
    month = today().strftime("%Y-%m")
    total = 0
    async for t in db.transactions.find({"company_id": {"$in": ids}, "category": "Intercompany",
                                         "date": {"$regex": f"^{month}"}, "amount_cents": {"$lt": 0}}, {"amount_cents": 1}):
        total -= t["amount_cents"]
    return total


@router.get("/dashboard/group")
async def group_dashboard(user: dict = Depends(get_current_user)):
    db = get_db()
    scope = await companies_with(user, "view")
    ids = list(scope)
    cards = [await _company_card(db, cid, info["name"]) for cid, info in scope.items()]
    cards.sort(key=lambda c: c["name"])
    forecast = await weekly_forecast(db, ids) if ids else None
    return {
        "companies": cards,
        "totals": {
            "balance_cents": sum(c["balance_cents"] for c in cards),
            "month_inflow_cents": sum(c["month_inflow_cents"] for c in cards),
            "month_outflow_cents": sum(c["month_outflow_cents"] for c in cards),
            "to_reconcile": sum(c["to_reconcile"] for c in cards),
            "open_questions": sum(c["open_questions"] for c in cards),
            "accounts_count": sum(c["accounts_count"] for c in cards),
            "credit_available_cents": forecast["credit_available_cents"] if forecast else 0,
            "internal_transfers_cents": await _internal_transfers(db, ids),
        },
        "monthly": await _monthly_series(db, ids) if ids else [],
        "forecast": forecast,
        "upcoming": await _upcoming(db, ids, {k: v["name"] for k, v in scope.items()}),
    }


@router.get("/companies/{company_id}/dashboard")
async def company_dashboard(company_id: str, weeks: int = 8, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    db = get_db()
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    accounts = await db.bank_accounts.find({"company_id": company_id}, {"_id": 0, "iban": 0}).to_list(100)
    for a in accounts:
        if a.get("consent_expires_at"):
            a["consent_days_left"] = (parse_date(a["consent_expires_at"]) - today()).days
    recent = await db.transactions.find({"company_id": company_id}, {"_id": 0}) \
        .sort([("date", -1), ("created_at", -1)]).limit(8).to_list(8)
    return {
        "card": await _company_card(db, company_id, company["name"]),
        "accounts": accounts,
        "monthly": await _monthly_series(db, [company_id]),
        "forecast": await weekly_forecast(db, [company_id], max(4, min(weeks, 26))),
        "recent": recent,
        "upcoming": await _upcoming(db, [company_id], {company_id: company["name"]}, 30),
    }


@router.get("/forecast")
async def forecast(company_id: str | None = None, weeks: int = 12, user: dict = Depends(get_current_user)):
    scope = await companies_with(user, "view", company_id)
    return await weekly_forecast(get_db(), list(scope), max(4, min(weeks, 26)))
