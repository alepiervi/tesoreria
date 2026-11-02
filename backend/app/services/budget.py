"""Budget per categoria: quanto si prevede di spendere (o incassare) ogni mese, confrontato con il reale."""
from datetime import date, timedelta

from .categories import CATEGORIES, NEUTRAL_CATEGORIES

REVENUE = {"Incassi clienti", "Altre entrate"}
BUDGET_CATEGORIES = [c for c in CATEGORIES if c not in NEUTRAL_CATEGORIES and c != "Da classificare"]


async def _actuals(db, company_id: str, year: int) -> dict[tuple[str, int], int]:
    """Importi reali per (categoria, mese): entrate per le categorie di ricavo, uscite per le altre."""
    out: dict[tuple[str, int], int] = {}
    async for t in db.transactions.find({"company_id": company_id, "date": {"$gte": f"{year}-01-01", "$lte": f"{year}-12-31"},
                                         "category": {"$nin": list(NEUTRAL_CATEGORIES)}},
                                        {"category": 1, "amount_cents": 1, "date": 1}):
        cat = t["category"]
        m = int(t["date"][5:7])
        if cat in REVENUE:
            val = t["amount_cents"] if t["amount_cents"] > 0 else 0
        else:
            val = -t["amount_cents"]  # uscite positive, eventuali rimborsi riducono la spesa
        out[(cat, m)] = out.get((cat, m), 0) + val
    return out


async def budget_status(db, company_id: str, year: int, month: int) -> dict:
    budgets = {b["category"]: b["months"] async for b in db.budgets.find({"company_id": company_id, "year": year})}
    actual = await _actuals(db, company_id, year)
    rows = []
    for cat in BUDGET_CATEGORIES:
        months = budgets.get(cat) or [0] * 12
        month_actual = actual.get((cat, month), 0)
        ytd_actual = sum(actual.get((cat, m), 0) for m in range(1, month + 1))
        ytd_budget = sum(months[:month])
        if not months[month - 1] and not month_actual and not ytd_budget and not ytd_actual:
            continue
        b = months[month - 1]
        rows.append({
            "category": cat, "kind": "entrata" if cat in REVENUE else "uscita",
            "budget_cents": b, "actual_cents": month_actual,
            "pct": round(month_actual / b * 100) if b else None,
            "ytd_budget_cents": ytd_budget, "ytd_actual_cents": ytd_actual,
            "annual_budget_cents": sum(months), "months": months,
            "over": bool(b) and (month_actual < b if cat in REVENUE else month_actual > b),
        })
    rows.sort(key=lambda r: (r["kind"] != "entrata", -max(r["budget_cents"], r["actual_cents"])))
    cost = [r for r in rows if r["kind"] == "uscita"]
    rev = [r for r in rows if r["kind"] == "entrata"]
    return {
        "year": year, "month": month, "rows": rows, "has_budget": bool(budgets),
        "totals": {
            "cost_budget_cents": sum(r["budget_cents"] for r in cost), "cost_actual_cents": sum(r["actual_cents"] for r in cost),
            "revenue_budget_cents": sum(r["budget_cents"] for r in rev), "revenue_actual_cents": sum(r["actual_cents"] for r in rev),
        },
    }


async def suggest_from_history(db, company_id: str, reference: date) -> dict[str, int]:
    """Media mensile degli ultimi 12 mesi per categoria: un punto di partenza per il budget."""
    start = (reference.replace(day=1) - timedelta(days=365)).replace(day=1).isoformat()
    end = reference.replace(day=1).isoformat()
    totals: dict[str, int] = {}
    months: set[str] = set()
    async for t in db.transactions.find({"company_id": company_id, "date": {"$gte": start, "$lt": end},
                                         "category": {"$in": BUDGET_CATEGORIES}}, {"category": 1, "amount_cents": 1, "date": 1}):
        months.add(t["date"][:7])
        cat = t["category"]
        val = (t["amount_cents"] if t["amount_cents"] > 0 else 0) if cat in REVENUE else -t["amount_cents"]
        totals[cat] = totals.get(cat, 0) + val
    n = max(1, len(months))
    return {c: round(v / n / 1000) * 1000 for c, v in totals.items() if v > 0}  # arrotondato a 10 €
