"""Pianificazione: IVA stimata, budget, finanziamenti e fidi, scenari di cassa."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services import loans as loan_svc
from ..services.budget import BUDGET_CATEGORIES, budget_status, suggest_from_history
from ..services.forecast import weekly_forecast
from ..services.vat import compute as vat_compute
from ..services.vat import sync_vat_deadlines
from ..utils import new_id, now_iso, parse_date, to_cents, today
from .common import companies_with, load

router = APIRouter(tags=["planning"])


# ---------- IVA ----------

class VatSettingsIn(BaseModel):
    vat_period: str  # mensile | trimestrale
    vat_auto: bool = True
    opening_credit: str = ""


@router.get("/companies/{company_id}/vat")
async def vat(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    company = await get_db().companies.find_one({"id": company_id}, {"_id": 0})
    data = await vat_compute(get_db(), company, year or today().year)
    data["vat_auto"] = company.get("vat_auto", True)
    data["opening_credit_cents"] = company.get("vat_opening_credit_cents", 0)
    return data


@router.put("/companies/{company_id}/vat-settings")
async def vat_settings(company_id: str, body: VatSettingsIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_deadlines")
    if body.vat_period not in {"mensile", "trimestrale"}:
        raise HTTPException(400, "Periodicità non valida.")
    db = get_db()
    credit = to_cents(body.opening_credit) if body.opening_credit.strip() else 0
    await db.companies.update_one({"id": company_id}, {"$set": {
        "vat_period": body.vat_period, "vat_auto": body.vat_auto, "vat_opening_credit_cents": credit}})
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    if body.vat_auto:
        # cambiando periodicità le vecchie stime non pagate non valgono più
        await db.deadlines.delete_many({"company_id": company_id, "auto_vat_period": {"$ne": None}, "status": "da_pagare"})
        await sync_vat_deadlines(db, company)
    else:
        await db.deadlines.delete_many({"company_id": company_id, "auto_vat_period": {"$ne": None}, "status": "da_pagare"})
    await audit.log(user, "impostazioni_iva", company_id, details=body.model_dump())
    return {"ok": True}


@router.post("/companies/{company_id}/vat/sync")
async def vat_sync(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_deadlines")
    company = await get_db().companies.find_one({"id": company_id}, {"_id": 0})
    return {"changed": await sync_vat_deadlines(get_db(), company)}


# ---------- Budget ----------

class BudgetItem(BaseModel):
    category: str
    months: list[int]  # 12 importi in centesimi


class BudgetIn(BaseModel):
    year: int
    items: list[BudgetItem]


@router.get("/companies/{company_id}/budget")
async def get_budget(company_id: str, year: int | None = None, month: int | None = None,
                     user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    t = today()
    data = await budget_status(get_db(), company_id, year or t.year, month or t.month)
    data["categories"] = BUDGET_CATEGORIES
    return data


@router.put("/companies/{company_id}/budget")
async def save_budget(company_id: str, body: BudgetIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_budget")
    db = get_db()
    for item in body.items:
        if item.category not in BUDGET_CATEGORIES:
            raise HTTPException(400, f"Categoria non valida: {item.category}")
        if len(item.months) != 12 or any(v < 0 for v in item.months):
            raise HTTPException(400, "Servono 12 importi mensili, non negativi.")
    await db.budgets.delete_many({"company_id": company_id, "year": body.year})
    docs = [{"id": new_id(), "company_id": company_id, "year": body.year, "category": i.category, "months": i.months,
             "updated_by": user["id"], "updated_at": now_iso()} for i in body.items if any(i.months)]
    if docs:
        await db.budgets.insert_many(docs)
    await audit.log(user, "budget_salvato", company_id, str(body.year), {"categorie": len(docs)})
    return {"ok": True}


@router.get("/companies/{company_id}/budget/suggest")
async def suggest_budget(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    return await suggest_from_history(get_db(), company_id, today())


# ---------- Finanziamenti e fidi ----------

class LoanIn(BaseModel):
    kind: str
    lender: str
    description: str = ""
    principal: str = ""
    rate: float = 0
    months: int = 0
    start_date: str = ""
    installment: str = ""
    limit: str = ""
    used: str = ""
    active: bool = True


def _loan_doc(body: LoanIn) -> dict:
    if body.kind not in loan_svc.KINDS:
        raise HTTPException(400, "Tipo di finanziamento non valido.")
    if not body.lender.strip():
        raise HTTPException(400, "Indica la banca o la società finanziaria.")
    doc = {"kind": body.kind, "lender": body.lender.strip(), "description": body.description.strip(), "active": body.active}
    if body.kind in loan_svc.CREDIT_LINES:
        doc.update(limit_cents=to_cents(body.limit), used_cents=to_cents(body.used) if body.used.strip() else 0)
        if doc["limit_cents"] <= 0:
            raise HTTPException(400, "Indica l'importo del fido.")
        return doc
    try:
        parse_date(body.start_date)
    except ValueError:
        raise HTTPException(400, "Indica la data della prima rata.")
    if body.months <= 0 or body.months > 480:
        raise HTTPException(400, "Indica il numero di rate (da 1 a 480).")
    principal = to_cents(body.principal) if body.principal.strip() else 0
    installment = to_cents(body.installment) if body.installment.strip() else 0
    if not principal and not installment:
        raise HTTPException(400, "Indica l'importo finanziato oppure la rata.")
    if body.rate < 0 or body.rate > 30:
        raise HTTPException(400, "Tasso non valido.")
    doc.update(principal_cents=principal, installment_cents=installment, rate=body.rate, months=body.months,
               start_date=body.start_date)
    return doc


@router.get("/loans")
async def list_loans(company_id: str | None = None, user: dict = Depends(get_current_user)):
    scope = await companies_with(user, "view", company_id)
    items = await get_db().loans.find({"company_id": {"$in": list(scope)}}, {"_id": 0}).sort("created_at", 1).to_list(500)
    result = []
    for loan in items:
        s = loan_svc.summary(loan)
        s["company_name"] = scope[loan["company_id"]]["name"]
        s["can_edit"] = "manage_deadlines" in scope[loan["company_id"]]["permissions"]
        result.append(s)
    active = [r for r in result if r.get("active", True)]
    return {
        "items": result,
        "totals": {
            "residual_cents": sum(r.get("residual_cents", 0) for r in active if r["kind"] not in loan_svc.CREDIT_LINES),
            "monthly_installments_cents": sum(r.get("installment_cents", 0) for r in active
                                              if r["kind"] not in loan_svc.CREDIT_LINES and r.get("remaining_installments")),
            "credit_limit_cents": sum(r.get("limit_cents", 0) for r in active if r["kind"] in loan_svc.CREDIT_LINES),
            "credit_available_cents": sum(r.get("available_cents", 0) for r in active if r["kind"] in loan_svc.CREDIT_LINES),
        },
        "kinds": loan_svc.KINDS,
    }


@router.post("/companies/{company_id}/loans")
async def create_loan(company_id: str, body: LoanIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_deadlines")
    doc = {"id": new_id(), "company_id": company_id, **_loan_doc(body), "created_at": now_iso()}
    await get_db().loans.insert_one(dict(doc))
    await audit.log(user, "finanziamento_creato", company_id, f"{doc['lender']} {doc['description']}")
    return loan_svc.summary(doc)


@router.put("/loans/{loan_id}")
async def update_loan(loan_id: str, body: LoanIn, user: dict = Depends(get_current_user)):
    loan, _ = await load("loans", loan_id, user, "manage_deadlines")
    doc = _loan_doc(body)
    await get_db().loans.update_one({"id": loan_id}, {"$set": doc})
    await audit.log(user, "finanziamento_modificato", loan["company_id"], f"{doc['lender']} {doc['description']}")
    return {"ok": True}


@router.delete("/loans/{loan_id}")
async def delete_loan(loan_id: str, user: dict = Depends(get_current_user)):
    loan, _ = await load("loans", loan_id, user, "manage_deadlines")
    await get_db().loans.delete_one({"id": loan_id})
    await audit.log(user, "finanziamento_eliminato", loan["company_id"], f"{loan['lender']} {loan.get('description', '')}")
    return {"ok": True}


@router.get("/loans/{loan_id}/schedule")
async def loan_schedule(loan_id: str, user: dict = Depends(get_current_user)):
    loan, _ = await load("loans", loan_id, user, "view")
    return {"loan": loan_svc.summary(loan), "rows": loan_svc.schedule(loan)}


# ---------- Scenari ----------

class ScenarioIn(BaseModel):
    company_id: str | None = None
    weeks: int = 12
    adjustments: list[dict] = []


@router.post("/forecast/scenario")
async def scenario(body: ScenarioIn, user: dict = Depends(get_current_user)):
    scope = await companies_with(user, "view", body.company_id)
    weeks = max(4, min(body.weeks, 26))
    ids = list(scope)
    for a in body.adjustments:
        if a.get("type") == "extra":
            try:
                a["amount_cents"] = int(a.get("amount_cents") or 0)
                parse_date(a.get("date", ""))
            except (ValueError, TypeError):
                raise HTTPException(400, "Data o importo non validi nello scenario.")
    db = get_db()
    return {"base": await weekly_forecast(db, ids, weeks),
            "scenario": await weekly_forecast(db, ids, weeks, body.adjustments)}


@router.get("/forecast/open-items")
async def forecast_items(company_id: str | None = None, user: dict = Depends(get_current_user)):
    """Incassi e pagamenti aperti, per scegliere cosa spostare in uno scenario."""
    scope = await companies_with(user, "view", company_id)
    items = await get_db().deadlines.find(
        {"company_id": {"$in": list(scope)}, "status": {"$in": ["aperta", "da_pagare", "in_attesa_autorizzazione"]}},
        {"_id": 0, "id": 1, "description": 1, "due_date": 1, "amount_cents": 1, "kind": 1, "company_id": 1}
    ).sort("due_date", 1).to_list(500)
    for i in items:
        i["company_name"] = scope[i["company_id"]]["name"]
    return items
