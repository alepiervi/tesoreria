from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..config import settings
from ..services.app_settings import email_mode
from ..db import get_db
from ..deps import get_current_user, require_owner
from ..services import notifications as svc
from ..utils import now_iso

router = APIRouter(tags=["notifications"])


class PrefsIn(BaseModel):
    email_alerts: bool = True
    whatsapp_alerts: bool = False
    whatsapp_number: str = ""
    weekly_digest: bool = True
    monthly_report: bool = False


@router.get("/notifications")
async def list_notifications(limit: int = Query(50, le=200), user: dict = Depends(get_current_user)):
    db = get_db()
    items = await db.notifications.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    unread = await db.notifications.count_documents({"user_id": user["id"], "read_at": None})
    return {"items": items, "unread": unread}


@router.get("/notifications/unread-count")
async def unread_count(user: dict = Depends(get_current_user)):
    return {"unread": await get_db().notifications.count_documents({"user_id": user["id"], "read_at": None})}


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: str, user: dict = Depends(get_current_user)):
    await get_db().notifications.update_one({"id": notification_id, "user_id": user["id"]}, {"$set": {"read_at": now_iso()}})
    return {"ok": True}


@router.post("/notifications/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    await get_db().notifications.update_many({"user_id": user["id"], "read_at": None}, {"$set": {"read_at": now_iso()}})
    return {"ok": True}


@router.get("/me/notification-settings")
async def get_prefs(user: dict = Depends(get_current_user)):
    return {**svc.prefs_of(user), "email": user["email"],
            "channels": {"email": await email_mode(), "whatsapp": settings.whatsapp_provider}}


@router.put("/me/notification-settings")
async def set_prefs(body: PrefsIn, user: dict = Depends(get_current_user)):
    number = body.whatsapp_number.strip().replace(" ", "")
    if body.whatsapp_alerts and not number:
        raise HTTPException(400, "Per gli avvisi WhatsApp indica il numero, con il prefisso (es. +39 333 1234567).")
    if number and not number.lstrip("+").isdigit():
        raise HTTPException(400, "Numero WhatsApp non valido.")
    await get_db().users.update_one({"id": user["id"]}, {"$set": {"notify": {**body.model_dump(), "whatsapp_number": number}}})
    return {"ok": True}


@router.post("/me/notification-settings/test")
async def test_prefs(user: dict = Depends(get_current_user)):
    """Manda subito a se stessi il riepilogo settimanale (per vedere come arriva)."""
    sent = await svc.send_weekly_digests(get_db(), only_user_id=user["id"])
    return {"sent": sent, "mode": await email_mode()}


@router.post("/notifications/run-now")
async def run_now(user: dict = Depends(get_current_user)):
    """Esegue subito i controlli giornalieri (di norma partono da soli ogni mattina)."""
    require_owner(user)
    return {"created": await svc.run_daily_alerts(get_db())}


@router.get("/outbox")
async def outbox(limit: int = Query(50, le=200), user: dict = Depends(get_current_user)):
    """Messaggi inviati o, in modalità demo, simulati. Visibile solo al titolare."""
    require_owner(user)
    items = await get_db().outbox.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": items, "email_mode": await email_mode(), "whatsapp_mode": settings.whatsapp_provider}
