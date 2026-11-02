from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, get_memberships, require, require_owner
from ..permissions import permissions_for
from ..utils import clean, new_id, now_iso

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyIn(BaseModel):
    name: str
    vat_number: str = ""
    tax_code: str = ""
    sdi_code: str = ""
    pec: str = ""
    address: str = ""


class CompanyUpdate(BaseModel):
    name: str | None = None
    vat_number: str | None = None
    tax_code: str | None = None
    sdi_code: str | None = None
    pec: str | None = None
    address: str | None = None


@router.get("")
async def list_companies(user: dict = Depends(get_current_user)):
    db = get_db()
    memberships = {m["company_id"]: m["role"] for m in await get_memberships(user["id"])}
    companies = await db.companies.find({"id": {"$in": list(memberships)}}, {"_id": 0}).sort("name", 1).to_list(500)
    for c in companies:
        c["role"] = memberships[c["id"]]
        c["permissions"] = sorted(permissions_for(c["role"]))
    return companies


@router.post("")
async def create_company(body: CompanyIn, user: dict = Depends(get_current_user)):
    require_owner(user)
    db = get_db()
    company = {"id": new_id(), **body.model_dump(), "vat_number": body.vat_number.strip().upper(),
               "created_at": now_iso(), "created_by": user["id"]}
    await db.companies.insert_one(company)
    # Tutti i titolari del gruppo prendono in carico la nuova azienda
    owners = await db.users.find({"is_owner": True, "is_developer": {"$ne": True}, "active": {"$ne": False}}, {"_id": 0, "id": 1}).to_list(100)
    for uid in {user["id"], *(o["id"] for o in owners)}:
        await db.memberships.insert_one({"id": new_id(), "user_id": uid, "company_id": company["id"],
                                         "role": "titolare", "created_at": now_iso()})
    await audit.log(user, "azienda_creata", company["id"], company["name"])
    return clean(company)


@router.get("/{company_id}")
async def get_company(company_id: str, user: dict = Depends(get_current_user)):
    role = await require(user, company_id, "view")
    company = clean(await get_db().companies.find_one({"id": company_id}))
    company["role"] = role
    company["permissions"] = sorted(permissions_for(role))
    return company


@router.patch("/{company_id}")
async def update_company(company_id: str, body: CompanyUpdate, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_members")
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(400, "Nessuna modifica.")
    await get_db().companies.update_one({"id": company_id}, {"$set": changes})
    await audit.log(user, "azienda_modificata", company_id, details=changes)
    return clean(await get_db().companies.find_one({"id": company_id}))
