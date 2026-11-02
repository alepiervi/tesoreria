"""Assistente (domande in italiano), lettura degli scontrini, aiuto nella riconciliazione."""
from datetime import timedelta

from bson import Binary
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require
from ..integrations.ai import get_ai
from ..services import reconciliation as rec
from ..services.invoices import payable
from ..services.assistant_tools import Tools
from ..utils import new_id, now_iso, parse_date, to_cents
from .common import companies_with, load

router = APIRouter(tags=["assistant"])

EXAMPLES = [
    "Quanto ho in banca in tutto?",
    "Quanto ha speso Alfa di carburante quest'anno?",
    "Quali clienti mi devono più di 5.000 €?",
    "Cosa devo pagare nei prossimi 7 giorni?",
    "Andrò in rosso nelle prossime settimane?",
    "Quanta IVA devo versare?",
]
RECEIPT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


class AskIn(BaseModel):
    question: str
    company_id: str | None = None
    history: list[dict] = []


class ReceiptUpdate(BaseModel):
    date: str = ""
    total: str = ""
    merchant: str = ""


class ReceiptLink(BaseModel):
    transaction_id: str


@router.get("/assistant/status")
async def status(user: dict = Depends(get_current_user)):
    ai = get_ai()
    return {"enabled": ai is not None, "provider": ai.name if ai else "none", "examples": EXAMPLES,
            "reads_receipts": bool(ai and ai.name == "anthropic")}


@router.post("/assistant/ask")
async def ask(body: AskIn, user: dict = Depends(get_current_user)):
    ai = get_ai()
    if ai is None:
        raise HTTPException(400, "L'assistente è disattivato.")
    question = body.question.strip()
    if not question or len(question) > 1000:
        raise HTTPException(400, "Scrivi una domanda (al massimo 1000 caratteri).")
    scope = await companies_with(user, "use_assistant", body.company_id)
    if not scope:
        raise HTTPException(403, "Il tuo ruolo non permette di usare l'assistente.")
    try:
        result = await ai.ask(Tools(get_db(), scope), question, body.history)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    await get_db().assistant_log.insert_one({"id": new_id(), "user_id": user["id"], "question": question,
                                             "tools": result.get("tools", []), "provider": ai.name, "at": now_iso()})
    return {"answer": result["answer"], "tools": result.get("tools", []), "provider": ai.name}


@router.post("/transactions/{tx_id}/ai-suggest")
async def ai_suggest(tx_id: str, user: dict = Depends(get_current_user)):
    tx, _ = await load("transactions", tx_id, user, "view")
    await require(user, tx["company_id"], "use_assistant")
    ai = get_ai()
    if ai is None:
        raise HTTPException(400, "L'assistente è disattivato.")
    invoices, deadlines = await rec.open_targets(get_db(), tx["company_id"])
    direction = "attiva" if tx["amount_cents"] > 0 else "passiva"
    items = [rec._inv_target(i, payable(i) - i.get("paid_cents", 0)) for i in invoices if i["direction"] == direction]
    items += [{"type": "deadline", "id": d["id"], "label": d["description"], "amount_cents": d["amount_cents"],
               "due_date": d["due_date"]} for d in deadlines if (d["kind"] == "incasso") == (tx["amount_cents"] > 0)]
    amount = abs(tx["amount_cents"])
    items.sort(key=lambda i: abs(i["amount_cents"] - amount))
    try:
        result = await ai.suggest_match(tx, items[:40])
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return result or {"targets": [], "explanation": "Nessun suggerimento disponibile.", "confidence": "bassa"}


# ---------- Scontrini ----------

async def _receipt_candidates(db, company_id: str, receipt: dict) -> list[dict]:
    if not receipt.get("total_cents") or not receipt.get("date"):
        return []
    d = parse_date(receipt["date"])
    q = {"company_id": company_id, "amount_cents": -receipt["total_cents"], "status": "da_riconciliare",
         "date": {"$gte": (d - timedelta(days=2)).isoformat(), "$lte": (d + timedelta(days=7)).isoformat()}}
    return await db.transactions.find(q, {"_id": 0, "id": 1, "date": 1, "description": 1, "amount_cents": 1}).to_list(10)


def _public(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in {"_id", "data"}}


@router.get("/companies/{company_id}/receipts")
async def list_receipts(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    return await get_db().documents.find({"company_id": company_id, "category": "Scontrino"}, {"_id": 0, "data": 0}) \
        .sort("created_at", -1).to_list(500)


@router.post("/companies/{company_id}/receipts")
async def upload_receipt(company_id: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    await require(user, company_id, "upload_documents")
    mime = file.content_type or ""
    if mime not in RECEIPT_TYPES:
        raise HTTPException(400, "Carica una foto (JPG, PNG) o un PDF dello scontrino.")
    data = await file.read(settings.max_document_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_document_mb * 1024 * 1024:
        raise HTTPException(413, f"Il file supera {settings.max_document_mb} MB.")
    extracted = None
    ai = get_ai()
    if ai:
        try:
            extracted = await ai.read_receipt(data, mime)
        except Exception:  # noqa: BLE001 - se la lettura automatica fallisce si compila a mano
            extracted = None
    receipt = {"date": None, "total_cents": None, "merchant": "", "vat_cents": None, "read_automatically": bool(extracted),
               "transaction_id": None}
    if extracted:
        try:
            receipt["date"] = parse_date(str(extracted.get("data"))).isoformat() if extracted.get("data") else None
        except ValueError:
            pass
        if extracted.get("totale") is not None:
            receipt["total_cents"] = round(float(extracted["totale"]) * 100)
        receipt["merchant"] = str(extracted.get("esercente") or "")[:120]
        if extracted.get("iva") is not None:
            receipt["vat_cents"] = round(float(extracted["iva"]) * 100)
    doc = {"id": new_id(), "company_id": company_id, "name": file.filename or "scontrino", "category": "Scontrino",
           "note": "", "period": "", "content_type": mime, "size": len(data), "uploaded_by": user["id"],
           "uploaded_by_name": user.get("name", ""), "created_at": now_iso(), "receipt": receipt}
    db = get_db()
    await db.documents.insert_one({**doc, "data": Binary(data)})
    await audit.log(user, "scontrino_caricato", company_id, doc["name"])
    return {"document": doc, "candidates": await _receipt_candidates(db, company_id, receipt)}


@router.put("/receipts/{document_id}")
async def update_receipt(document_id: str, body: ReceiptUpdate, user: dict = Depends(get_current_user)):
    doc, _ = await load("documents", document_id, user, "upload_documents")
    if doc.get("category") != "Scontrino":
        raise HTTPException(400, "Il documento non è uno scontrino.")
    receipt = dict(doc.get("receipt") or {})
    try:
        if body.date:
            receipt["date"] = parse_date(body.date).isoformat()
        if body.total:
            receipt["total_cents"] = to_cents(body.total)
    except ValueError:
        raise HTTPException(400, "Data o importo non validi.")
    if body.merchant:
        receipt["merchant"] = body.merchant.strip()[:120]
    db = get_db()
    await db.documents.update_one({"id": document_id}, {"$set": {"receipt": receipt}})
    return {"receipt": receipt, "candidates": await _receipt_candidates(db, doc["company_id"], receipt)}


@router.post("/receipts/{document_id}/link")
async def link_receipt(document_id: str, body: ReceiptLink, user: dict = Depends(get_current_user)):
    doc, _ = await load("documents", document_id, user, "upload_documents")
    tx, _ = await load("transactions", body.transaction_id, user, "reconcile")
    if tx["company_id"] != doc["company_id"]:
        raise HTTPException(400, "Scontrino e movimento devono essere della stessa azienda.")
    if tx["status"] != "da_riconciliare":
        raise HTTPException(400, "Il movimento è già sistemato.")
    receipt = doc.get("receipt") or {}
    db = get_db()
    await db.transactions.update_one({"id": tx["id"]}, {"$set": {
        "status": "escluso", "exclusion_reason": f"Scontrino {receipt.get('merchant') or doc['name']}".strip(),
        "receipt_document_id": document_id, "reconciled_by": user["id"], "reconciled_by_name": user.get("name", ""),
        "reconciled_at": now_iso()}})
    await db.documents.update_one({"id": document_id}, {"$set": {"receipt.transaction_id": tx["id"]}})
    from ..services.accounting import sync_source
    await sync_source(db, "transaction", tx["id"])
    await audit.log(user, "scontrino_abbinato", tx["company_id"], tx["description"])
    return {"ok": True}
