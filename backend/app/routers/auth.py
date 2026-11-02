from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, user_permissions_by_company
from ..security import (
    create_access_token, hash_password, new_totp_secret, totp_uri,
    validate_password_strength, verify_password, verify_totp,
)
from ..utils import now_iso, now_utc

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str
    totp_code: str | None = None


class CodeIn(BaseModel):
    code: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "is_owner": user.get("is_owner", False),
        "totp_enabled": user.get("totp_enabled", False),
    }


@router.post("/login")
async def login(body: LoginIn):
    db = get_db()
    email = body.email.strip().lower()
    user = await db.users.find_one({"email": email})
    generic_error = HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o password non corretti.")
    if not user or not user.get("active", True):
        raise generic_error

    locked_until = user.get("locked_until")
    if locked_until and datetime.fromisoformat(locked_until) > now_utc():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Troppi tentativi falliti. Riprova tra qualche minuto.")

    if not verify_password(body.password, user["password_hash"]):
        failed = user.get("failed_logins", 0) + 1
        update = {"failed_logins": failed}
        if failed >= settings.max_failed_logins:
            update = {"failed_logins": 0,
                      "locked_until": (now_utc() + timedelta(minutes=settings.lockout_minutes)).isoformat()}
        await db.users.update_one({"id": user["id"]}, {"$set": update})
        await audit.log(user, "login_fallito")
        raise generic_error

    if user.get("totp_enabled"):
        if not body.totp_code:
            # Il frontend riconosce questo codice e chiede il codice a 6 cifre
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "2fa_required")
        if not verify_totp(user.get("totp_secret"), body.totp_code):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Codice di verifica non valido.")

    await db.users.update_one({"id": user["id"]},
                              {"$set": {"failed_logins": 0, "locked_until": None, "last_login_at": now_iso()}})
    await audit.log(user, "login")
    token = create_access_token(user["id"], user.get("token_version", 0))
    return {"access_token": token, "token_type": "bearer", "user": public_user(user)}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"user": public_user(user), "companies": await user_permissions_by_company(user)}


@router.post("/logout-everywhere")
async def logout_everywhere(user: dict = Depends(get_current_user)):
    """Invalida tutti i token dell'utente (es. se pensa che la password sia compromessa)."""
    await get_db().users.update_one({"id": user["id"]}, {"$inc": {"token_version": 1}})
    await audit.log(user, "logout_ovunque")
    return {"ok": True}


@router.post("/password")
async def change_password(body: PasswordChangeIn, user: dict = Depends(get_current_user)):
    db = get_db()
    full = await db.users.find_one({"id": user["id"]})
    if not verify_password(body.current_password, full["password_hash"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La password attuale non è corretta.")
    problem = validate_password_strength(body.new_password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"password_hash": hash_password(body.new_password)},
        "$inc": {"token_version": 1},
    })
    await audit.log(user, "password_cambiata")
    updated = await db.users.find_one({"id": user["id"]})
    return {"access_token": create_access_token(user["id"], updated.get("token_version", 0))}


@router.post("/2fa/setup")
async def totp_setup(user: dict = Depends(get_current_user)):
    """Genera un segreto da aggiungere all'app di autenticazione (Google Authenticator, ecc.)."""
    if user.get("totp_enabled"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La verifica in due passaggi è già attiva.")
    secret = new_totp_secret()
    await get_db().users.update_one({"id": user["id"]}, {"$set": {"totp_pending_secret": secret}})
    return {"secret": secret, "otpauth_uri": totp_uri(secret, user["email"])}


@router.post("/2fa/enable")
async def totp_enable(body: CodeIn, user: dict = Depends(get_current_user)):
    db = get_db()
    full = await db.users.find_one({"id": user["id"]})
    secret = full.get("totp_pending_secret")
    if not secret or not verify_totp(secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Codice non valido. Riprova con un codice nuovo.")
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"totp_secret": secret, "totp_enabled": True, "totp_pending_secret": None}})
    await audit.log(user, "2fa_attivata")
    return {"ok": True}


@router.post("/2fa/disable")
async def totp_disable(body: CodeIn, user: dict = Depends(get_current_user)):
    db = get_db()
    full = await db.users.find_one({"id": user["id"]})
    if not full.get("totp_enabled") or not verify_totp(full.get("totp_secret"), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Codice non valido.")
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"totp_secret": None, "totp_enabled": False}})
    await audit.log(user, "2fa_disattivata")
    return {"ok": True}
