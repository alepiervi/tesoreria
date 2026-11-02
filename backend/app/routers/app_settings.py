"""Impostazioni del titolare: casella email (es. Aruba) e stato dei collegamenti."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit
from ..config import settings
from ..deps import get_current_user, require_owner
from ..integrations.messaging import send_email
from ..services.app_settings import email_mode, public_email_config, save_email_config
from ..utils import now_iso
from ..db import get_db

router = APIRouter(tags=["settings"])


class EmailConfigIn(BaseModel):
    enabled: bool = True
    host: str = Field(min_length=3, max_length=200)
    port: int = Field(ge=1, le=65535)
    ssl: bool = True
    user: str = Field(min_length=3, max_length=200)
    password: str | None = Field(default=None, max_length=200)
    from_addr: str = Field(min_length=3, max_length=200)
    from_name: str = Field(default="Nureal-Amministrazione", max_length=120)


class TestIn(BaseModel):
    to: str = Field(max_length=254)


async def features() -> dict:
    return {
        "bank_auto": settings.banking_provider != "none",
        "sdi_auto": settings.sdi_provider != "none",
        "payments_auto": settings.payments_provider != "none",
        "whatsapp": settings.whatsapp_provider != "none",
        "email": await email_mode() == "smtp",
        "ai": settings.ai_provider,
    }


def owner(user: dict = Depends(get_current_user)) -> dict:
    require_owner(user)
    return user


@router.get("/settings/email")
async def get_email(user: dict = Depends(owner)):
    return await public_email_config()


@router.put("/settings/email")
async def put_email(body: EmailConfigIn, user: dict = Depends(owner)):
    current = await public_email_config()
    if not body.password and not current["has_password"]:
        raise HTTPException(400, "Inserisci la password della casella.")
    if "@" not in body.from_addr:
        raise HTTPException(400, "Indirizzo mittente non valido.")
    data = body.model_dump(exclude={"password"})
    data["host"] = data["host"].strip()
    data["user"] = data["user"].strip()
    data["from_addr"] = data["from_addr"].strip()
    await save_email_config(data, body.password, user["id"])
    await audit.log(user, "email_configurata", details={"server": data["host"], "utente": data["user"]})
    return await public_email_config()


@router.post("/settings/email/test")
async def test_email(body: TestIn, user: dict = Depends(owner)):
    if await email_mode() != "smtp":
        raise HTTPException(400, "Salva e attiva prima la casella email.")
    result = await send_email(body.to.strip(), "Prova invio · Nureal-Amministrazione",
                              "Se leggi questo messaggio, l'invio delle email da Nureal-Amministrazione funziona.")
    await get_db().app_settings.update_one({"id": "email"}, {"$set": {"last_test": {
        "at": now_iso(), "ok": result["status"] == "inviato", "error": result.get("error")}}})
    if result["status"] != "inviato":
        raise HTTPException(400, result.get("error") or "Invio non riuscito.")
    return {"ok": True}
