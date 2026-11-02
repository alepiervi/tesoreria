"""Utenti e accessi: inviti, ruoli per azienda, revoche."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import company_role, get_current_user, get_memberships, require, require_owner
from ..permissions import ROLES, has_permission
from ..security import (
    create_access_token, hash_password, hash_token, new_invite_token,
    validate_password_strength, verify_password,
)
from ..utils import clean, new_id, now_iso, now_utc

router = APIRouter(tags=["members"])

INVITE_DAYS = 7


class InviteIn(BaseModel):
    email: str
    name: str = ""
    role: str
    company_ids: list[str]


class RoleIn(BaseModel):
    role: str


class AcceptIn(BaseModel):
    name: str = ""
    password: str


async def _managed_company_ids(user: dict) -> list[str]:
    return [m["company_id"] for m in await get_memberships(user["id"])
            if has_permission(m["role"], "manage_members")]


def _check_role(role: str):
    if role not in ROLES:
        raise HTTPException(400, f"Ruolo non valido. Ruoli possibili: {', '.join(ROLES)}.")


@router.get("/roles")
async def list_roles():
    return [{"id": k, "label": v} for k, v in ROLES.items()]


@router.get("/members")
async def list_members(user: dict = Depends(get_current_user)):
    db = get_db()
    managed = await _managed_company_ids(user)
    if not managed:
        raise HTTPException(403, "Il tuo ruolo non permette di gestire gli accessi.")
    companies = {c["id"]: c["name"] for c in await db.companies.find({"id": {"$in": managed}}, {"_id": 0}).to_list(500)}
    memberships = await db.memberships.find({"company_id": {"$in": managed}}, {"_id": 0}).to_list(5000)
    by_user: dict[str, list] = {}
    for m in memberships:
        by_user.setdefault(m["user_id"], []).append(
            {"company_id": m["company_id"], "company_name": companies.get(m["company_id"], ""), "role": m["role"]})
    users = await db.users.find({"id": {"$in": list(by_user)}}, {"_id": 0}).to_list(1000)
    result = []
    for u in users:
        result.append({
            "id": u["id"], "email": u["email"], "name": u.get("name", ""),
            "is_owner": u.get("is_owner", False), "active": u.get("active", True),
            "totp_enabled": u.get("totp_enabled", False), "last_login_at": u.get("last_login_at"),
            "is_me": u["id"] == user["id"],
            "access": sorted(by_user[u["id"]], key=lambda a: a["company_name"]),
        })
    result.sort(key=lambda u: (not u["is_owner"], u["name"].lower()))
    return result


@router.put("/members/{user_id}/companies/{company_id}")
async def set_role(user_id: str, company_id: str, body: RoleIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_members")
    _check_role(body.role)
    db = get_db()
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(404, "Utente non trovato.")
    if user_id == user["id"] and body.role != "titolare":
        raise HTTPException(400, "Non puoi togliere a te stesso il ruolo di titolare.")
    existing = await db.memberships.find_one({"user_id": user_id, "company_id": company_id})
    if existing:
        await db.memberships.update_one({"id": existing["id"]}, {"$set": {"role": body.role}})
    else:
        await db.memberships.insert_one({"id": new_id(), "user_id": user_id, "company_id": company_id,
                                         "role": body.role, "created_at": now_iso()})
    await audit.log(user, "ruolo_impostato", company_id, target["email"], {"role": body.role})
    return {"ok": True}


@router.delete("/members/{user_id}/companies/{company_id}")
async def revoke(user_id: str, company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_members")
    db = get_db()
    if user_id == user["id"]:
        raise HTTPException(400, "Non puoi revocare il tuo stesso accesso.")
    membership = await db.memberships.find_one({"user_id": user_id, "company_id": company_id})
    if not membership:
        raise HTTPException(404, "Accesso non trovato.")
    if membership["role"] == "titolare":
        others = await db.memberships.count_documents({"company_id": company_id, "role": "titolare"})
        if others <= 1:
            raise HTTPException(400, "L'azienda deve avere almeno un titolare.")
    await db.memberships.delete_one({"id": membership["id"]})
    target = await db.users.find_one({"id": user_id})
    await audit.log(user, "accesso_revocato", company_id, target["email"] if target else user_id)
    return {"ok": True}


@router.post("/members/{user_id}/deactivate")
async def deactivate(user_id: str, user: dict = Depends(get_current_user)):
    """Blocca l'utente su tutte le aziende e chiude subito le sue sessioni."""
    require_owner(user)
    if user_id == user["id"]:
        raise HTTPException(400, "Non puoi disattivare te stesso.")
    db = get_db()
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(404, "Utente non trovato.")
    await db.users.update_one({"id": user_id}, {"$set": {"active": False}, "$inc": {"token_version": 1}})
    await audit.log(user, "utente_disattivato", target=target["email"])
    return {"ok": True}


@router.post("/members/{user_id}/activate")
async def activate(user_id: str, user: dict = Depends(get_current_user)):
    require_owner(user)
    db = get_db()
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(404, "Utente non trovato.")
    await db.users.update_one({"id": user_id}, {"$set": {"active": True}})
    await audit.log(user, "utente_riattivato", target=target["email"])
    return {"ok": True}


# ---------- Inviti ----------

@router.post("/invites")
async def create_invite(body: InviteIn, user: dict = Depends(get_current_user)):
    _check_role(body.role)
    if not body.company_ids:
        raise HTTPException(400, "Scegli almeno un'azienda.")
    for cid in body.company_ids:
        await require(user, cid, "manage_members")
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Email non valida.")
    token = new_invite_token()
    invite = {
        "id": new_id(), "email": email, "name": body.name.strip(), "role": body.role,
        "company_ids": body.company_ids, "token_hash": hash_token(token),
        "invited_by": user["id"], "created_at": now_iso(),
        "expires_at": (now_utc() + timedelta(days=INVITE_DAYS)).isoformat(), "accepted_at": None,
    }
    db = get_db()
    await db.invites.insert_one(invite)
    for cid in body.company_ids:
        await audit.log(user, "invito_creato", cid, email, {"role": body.role})
    # Il link va inviato all'utente. Quando collegherai un servizio email potrai spedirlo in automatico.
    invite_url = f"{settings.frontend_url}/invito/{token}"
    out = clean(invite)
    out.pop("token_hash")
    out["invite_url"] = invite_url
    return out


@router.get("/invites")
async def list_invites(user: dict = Depends(get_current_user)):
    managed = await _managed_company_ids(user)
    invites = await get_db().invites.find(
        {"accepted_at": None, "company_ids": {"$in": managed}}, {"_id": 0, "token_hash": 0}
    ).sort("created_at", -1).to_list(200)
    return invites


@router.delete("/invites/{invite_id}")
async def cancel_invite(invite_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    invite = await db.invites.find_one({"id": invite_id})
    if not invite:
        raise HTTPException(404, "Invito non trovato.")
    for cid in invite["company_ids"]:
        await require(user, cid, "manage_members")
    await db.invites.delete_one({"id": invite_id})
    await audit.log(user, "invito_annullato", target=invite["email"])
    return {"ok": True}


async def _valid_invite(token: str) -> dict:
    invite = await get_db().invites.find_one({"token_hash": hash_token(token)})
    if not invite or invite.get("accepted_at"):
        raise HTTPException(404, "Invito non valido o già usato.")
    if datetime.fromisoformat(invite["expires_at"]) < now_utc():
        raise HTTPException(410, "Invito scaduto. Chiedi al titolare di inviarne uno nuovo.")
    return invite


@router.get("/invites/token/{token}")
async def invite_info(token: str):
    invite = await _valid_invite(token)
    db = get_db()
    companies = await db.companies.find({"id": {"$in": invite["company_ids"]}}, {"_id": 0, "name": 1}).to_list(100)
    existing = await db.users.find_one({"email": invite["email"]})
    return {
        "email": invite["email"], "name": invite.get("name", ""), "role": invite["role"],
        "role_label": "Titolare del gruppo" if invite.get("owner_invite") else ROLES[invite["role"]],
        "owner_invite": invite.get("owner_invite", False),
        "companies": [c["name"] for c in companies],
        "existing_user": existing is not None,
    }


@router.post("/invites/token/{token}/accept")
async def accept_invite(token: str, body: AcceptIn):
    invite = await _valid_invite(token)
    db = get_db()
    user = await db.users.find_one({"email": invite["email"]})
    owner_invite = invite.get("owner_invite", False)
    if user and user.get("is_developer") and owner_invite:
        raise HTTPException(400, "L'account sviluppatore non può diventare titolare.")
    if user:
        if not verify_password(body.password, user["password_hash"]):
            raise HTTPException(401, "Password non corretta per questo account.")
        if owner_invite and not user.get("is_owner"):
            await db.users.update_one({"id": user["id"]}, {"$set": {"is_owner": True}})
    else:
        problem = validate_password_strength(body.password)
        if problem:
            raise HTTPException(400, problem)
        user = {
            "id": new_id(), "email": invite["email"], "name": body.name.strip() or invite.get("name", ""),
            "password_hash": hash_password(body.password), "is_owner": owner_invite, "active": True,
            "totp_enabled": False, "token_version": 0, "created_at": now_iso(),
        }
        await db.users.insert_one(user)
    # Il titolare del gruppo prende in carico tutte le aziende già esistenti
    company_ids = [c["id"] for c in await db.companies.find({}, {"_id": 0, "id": 1}).to_list(1000)] if owner_invite \
        else invite["company_ids"]
    for cid in company_ids:
        role = await company_role(user, cid)
        if role is None:
            await db.memberships.insert_one({"id": new_id(), "user_id": user["id"], "company_id": cid,
                                             "role": invite["role"], "created_at": now_iso()})
        elif owner_invite and role != "titolare":
            await db.memberships.update_one({"user_id": user["id"], "company_id": cid}, {"$set": {"role": "titolare"}})
    await db.invites.update_one({"id": invite["id"]}, {"$set": {"accepted_at": now_iso()}})
    await audit.log(user, "invito_accettato", details={"companies": company_ids, "titolare": owner_invite})
    return {"access_token": create_access_token(user["id"], user.get("token_version", 0))}
