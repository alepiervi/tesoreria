"""Scadenzario, pagamenti e spese ricorrenti."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..config import settings
from ..integrations.payments import get_payments_provider
from ..services.notifications import _eur, notify, users_with
from ..utils import new_id, now_iso, to_cents, today
from .common import companies_with, load

router = APIRouter(tags=["deadlines"])

KINDS = {"incasso": "Incasso", "pagamento": "Pagamento", "f24": "F24", "altro": "Altro"}
OPEN = ["aperta", "da_pagare", "in_attesa_autorizzazione", "inviato"]


class DeadlineIn(BaseModel):
    kind: str
    description: str
    due_date: str
    amount: str
    beneficiary: str = ""
    iban: str = ""


class DeadlineUpdate(BaseModel):
    description: str | None = None
    due_date: str | None = None
    amount: str | None = None
    beneficiary: str | None = None
    iban: str | None = None


class PayIn(BaseModel):
    account_id: str


class RecurringIn(BaseModel):
    kind: str  # entrata | uscita
    description: str
    amount: str
    day_of_month: int
    active: bool = True


@router.get("/deadlines")
async def list_deadlines(company_id: str | None = None, scope: str = "open", user: dict = Depends(get_current_user)):
    db = get_db()
    companies = await companies_with(user, "view", company_id)
    query: dict = {"company_id": {"$in": list(companies)}}
    if scope == "open":
        query["status"] = {"$in": OPEN}
    items = await db.deadlines.find(query, {"_id": 0}).sort("due_date", 1).to_list(5000)
    t = today().isoformat()
    for d in items:
        info = companies[d["company_id"]]
        d["company_name"] = info["name"]
        d["permissions"] = info["permissions"]
        d["overdue"] = d["status"] in OPEN and d["due_date"] < t
    return items


@router.post("/companies/{company_id}/deadlines")
async def create_deadline(company_id: str, body: DeadlineIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_deadlines")
    if body.kind not in KINDS:
        raise HTTPException(400, "Tipo di scadenza non valido.")
    amount = to_cents(body.amount)
    if amount <= 0:
        raise HTTPException(400, "L'importo deve essere maggiore di zero.")
    d = {"id": new_id(), "company_id": company_id, "kind": body.kind, "description": body.description.strip(),
         "due_date": body.due_date, "amount_cents": amount, "invoice_id": None,
         "beneficiary": body.beneficiary.strip(), "iban": body.iban.replace(" ", "").upper(),
         "status": "aperta" if body.kind == "incasso" else "da_pagare", "manual": True, "created_at": now_iso()}
    await get_db().deadlines.insert_one(dict(d))
    await audit.log(user, "scadenza_creata", company_id, d["description"])
    return d


@router.patch("/deadlines/{deadline_id}")
async def update_deadline(deadline_id: str, body: DeadlineUpdate, user: dict = Depends(get_current_user)):
    d, _ = await load("deadlines", deadline_id, user, "manage_deadlines")
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "amount" in changes:
        changes["amount_cents"] = to_cents(changes.pop("amount"))
    if "iban" in changes:
        changes["iban"] = changes["iban"].replace(" ", "").upper()
    await get_db().deadlines.update_one({"id": deadline_id}, {"$set": changes})
    await audit.log(user, "scadenza_modificata", d["company_id"], d["description"])
    return {"ok": True}


@router.delete("/deadlines/{deadline_id}")
async def delete_deadline(deadline_id: str, user: dict = Depends(get_current_user)):
    d, _ = await load("deadlines", deadline_id, user, "manage_deadlines")
    if d.get("invoice_id"):
        raise HTTPException(400, "Questa scadenza deriva da una fattura: elimina o modifica la fattura.")
    await get_db().deadlines.delete_one({"id": deadline_id})
    await audit.log(user, "scadenza_eliminata", d["company_id"], d["description"])
    return {"ok": True}


@router.post("/deadlines/{deadline_id}/mark-done")
async def mark_done(deadline_id: str, user: dict = Depends(get_current_user)):
    """Per pagamenti fatti fuori dal programma (es. dall'home banking)."""
    d, _ = await load("deadlines", deadline_id, user, "manage_deadlines")
    status = "incassato" if d["kind"] == "incasso" else "pagato"
    await get_db().deadlines.update_one({"id": deadline_id}, {"$set": {"status": status, "done_at": now_iso()}})
    await audit.log(user, "scadenza_chiusa", d["company_id"], d["description"])
    return {"ok": True}


@router.post("/deadlines/{deadline_id}/request-payment")
async def request_payment(deadline_id: str, body: PayIn, user: dict = Depends(get_current_user)):
    d, _ = await load("deadlines", deadline_id, user, "request_payment")
    if d["kind"] == "incasso" or d["status"] != "da_pagare":
        raise HTTPException(400, "Questa scadenza non è un pagamento da preparare.")
    await _check_account(d, body.account_id)
    await get_db().deadlines.update_one({"id": deadline_id}, {"$set": {
        "status": "in_attesa_autorizzazione", "account_id": body.account_id,
        "requested_by": user["id"], "requested_by_name": user.get("name", ""), "requested_at": now_iso()}})
    await audit.log(user, "pagamento_richiesto", d["company_id"], d["description"], {"importo": d["amount_cents"]})
    db = get_db()
    company = await db.companies.find_one({"id": d["company_id"]}, {"name": 1})
    await notify(db, await users_with(db, d["company_id"], "authorize_payment"), kind="pagamento", important=True,
                 company_id=d["company_id"], link="/scadenze", title=f"Pagamento da autorizzare · {company['name']}",
                 body=f"{user.get('name') or user['email']} ha preparato: {d['description']}, {_eur(d['amount_cents'])}")
    return {"ok": True}


@router.post("/deadlines/{deadline_id}/authorize")
async def authorize_payment(deadline_id: str, body: PayIn, user: dict = Depends(get_current_user)):
    d, _ = await load("deadlines", deadline_id, user, "authorize_payment")
    if settings.require_2fa_for_payments and not user.get("totp_enabled"):
        raise HTTPException(403, "Per autorizzare i pagamenti devi attivare la verifica in due passaggi "
                                 "(Impostazioni → Verifica in due passaggi).")
    if d["kind"] == "incasso" or d["status"] not in {"da_pagare", "in_attesa_autorizzazione"}:
        raise HTTPException(400, "Questa scadenza non può essere pagata.")
    if d["kind"] != "f24" and not d.get("iban"):
        raise HTTPException(400, "Manca l'IBAN del beneficiario: aggiungilo alla scadenza.")
    account = await _check_account(d, body.account_id)
    provider = get_payments_provider()
    if provider is None:
        # Pagamento eseguito dall'home banking: qui resta l'autorizzazione, poi si segna come pagato
        await get_db().deadlines.update_one({"id": deadline_id}, {"$set": {
            "status": "da_pagare", "account_id": body.account_id, "authorized_by": user["id"],
            "authorized_by_name": user.get("name", ""), "authorized_at": now_iso()}})
        await audit.log(user, "pagamento_autorizzato", d["company_id"], d["description"],
                        {"importo": d["amount_cents"], "modo": "home banking"})
        if d.get("requested_by") and d["requested_by"] != user["id"]:
            db = get_db()
            requester = await db.users.find_one({"id": d["requested_by"]}, {"_id": 0})
            if requester:
                await notify(db, [requester], kind="pagamento", company_id=d["company_id"], link="/scadenze",
                             title="Pagamento autorizzato", body=f"{d['description']}: autorizzato, va eseguito dall'home banking.")
        return {"ok": True, "manual": True}
    result = await provider.send_transfer(
        account, d.get("beneficiary", ""), d.get("iban", ""), d["amount_cents"], d["description"])
    await get_db().deadlines.update_one({"id": deadline_id}, {"$set": {
        "status": "inviato", "account_id": body.account_id, "payment_ref": result.get("payment_ref"),
        "authorized_by": user["id"], "authorized_by_name": user.get("name", ""), "authorized_at": now_iso()}})
    await audit.log(user, "pagamento_autorizzato", d["company_id"], d["description"],
                    {"importo": d["amount_cents"], "riferimento": result.get("payment_ref")})
    if d.get("requested_by") and d["requested_by"] != user["id"]:
        db = get_db()
        requester = await db.users.find_one({"id": d["requested_by"]}, {"_id": 0})
        if requester:
            await notify(db, [requester], kind="pagamento", company_id=d["company_id"], link="/scadenze",
                         title="Pagamento autorizzato", body=f"{d['description']}: bonifico inviato (rif. {result.get('payment_ref')}).")
    return {"ok": True, **result}


async def _check_account(d: dict, account_id: str) -> dict:
    account = await get_db().bank_accounts.find_one({"id": account_id, "company_id": d["company_id"]}, {"_id": 0})
    if not account or account.get("status") != "attivo":
        raise HTTPException(400, "Scegli un conto attivo della stessa azienda.")
    return account


# ---------- Spese e entrate ricorrenti ----------

@router.get("/companies/{company_id}/recurring")
async def list_recurring(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    return await get_db().recurring.find({"company_id": company_id}, {"_id": 0}).sort("day_of_month", 1).to_list(500)


def _recurring_doc(body: RecurringIn) -> dict:
    if body.kind not in {"entrata", "uscita"}:
        raise HTTPException(400, "Tipo non valido.")
    if not 1 <= body.day_of_month <= 31:
        raise HTTPException(400, "Il giorno del mese deve essere tra 1 e 31.")
    amount = to_cents(body.amount)
    if amount <= 0:
        raise HTTPException(400, "L'importo deve essere maggiore di zero.")
    return {"kind": body.kind, "description": body.description.strip(), "amount_cents": amount,
            "day_of_month": body.day_of_month, "active": body.active}


@router.post("/companies/{company_id}/recurring")
async def create_recurring(company_id: str, body: RecurringIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_deadlines")
    r = {"id": new_id(), "company_id": company_id, **_recurring_doc(body), "created_at": now_iso()}
    await get_db().recurring.insert_one(dict(r))
    await audit.log(user, "ricorrenza_creata", company_id, r["description"])
    return r


@router.put("/recurring/{recurring_id}")
async def update_recurring(recurring_id: str, body: RecurringIn, user: dict = Depends(get_current_user)):
    r, _ = await load("recurring", recurring_id, user, "manage_deadlines")
    await get_db().recurring.update_one({"id": recurring_id}, {"$set": _recurring_doc(body)})
    return {"ok": True}


@router.delete("/recurring/{recurring_id}")
async def delete_recurring(recurring_id: str, user: dict = Depends(get_current_user)):
    r, _ = await load("recurring", recurring_id, user, "manage_deadlines")
    await get_db().recurring.delete_one({"id": recurring_id})
    await audit.log(user, "ricorrenza_eliminata", r["company_id"], r["description"])
    return {"ok": True}
