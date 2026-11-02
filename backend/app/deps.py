"""Dipendenze FastAPI: utente autenticato e controllo dei permessi per azienda."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_db
from .permissions import has_permission, permissions_for
from .security import decode_access_token
from .utils import clean

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Accesso richiesto.")
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione scaduta o non valida.")
    user = await get_db().users.find_one({"id": payload.get("sub")})
    if not user or not user.get("active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo.")
    if payload.get("ver", 0) != user.get("token_version", 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione non più valida.")
    return clean(user)


async def get_memberships(user_id: str) -> list[dict]:
    # Lo sviluppatore non ha mai accessi alle aziende, anche se qualcuno li inserisse a mano nel database
    if await get_db().users.count_documents({"id": user_id, "is_developer": True}) > 0:
        return []
    cursor = get_db().memberships.find({"user_id": user_id}, {"_id": 0})
    return await cursor.to_list(1000)


async def visible_company_ids(user: dict) -> list[str]:
    return [m["company_id"] for m in await get_memberships(user["id"])]


async def company_role(user: dict, company_id: str) -> str | None:
    m = await get_db().memberships.find_one({"user_id": user["id"], "company_id": company_id})
    return m["role"] if m else None


async def require(user: dict, company_id: str, permission: str) -> str:
    """Verifica che l'utente abbia il permesso sull'azienda. Restituisce il ruolo."""
    role = None if user.get("is_developer") else await company_role(user, company_id)
    if role is None:
        # 404 e non 403: chi non ha accesso non deve sapere che l'azienda esiste
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Azienda non trovata.")
    if not has_permission(role, permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non permette questa operazione.")
    return role


def require_owner(user: dict):
    if not user.get("is_owner") or user.get("is_developer"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Operazione riservata al titolare.")


def require_developer(user: dict):
    if not user.get("is_developer"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Operazione riservata allo sviluppatore.")


async def user_permissions_by_company(user: dict) -> dict[str, dict]:
    result = {}
    for m in await get_memberships(user["id"]):
        result[m["company_id"]] = {
            "role": m["role"],
            "permissions": sorted(permissions_for(m["role"])),
        }
    return result
