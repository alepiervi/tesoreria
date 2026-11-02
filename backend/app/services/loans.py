"""Finanziamenti: mutui, leasing, prestiti (con piano di rimborso) e fidi / anticipi (linee di credito)."""
import calendar
from datetime import date

from ..utils import parse_date, today

KINDS = {
    "mutuo": "Mutuo",
    "finanziamento": "Finanziamento",
    "leasing": "Leasing",
    "fido": "Fido di cassa",
    "anticipo_fatture": "Anticipo fatture",
}
CREDIT_LINES = {"fido", "anticipo_fatture"}


def add_months(d: date, n: int, day: int | None = None) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = day or d.day
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def french_installment(principal: int, annual_rate: float, months: int) -> int:
    if months <= 0:
        return 0
    r = annual_rate / 100 / 12
    if r == 0:
        return round(principal / months)
    return round(principal * r / (1 - (1 + r) ** -months))


def schedule(loan: dict) -> list[dict]:
    """Piano di rimborso. Con il tasso: quota interessi e capitale (alla francese). Senza: rate costanti."""
    if loan["kind"] in CREDIT_LINES:
        return []
    months = int(loan.get("months") or 0)
    start = parse_date(loan["start_date"])
    rate = float(loan.get("rate") or 0)
    principal = int(loan.get("principal_cents") or 0)
    inst = int(loan.get("installment_cents") or 0) or french_installment(principal, rate, months)
    rows, residual = [], principal
    for n in range(1, months + 1):
        interest = round(residual * rate / 100 / 12) if principal and rate else 0
        capital = inst - interest if principal else inst
        if principal and n == months:
            capital = residual  # l'ultima rata chiude il debito
        residual = max(0, residual - capital) if principal else 0
        rows.append({"n": n, "date": add_months(start, n - 1).isoformat(), "installment_cents": capital + interest,
                     "interest_cents": interest, "principal_cents": capital, "residual_cents": residual})
    return rows


def summary(loan: dict) -> dict:
    t = today().isoformat()
    out = {k: v for k, v in loan.items() if k != "_id"}
    out["kind_label"] = KINDS.get(loan["kind"], loan["kind"])
    if loan["kind"] in CREDIT_LINES:
        out["available_cents"] = max(0, int(loan.get("limit_cents") or 0) - int(loan.get("used_cents") or 0))
        return out
    rows = schedule(loan)
    past = [r for r in rows if r["date"] <= t]
    future = [r for r in rows if r["date"] > t]
    out["installment_cents"] = rows[0]["installment_cents"] if rows else 0
    out["paid_installments"] = len(past)
    out["remaining_installments"] = len(future)
    out["next_date"] = future[0]["date"] if future else None
    out["residual_cents"] = (past[-1]["residual_cents"] if past else int(loan.get("principal_cents") or 0)) \
        if loan.get("principal_cents") else sum(r["installment_cents"] for r in future)
    out["end_date"] = rows[-1]["date"] if rows else None
    return out


def installments_between(loan: dict, start: str, end: str) -> list[dict]:
    if not loan.get("active", True):
        return []
    return [r for r in schedule(loan) if start <= r["date"] < end]
