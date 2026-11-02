"""Note e richieste di chiarimento su movimenti, fatture e scadenze."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..utils import new_id, now_iso
from .common import companies_with, load

router = APIRouter(tags=["notes"])

TARGETS = {"transaction": "transactions", "invoice": "invoices", "deadline": "deadlines"}


class NoteIn(BaseModel):
    target_type: str
    target_id: str
    text: str
    is_question: bool = False


@router.get("/notes")
async def list_notes(target_type: str, target_id: str, user: dict = Depends(get_current_user)):
    if target_type not in TARGETS:
        raise HTTPException(400, "Tipo non valido.")
    await load(TARGETS[target_type], target_id, user, "view")
    return await get_db().notes.find({"target_type": target_type, "target_id": target_id}, {"_id": 0}) \
        .sort("created_at", 1).to_list(500)


@router.post("/notes")
async def add_note(body: NoteIn, user: dict = Depends(get_current_user)):
    if body.target_type not in TARGETS:
        raise HTTPException(400, "Tipo non valido.")
    if not body.text.strip():
        raise HTTPException(400, "Scrivi il testo della nota.")
    target, _ = await load(TARGETS[body.target_type], body.target_id, user, "note")
    note = {
        "id": new_id(), "company_id": target["company_id"], "target_type": body.target_type,
        "target_id": body.target_id, "target_label": target.get("description") or target.get("number", ""),
        "author_id": user["id"], "author_name": user.get("name") or user["email"],
        "text": body.text.strip(), "is_question": body.is_question, "resolved": False, "created_at": now_iso(),
    }
    db = get_db()
    await db.notes.insert_one(dict(note))
    await audit.log(user, "richiesta_chiarimento" if body.is_question else "nota_aggiunta",
                    target["company_id"], note["target_label"])
    # Avvisa le altre persone che seguono l'azienda (una domanda è importante, una nota no)
    from ..services.notifications import notify, users_with
    others = [u for u in await users_with(db, target["company_id"], "note") if u["id"] != user["id"]]
    if body.is_question or await db.notes.count_documents({"target_id": body.target_id, "is_question": True, "resolved": False}):
        company = await db.companies.find_one({"id": target["company_id"]}, {"name": 1})
        await notify(db, others, kind="chiarimento", company_id=target["company_id"], link="/chiarimenti",
                     important=body.is_question,
                     title=("Nuova domanda" if body.is_question else "Risposta a un chiarimento") + f" · {company['name']}",
                     body=f"{note['author_name']} su \"{note['target_label'][:80]}\": {note['text'][:200]}")
    return note


@router.post("/notes/{note_id}/resolve")
async def resolve(note_id: str, user: dict = Depends(get_current_user)):
    note, _ = await load("notes", note_id, user, "note")
    await get_db().notes.update_one({"id": note_id}, {"$set": {"resolved": True, "resolved_by": user["id"],
                                                               "resolved_at": now_iso()}})
    return {"ok": True}


@router.get("/questions")
async def open_questions(company_id: str | None = None, user: dict = Depends(get_current_user)):
    """Richieste di chiarimento ancora aperte (es. del commercialista al titolare)."""
    scope = await companies_with(user, "view", company_id)
    items = await get_db().notes.find(
        {"company_id": {"$in": list(scope)}, "is_question": True, "resolved": False}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    for n in items:
        n["company_name"] = scope[n["company_id"]]["name"]
    return items
