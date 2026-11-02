from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, user_permissions_by_company
from ..security import (
    create_access_token, create_setup_token, decode_access_token, hash_password, hash_token, new_recovery_codes,
    new_totp_secret, normalize_recovery_code, totp_step, totp_uri, validate_password_strength, verify_password,
)
from ..utils import now_iso, now_utc

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    totp_code: str | None = Field(default=None, max_length=20)


class CodeIn(BaseModel):
    code: str = Field(max_length=20)


class SetupIn(BaseModel):
    setup_token: str
    code: str | None = Field(default=None, max_length=20)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "is_owner": user.get("is_owner", False) and not user.get("is_developer", False),
        "is_developer": user.get("is_developer", False),
        "totp_enabled": user.get("totp_enabled", False),
        "recovery_codes_left": len(user.get("recovery_codes") or []),
        "twofa_required": settings.require_2fa_login,
    }


async def fail_attempt(db, user: dict, action: str, message: str):
    """Ogni tentativo sbagliato (password o codice) conta per il blocco dell'account."""
    failed = user.get("failed_logins", 0) + 1
    update = {"failed_logins": failed}
    if failed >= settings.max_failed_logins:
        update = {"failed_logins": 0,
                  "locked_until": (now_utc() + timedelta(minutes=settings.lockout_minutes)).isoformat()}
    await db.users.update_one({"id": user["id"]}, {"$set": update})
    await audit.log(user, action)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, message)


async def check_second_factor(db, user: dict, code: str, allow_recovery: bool = True) -> str | None:
    """Verifica un codice dell'app (una sola volta per codice) o un codice di recupero. Restituisce il tipo usato."""
    step = totp_step(user.get("totp_secret"), code)
    if step is not None:
        res = await db.users.update_one(
            {"id": user["id"], "$or": [{"totp_last_step": {"$exists": False}}, {"totp_last_step": {"$lt": step}}]},
            {"$set": {"totp_last_step": step}})
        return "app" if res.modified_count else None
    if not allow_recovery:
        return None
    hashed = hash_token(normalize_recovery_code(code))
    res = await db.users.update_one({"id": user["id"], "recovery_codes": hashed}, {"$pull": {"recovery_codes": hashed}})
    return "recupero" if res.modified_count else None


def _session(user: dict) -> dict:
    return {"access_token": create_access_token(user["id"], user.get("token_version", 0)),
            "token_type": "bearer", "user": public_user(user)}


async def _login_ok(db, user: dict, method: str) -> dict:
    await db.users.update_one({"id": user["id"]},
                              {"$set": {"failed_logins": 0, "locked_until": None, "last_login_at": now_iso()}})
    await audit.log(user, "login", details={"secondo_fattore": method})
    return _session(user)


@router.post("/login")
async def login(body: LoginIn):
    db = get_db()
    email = body.email.strip().lower()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o password non corretti.")

    locked_until = user.get("locked_until")
    if locked_until and datetime.fromisoformat(locked_until) > now_utc():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Troppi tentativi falliti. Riprova tra qualche minuto.")

    if not verify_password(body.password, user["password_hash"]):
        await fail_attempt(db, user, "login_fallito", "Email o password non corretti.")

    if user.get("totp_enabled"):
        if not body.totp_code:
            # Il frontend riconosce questo codice e chiede il codice a 6 cifre
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "2fa_required")
        method = await check_second_factor(db, user, body.totp_code)
        if not method:
            await fail_attempt(db, user, "codice_2fa_errato", "Codice di verifica non valido o già usato.")
        return await _login_ok(db, user, method)

    if settings.require_2fa_login:
        # Password giusta ma verifica in due passaggi non ancora attiva: niente sessione, solo l'attivazione
        return {"setup_required": True, "setup_token": create_setup_token(user["id"], user.get("token_version", 0)),
                "email": user["email"]}
    return await _login_ok(db, user, "nessuno")


async def _setup_user(token: str) -> dict:
    try:
        payload = decode_access_token(token, typ="2fa_setup")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Attivazione scaduta: accedi di nuovo.")
    user = await get_db().users.find_one({"id": payload.get("sub")})
    if not user or not user.get("active", True) or payload.get("ver", 0) != user.get("token_version", 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Attivazione non valida: accedi di nuovo.")
    if user.get("totp_enabled"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La verifica in due passaggi è già attiva: accedi con il codice.")
    return user


async def _start_setup(user: dict) -> dict:
    secret = new_totp_secret()
    await get_db().users.update_one({"id": user["id"]}, {"$set": {"totp_pending_secret": secret}})
    return {"secret": secret, "otpauth_uri": totp_uri(secret, user["email"])}


async def _finish_setup(user: dict, code: str) -> list[str]:
    db = get_db()
    secret = user.get("totp_pending_secret")
    step = totp_step(secret, code or "")
    if step is None:
        await fail_attempt(db, user, "codice_2fa_errato", "Codice non valido. Controlla l'ora del telefono e riprova.")
    codes = new_recovery_codes()
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "totp_secret": secret, "totp_enabled": True, "totp_pending_secret": None, "totp_last_step": step,
        "recovery_codes": [hash_token(c) for c in codes], "failed_logins": 0}})
    await audit.log(user, "2fa_attivata")
    return codes


@router.post("/2fa/enroll/start")
async def enroll_start(body: SetupIn):
    return await _start_setup(await _setup_user(body.setup_token))


@router.post("/2fa/enroll/finish")
async def enroll_finish(body: SetupIn):
    user = await _setup_user(body.setup_token)
    codes = await _finish_setup(user, body.code)
    out = await _login_ok(get_db(), user, "attivazione")
    out["user"]["totp_enabled"] = True
    out["user"]["recovery_codes_left"] = len(codes)
    out["recovery_codes"] = codes
    return out


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
    return await _start_setup(user)


@router.post("/2fa/enable")
async def totp_enable(body: CodeIn, user: dict = Depends(get_current_user)):
    full = await get_db().users.find_one({"id": user["id"]})
    if not full.get("totp_pending_secret"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Avvia prima l'attivazione.")
    return {"ok": True, "recovery_codes": await _finish_setup(full, body.code)}


@router.post("/2fa/recovery-codes")
async def regenerate_recovery_codes(body: CodeIn, user: dict = Depends(get_current_user)):
    """Nuovi codici di recupero (i vecchi smettono di funzionare). Serve un codice dell'app."""
    db = get_db()
    full = await db.users.find_one({"id": user["id"]})
    if not full.get("totp_enabled") or not await check_second_factor(db, full, body.code, allow_recovery=False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Codice dell'app non valido.")
    codes = new_recovery_codes()
    await db.users.update_one({"id": user["id"]}, {"$set": {"recovery_codes": [hash_token(c) for c in codes]}})
    await audit.log(user, "codici_recupero_rigenerati")
    return {"recovery_codes": codes}


@router.post("/2fa/disable")
async def totp_disable(body: CodeIn, user: dict = Depends(get_current_user)):
    if settings.require_2fa_login:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La verifica in due passaggi è obbligatoria e non si può disattivare.")
    db = get_db()
    full = await db.users.find_one({"id": user["id"]})
    if not full.get("totp_enabled") or not await check_second_factor(db, full, body.code, allow_recovery=False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Codice non valido.")
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"totp_secret": None, "totp_enabled": False, "recovery_codes": []}})
    await audit.log(user, "2fa_disattivata")
    return {"ok": True}
