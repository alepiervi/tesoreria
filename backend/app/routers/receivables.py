from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..integrations.messaging import send_email
from ..services.invoices import norm_vat, payable
from ..services.receivables import aging, reminder_draft
from ..utils import new_id, now_iso
from .common import companies_with, load

router = APIRouter(tags=["receivables"])


class ContactIn(BaseModel):
    vat: str = ""
    name: str
    email: str = ""
    phone: str = ""


class ReminderIn(BaseModel):
    to: str
    subject: str
    body: str
    level: int = 1
    attach_xml: bool = True
    attach_qr: bool = True
    save_email: bool = True


async def _payment_iban(db, company: dict) -> str:
    if company.get("reminder_iban"):
        return company["reminder_iban"]
    acc = await db.bank_accounts.find_one({"company_id": company["id"], "status": "attivo", "iban": {"$nin": ["", None]}})
    return acc["iban"] if acc else ""


@router.get("/receivables")
async def receivables(direction: str = "attiva", company_id: str | None = None,
                      include_intercompany: bool = False, user: dict = Depends(get_current_user)):
    if direction not in {"attiva", "passiva"}:
        raise HTTPException(400, "Direzione non valida.")
    scope = await companies_with(user, "view", company_id)
    result = await aging(get_db(), list(scope), {k: v["name"] for k, v in scope.items()}, direction, include_intercompany)
    for p in result["parties"]:
        p["can_remind"] = "send_reminders" in scope[p["company_id"]]["permissions"]
    return result


@router.put("/companies/{company_id}/contacts")
async def save_contact(company_id: str, body: ContactIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "send_reminders")
    email = body.email.strip()
    if email and "@" not in email:
        raise HTTPException(400, "Email non valida.")
    key = norm_vat(body.vat) or body.name.strip().lower()
    db = get_db()
    await db.contacts.update_one({"company_id": company_id, "vat_key": key}, {"$set": {
        "company_id": company_id, "vat_key": key, "name": body.name.strip(), "email": email,
        "phone": body.phone.strip(), "updated_at": now_iso()}, "$setOnInsert": {"id": new_id()}}, upsert=True)
    return {"ok": True}


@router.get("/invoices/{invoice_id}/reminder-draft")
async def draft(invoice_id: str, level: int | None = None, user: dict = Depends(get_current_user)):
    inv, _ = await load("invoices", invoice_id, user, "send_reminders")
    if inv["direction"] != "attiva":
        raise HTTPException(400, "Si possono sollecitare solo le fatture emesse ai clienti.")
    db = get_db()
    company = await db.companies.find_one({"id": inv["company_id"]}, {"_id": 0})
    level = level or min(3, len(inv.get("reminders") or []) + 1)
    subject, body = reminder_draft(company, inv, level, await _payment_iban(db, company))
    contact = await db.contacts.find_one({"company_id": inv["company_id"],
                                          "vat_key": norm_vat(inv.get("counterparty_vat")) or inv["counterparty_name"].lower()})
    iban = await _payment_iban(db, company)
    residual = payable(inv) - inv.get("paid_cents", 0)
    from ..services.epc import payload
    return {"to": (contact or {}).get("email", ""), "subject": subject, "body": body, "level": level,
            "has_xml": inv.get("has_xml", False), "previous": inv.get("reminders") or [],
            "iban": iban, "amount_cents": residual,
            "qr_payload": payload(company["name"], iban, residual, f"Saldo fattura {inv['number']}") if iban and residual > 0 else None}


@router.post("/invoices/{invoice_id}/reminder")
async def send_reminder(invoice_id: str, body: ReminderIn, user: dict = Depends(get_current_user)):
    inv, _ = await load("invoices", invoice_id, user, "send_reminders")
    if inv["direction"] != "attiva" or inv["status"] == "pagata":
        raise HTTPException(400, "La fattura non è un credito aperto.")
    db = get_db()
    attachments = []
    if body.attach_xml:
        x = await db.invoice_xml.find_one({"invoice_id": invoice_id})
        if x:
            attachments.append((f"fattura_{inv['number'].replace('/', '-')}.xml", x["xml"].encode("utf-8"), "application/xml"))
    company = await db.companies.find_one({"id": inv["company_id"]}, {"_id": 0})
    iban = await _payment_iban(db, company)
    residual = payable(inv) - inv.get("paid_cents", 0)
    text = body.body
    if body.attach_qr and iban and residual > 0:
        from ..services.epc import payment_notice_pdf
        from ..utils import parse_date
        pdf = payment_notice_pdf(company, inv["counterparty_name"], iban, residual, f"Saldo fattura {inv['number']}",
                                 parse_date(inv["due_date"]).strftime("%d/%m/%Y"))
        attachments.append((f"avviso_pagamento_{inv['number'].replace('/', '-')}.pdf", pdf, "application/pdf"))
        text += "\n\nIn allegato l'avviso di pagamento con il QR code: inquadrandolo con l'app della banca il bonifico si compila da solo."
    result = await send_email(body.to.strip(), body.subject, text, attachments=attachments,
                              meta={"kind": "sollecito", "invoice_id": invoice_id})
    if result["status"] == "errore":
        raise HTTPException(400, result["error"])
    reminder = {"at": now_iso(), "level": max(1, min(3, body.level)), "to": body.to.strip(), "by": user["id"],
                "by_name": user.get("name", ""), "status": result["status"]}
    await db.invoices.update_one({"id": invoice_id}, {"$push": {"reminders": reminder}})
    if body.save_email:
        key = norm_vat(inv.get("counterparty_vat")) or inv["counterparty_name"].lower()
        await db.contacts.update_one({"company_id": inv["company_id"], "vat_key": key}, {"$set": {
            "company_id": inv["company_id"], "vat_key": key, "name": inv["counterparty_name"],
            "email": body.to.strip(), "updated_at": now_iso()}, "$setOnInsert": {"id": new_id(), "phone": ""}}, upsert=True)
    await audit.log(user, "sollecito_inviato", inv["company_id"], f"{inv['number']} {inv['counterparty_name']}",
                    {"livello": reminder["level"], "a": reminder["to"]})
    return {"ok": True, "status": result["status"]}
