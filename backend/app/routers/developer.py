"""Area Sviluppatore: stato del sistema, errori tecnici e invito del titolare. Nessun dato delle aziende."""
import platform
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require_developer
from ..security import hash_token, new_invite_token
from ..services.errors import record_client_error
from ..utils import new_id, now_iso, now_utc

router = APIRouter(tags=["developer"])
STARTED = time.time()
INVITE_DAYS = 7


def developer(user: dict = Depends(get_current_user)) -> dict:
    require_developer(user)
    return user


class ClientErrorIn(BaseModel):
    message: str = ""
    stack: str = ""
    path: str = ""


class OwnerInviteIn(BaseModel):
    email: str
    name: str = ""


@router.post("/client-errors")
async def client_error(body: ClientErrorIn, user: dict = Depends(get_current_user)):
    await record_client_error(body.message, body.stack, body.path)
    return {"ok": True}


@router.get("/developer/status")
async def status(user: dict = Depends(developer)):
    db = get_db()
    t0 = time.perf_counter()
    db_ok = True
    try:
        await db.command("ping")
    except Exception:  # noqa: BLE001
        db_ok = False
    ping_ms = round((time.perf_counter() - t0) * 1000, 1)
    day_ago = (now_utc() - timedelta(days=1)).isoformat()
    jobs = await db.jobs.find({}, {"_id": 0, "name": 1, "period": 1, "started_at": 1, "finished_at": 1, "error": 1}).to_list(50)
    return {
        "server_time": now_iso(),
        "uptime_seconds": int(time.time() - STARTED),
        "python": platform.python_version(),
        "database": {"ok": db_ok, "ping_ms": ping_ms},
        "titolare_presente": await db.users.count_documents({"is_owner": True, "is_developer": {"$ne": True}}) > 0,
        "providers": {
            "banche": settings.banking_provider, "sdi": settings.sdi_provider, "pagamenti": settings.payments_provider,
            "email": settings.email_provider, "whatsapp": settings.whatsapp_provider, "assistente": settings.ai_provider,
        },
        "sicurezza": {"2fa_per_pagamenti": settings.require_2fa_for_payments, "dati_demo": settings.seed_demo},
        "scheduler": {"attivo": settings.scheduler_enabled, "attivita": [
            {"nome": j["name"], "periodo": j.get("period"), "inizio": j.get("started_at"), "fine": j.get("finished_at"),
             "esito": "errore" if j.get("error") else ("ok" if j.get("finished_at") else "in corso")} for j in jobs]},
        "errori": {
            "aperti": await db.system_errors.count_documents({"resolved": False}),
            "ultime_24h": await db.system_errors.count_documents({"last_at": {"$gte": day_ago}}),
        },
    }


@router.get("/developer/errors")
async def list_errors(user: dict = Depends(developer)):
    return await get_db().system_errors.find({}, {"_id": 0}).sort("last_at", -1).to_list(200)


@router.post("/developer/errors/{error_id}/resolve")
async def resolve_error(error_id: str, user: dict = Depends(developer)):
    res = await get_db().system_errors.update_one({"id": error_id}, {"$set": {"resolved": True}})
    if not res.matched_count:
        raise HTTPException(404, "Errore non trovato.")
    return {"ok": True}


@router.delete("/developer/errors")
async def clear_errors(user: dict = Depends(developer)):
    await get_db().system_errors.delete_many({"resolved": True})
    return {"ok": True}


@router.get("/developer/owner-invites")
async def list_owner_invites(user: dict = Depends(developer)):
    return await get_db().invites.find(
        {"owner_invite": True, "accepted_at": None},
        {"_id": 0, "id": 1, "email": 1, "name": 1, "created_at": 1, "expires_at": 1},
    ).sort("created_at", -1).to_list(50)


@router.post("/developer/owner-invites")
async def create_owner_invite(body: OwnerInviteIn, user: dict = Depends(developer)):
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Email non valida.")
    db = get_db()
    target = await db.users.find_one({"email": email})
    if target and target.get("is_developer"):
        raise HTTPException(400, "L'account sviluppatore non può diventare titolare.")
    token = new_invite_token()
    invite = {
        "id": new_id(), "email": email, "name": body.name.strip(), "role": "titolare", "company_ids": [],
        "owner_invite": True, "token_hash": hash_token(token), "invited_by": user["id"], "created_at": now_iso(),
        "expires_at": (now_utc() + timedelta(days=INVITE_DAYS)).isoformat(), "accepted_at": None,
    }
    await db.invites.insert_one(invite)
    await audit.log(user, "invito_titolare_creato", target=email)
    return {"id": invite["id"], "email": email, "expires_at": invite["expires_at"],
            "invite_url": f"{settings.frontend_url}/invito/{token}"}


@router.delete("/developer/owner-invites/{invite_id}")
async def cancel_owner_invite(invite_id: str, user: dict = Depends(developer)):
    db = get_db()
    invite = await db.invites.find_one({"id": invite_id, "owner_invite": True, "accepted_at": None})
    if not invite:
        raise HTTPException(404, "Invito non trovato.")
    await db.invites.delete_one({"id": invite_id})
    await audit.log(user, "invito_titolare_annullato", target=invite["email"])
    return {"ok": True}
