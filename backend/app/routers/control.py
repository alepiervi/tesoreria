"""Controllo e strategia: funzioni di gruppo, salute dell'azienda, piano a 3 anni, Centrale Rischi."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services import analysis, central_risk, group, plan
from ..utils import new_id, now_iso, parse_date, to_cents, today
from .common import companies_with

router = APIRouter(tags=["control"])


async def _companies(user: dict, perm: str) -> list[dict]:
    scope = await companies_with(user, perm)
    if not scope:
        raise HTTPException(404, "Nessuna azienda disponibile.")
    return await get_db().companies.find({"id": {"$in": list(scope)}}, {"_id": 0}).sort("name", 1).to_list(200)


async def _company(company_id: str, user: dict, perm: str) -> dict:
    await require(user, company_id, perm)
    return await get_db().companies.find_one({"id": company_id}, {"_id": 0})


# ---------------- gruppo

@router.get("/group/consolidated")
async def consolidated(year: int | None = None, user: dict = Depends(get_current_user)):
    companies = await _companies(user, "view_accounting")
    return await group.consolidated(get_db(), companies, year or today().year)


@router.get("/group/liquidity")
async def liquidity(weeks: int = 13, user: dict = Depends(get_current_user)):
    companies = await _companies(user, "view")
    db = get_db()
    out = await group.group_liquidity(db, companies, weeks=max(4, min(weeks, 26)))
    out["intercompany"] = await group.intercompany_balances(db, companies)
    manageable = await companies_with(user, "manage_deadlines")
    out["can_transfer"] = {c["id"]: c["id"] in manageable for c in companies}
    return out


class BufferIn(BaseModel):
    amount: str


@router.put("/companies/{company_id}/cash-buffer")
async def set_buffer(company_id: str, body: BufferIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_budget")
    await get_db().companies.update_one({"id": company_id}, {"$set": {"cash_buffer_cents": max(0, to_cents(body.amount))}})
    return {"ok": True}


class TransferIn(BaseModel):
    from_company_id: str
    to_company_id: str
    amount: str
    date: str
    description: str = ""


@router.post("/group/transfers")
async def prepare_transfer(body: TransferIn, user: dict = Depends(get_current_user)):
    """Prepara un trasferimento tra aziende: pagamento da autorizzare nella prima, incasso previsto nella seconda."""
    db = get_db()
    await require(user, body.from_company_id, "manage_deadlines")
    await require(user, body.to_company_id, "manage_deadlines")
    if body.from_company_id == body.to_company_id:
        raise HTTPException(400, "Scegli due aziende diverse.")
    amount = to_cents(body.amount)
    if amount <= 0:
        raise HTTPException(400, "Indica un importo maggiore di zero.")
    parse_date(body.date)
    src = await db.companies.find_one({"id": body.from_company_id}, {"_id": 0})
    dst = await db.companies.find_one({"id": body.to_company_id}, {"_id": 0})
    bank = await db.bank_accounts.find_one({"company_id": dst["id"], "status": "attivo", "iban": {"$nin": ["", None]}}, {"_id": 0})
    if not bank:
        raise HTTPException(400, f"{dst['name']} non ha un conto con IBAN su cui ricevere il trasferimento.")
    gid = new_id()
    desc = body.description.strip() or "Finanziamento infragruppo"
    base = {"due_date": body.date, "amount_cents": amount, "invoice_id": None, "manual": True, "group_transfer_id": gid,
            "created_at": now_iso(), "creditor": "gruppo"}
    await db.deadlines.insert_many([
        {**base, "id": new_id(), "company_id": src["id"], "kind": "pagamento", "status": "da_pagare",
         "description": f"{desc} a {dst['name']}", "beneficiary": dst["name"], "iban": bank["iban"]},
        {**base, "id": new_id(), "company_id": dst["id"], "kind": "incasso", "status": "aperta",
         "description": f"{desc} da {src['name']}", "beneficiary": src["name"], "iban": ""},
    ])
    await audit.log(user, "trasferimento_gruppo_preparato", src["id"], f"{desc} a {dst['name']}", {"importo": amount})
    return {"ok": True, "group_transfer_id": gid}


@router.get("/group/compare")
async def compare(year: int | None = None, user: dict = Depends(get_current_user)):
    companies = await _companies(user, "view_accounting")
    return await group.compare(get_db(), companies, year or today().year)


# ---------------- salute dell'azienda

@router.get("/companies/{company_id}/health")
async def health(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    db = get_db()
    return {"ratios": await analysis.ratios(db, company, year), "alerts": await analysis.warning_signals(db, company)}


class CompanyProfileIn(BaseModel):
    legal_form: str


@router.put("/companies/{company_id}/legal-form")
async def set_legal_form(company_id: str, body: CompanyProfileIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_accounting")
    if body.legal_form not in {"individuale", "persone", "capitali"}:
        raise HTTPException(400, "Forma giuridica non valida.")
    await get_db().companies.update_one({"id": company_id}, {"$set": {"legal_form": body.legal_form}})
    return {"ok": True}


# ---------------- piano a 3 anni

class PlanYear(BaseModel):
    revenue_growth: float = 5.0
    variable_cost_pct: float | None = None
    fixed_cost_growth: float = 2.0
    staff_growth: float = 3.0
    capex: str = "0"
    capex_rate: float = 20.0
    new_loan: str = "0"
    new_loan_rate: float = 5.0
    new_loan_months: int = 60
    dso_days: int | None = None
    dpo_days: int | None = None
    tax_rate: float = 27.9


class PlanIn(BaseModel):
    years: list[PlanYear]
    save: bool = False


def _plan_assumptions(body: PlanIn) -> list[dict]:
    out = []
    for y in body.years[:3]:
        d = y.model_dump()
        d["capex_cents"] = max(0, to_cents(d.pop("capex") or 0))
        d["new_loan_cents"] = max(0, to_cents(d.pop("new_loan") or 0))
        if not 1 <= d["new_loan_months"] <= 360:
            raise HTTPException(400, "Durata del finanziamento non valida.")
        out.append(d)
    return out


@router.get("/companies/{company_id}/plan")
async def get_plan(company_id: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    saved = await get_db().business_plans.find_one({"company_id": company_id}, {"_id": 0})
    result = await plan.project(get_db(), company, (saved or {}).get("assumptions"))
    result["saved_at"] = (saved or {}).get("updated_at")
    return result


@router.post("/companies/{company_id}/plan")
async def run_plan(company_id: str, body: PlanIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    assumptions = _plan_assumptions(body)
    if body.save:
        await require(user, company_id, "manage_budget")
        await get_db().business_plans.update_one({"company_id": company_id}, {"$set": {
            "company_id": company_id, "assumptions": assumptions, "updated_at": now_iso(), "updated_by": user["id"]}}, upsert=True)
        await audit.log(user, "piano_salvato", company_id)
    return await plan.project(get_db(), company, assumptions)


@router.post("/companies/{company_id}/plan/export")
async def export_plan(company_id: str, body: PlanIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    result = await plan.project(get_db(), company, _plan_assumptions(body))
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Piano a 3 anni"
    ws.append([f"Piano economico-finanziario · {company['name']}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Base di partenza: {result['base']['source']}"])
    ws.append([])
    ws.append(["Voce", *result["years"]])
    for c in ws[4]:
        c.font = Font(bold=True)
    labels = [("ricavi", "Ricavi"), ("costi_variabili", "Costi variabili"), ("costi_fissi", "Costi fissi"), ("personale", "Personale"),
              ("ebitda", "Margine operativo lordo (MOL)"), ("ammortamenti", "Ammortamenti"), ("ebit", "Risultato operativo"),
              ("interessi", "Interessi"), ("imposte", "Imposte"), ("utile", "Utile"), ("variazione_circolante", "Variazione circolante"),
              ("flusso_operativo", "Flusso di cassa operativo"), ("investimenti", "Investimenti"), ("nuovi_finanziamenti", "Nuovi finanziamenti"),
              ("servizio_debito", "Rate dei finanziamenti"), ("cassa_fine", "Cassa a fine anno"), ("debito_fine", "Debiti finanziari a fine anno"),
              ("pfn", "Posizione finanziaria netta"), ("dscr", "DSCR")]
    for key, label in labels:
        ws.append([label, *[(r[key] / 100 if key != "dscr" and r[key] is not None else r[key]) for r in result["rows"]]])
    for row in ws.iter_rows(min_row=5, min_col=2):
        for c in row:
            c.number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 34
    for col in "BCD":
        ws.column_dimensions[col].width = 16
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="piano_3_anni.xlsx"'})


# ---------------- Centrale Rischi

class CRRow(BaseModel):
    bank: str
    category: str
    granted: str = "0"
    used: str = "0"
    overdraft: str = "0"
    past_due: str = "0"


class CRMonthIn(BaseModel):
    month: str
    rows: list[CRRow]


@router.get("/companies/{company_id}/central-risk")
async def cr_get(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view")
    loans = await get_db().loans.find({"company_id": company_id}, {"_id": 0}).to_list(200)
    return await central_risk.summary(get_db(), company_id, loans)


@router.get("/companies/{company_id}/central-risk/{month}")
async def cr_month(company_id: str, month: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view")
    return await get_db().central_risk.find({"company_id": company_id, "month": month}, {"_id": 0}).sort("bank", 1).to_list(500)


@router.put("/companies/{company_id}/central-risk")
async def cr_save(company_id: str, body: CRMonthIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_banks")
    try:
        parse_date(body.month + "-01")
    except ValueError:
        raise HTTPException(400, "Mese non valido.")
    docs = []
    for r in body.rows:
        if not r.bank.strip():
            continue
        if r.category not in central_risk.CATEGORIES:
            raise HTTPException(400, "Categoria non valida.")
        try:
            values = {k: max(0, to_cents(getattr(r, k) or 0)) for k in ("granted", "used", "overdraft", "past_due")}
        except ValueError:
            raise HTTPException(400, f"Importo non valido per {r.bank}.")
        docs.append({"id": new_id(), "company_id": company_id, "month": body.month, "bank": r.bank.strip(), "category": r.category,
                     "granted_cents": values["granted"], "used_cents": values["used"], "overdraft_cents": values["overdraft"],
                     "past_due_cents": values["past_due"], "updated_at": now_iso()})
    db = get_db()
    await db.central_risk.delete_many({"company_id": company_id, "month": body.month})
    if docs:
        await db.central_risk.insert_many(docs)
    await audit.log(user, "centrale_rischi_aggiornata", company_id, body.month, {"righe": len(docs)})
    return {"ok": True, "rows": len(docs)}


@router.post("/companies/{company_id}/central-risk/read")
async def cr_read(company_id: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Legge il PDF della Centrale Rischi con l'assistente (se attivo) e propone i dati da controllare."""
    await _company(company_id, user, "manage_banks")
    from ..integrations.ai import get_ai
    ai = get_ai()
    data = await file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "File troppo grande (massimo 8 MB).")
    mime = file.content_type or "application/pdf"
    result = await ai.read_document(data, mime, central_risk.READ_PROMPT) if ai else None
    if not result:
        return {"read": False, "message": "Lettura automatica non disponibile: inserisci i dati a mano dal prospetto."}
    rows = [{"bank": r.get("banca", ""), "category": r.get("categoria") if r.get("categoria") in central_risk.CATEGORIES else "revoca",
             "granted": str(r.get("accordato") or 0), "used": str(r.get("utilizzato") or 0),
             "overdraft": str(r.get("sconfinamento") or 0), "past_due": str(r.get("scaduto") or 0)} for r in result.get("righe", [])]
    return {"read": True, "month": result.get("mese"), "rows": rows}
