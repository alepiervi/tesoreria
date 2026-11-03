"""Consumo dell'assistente AI: solo conteggi di token, mai il contenuto delle domande."""
from contextvars import ContextVar
from datetime import date

from ..config import settings
from ..db import get_db
from ..utils import new_id, now_iso, today

current_user: ContextVar[dict | None] = ContextVar("current_user", default=None)

KIND_LABELS = {"domanda": "Domande all'assistente", "documento": "Lettura scontrini e documenti", "abbinamento": "Abbinamenti movimenti"}


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * settings.ai_price_in_per_mtok + output_tokens * settings.ai_price_out_per_mtok) / 1_000_000


async def record(kind: str, input_tokens: int, output_tokens: int):
    if not input_tokens and not output_tokens:
        return
    user = current_user.get()
    try:
        await get_db().ai_usage.insert_one({
            "id": new_id(), "at": now_iso(), "month": today().strftime("%Y-%m"), "kind": kind,
            "user_id": user["id"] if user else None, "user_name": (user or {}).get("name") or (user or {}).get("email", "automatico"),
            "input_tokens": int(input_tokens), "output_tokens": int(output_tokens), "model": settings.ai_model,
        })
    except Exception:  # noqa: BLE001 - il conteggio non deve mai bloccare l'assistente
        pass


def _months_back(n: int) -> list[str]:
    d = today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = date(d.year - (d.month == 1), 12 if d.month == 1 else d.month - 1, 1)
    return out


def _totals(rows: list[dict]) -> dict:
    i = sum(r["input_tokens"] for r in rows)
    o = sum(r["output_tokens"] for r in rows)
    return {"requests": len(rows), "input_tokens": i, "output_tokens": o, "cost_usd": round(cost_usd(i, o), 2)}


async def summary(month: str | None = None) -> dict:
    months = _months_back(6)
    month = month if month in months else months[0]
    db = get_db()
    rows = await db.ai_usage.find({"month": {"$in": months}}, {"_id": 0}).to_list(100000)
    current = [r for r in rows if r["month"] == month]
    by_kind, by_user = {}, {}
    for r in current:
        by_kind.setdefault(r["kind"], []).append(r)
        by_user.setdefault(r.get("user_name") or "automatico", []).append(r)
    budget = settings.ai_monthly_budget_usd
    total = _totals(current)
    return {
        "month": month, "months": months, "model": settings.ai_model, "provider": settings.ai_provider,
        "total": total,
        "budget_usd": budget, "budget_used_pct": round(total["cost_usd"] / budget * 100) if budget else None,
        "by_kind": sorted(({"kind": k, "label": KIND_LABELS.get(k, k), **_totals(v)} for k, v in by_kind.items()),
                          key=lambda x: -x["cost_usd"]),
        "by_user": sorted(({"name": k, **_totals(v)} for k, v in by_user.items()), key=lambda x: -x["cost_usd"]),
        "history": [{"month": m, **_totals([r for r in rows if r["month"] == m])} for m in reversed(months)],
        "prices": {"input_per_mtok": settings.ai_price_in_per_mtok, "output_per_mtok": settings.ai_price_out_per_mtok},
        "updated_at": now_iso(),
    }
