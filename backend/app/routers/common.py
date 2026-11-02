from fastapi import HTTPException

from ..db import get_db
from ..deps import get_memberships, require
from ..permissions import has_permission, permissions_for


async def load(collection: str, obj_id: str, user: dict, permission: str) -> tuple[dict, str]:
    """Carica un oggetto e verifica il permesso sull'azienda a cui appartiene."""
    doc = await get_db()[collection].find_one({"id": obj_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Elemento non trovato.")
    role = await require(user, doc["company_id"], permission)
    return doc, role


async def companies_with(user: dict, permission: str, company_id: str | None = None) -> dict[str, dict]:
    """Aziende su cui l'utente ha il permesso: {company_id: {name, role, permissions}}."""
    memberships = [m for m in await get_memberships(user["id"]) if has_permission(m["role"], permission)]
    if company_id:
        memberships = [m for m in memberships if m["company_id"] == company_id]
        if not memberships:
            raise HTTPException(404, "Azienda non trovata.")
    ids = [m["company_id"] for m in memberships]
    companies = {c["id"]: c for c in await get_db().companies.find({"id": {"$in": ids}}, {"_id": 0}).to_list(500)}
    return {
        m["company_id"]: {"name": companies[m["company_id"]]["name"], "role": m["role"],
                          "permissions": sorted(permissions_for(m["role"]))}
        for m in memberships if m["company_id"] in companies
    }


async def assert_open(company_id: str, d: str) -> None:
    """Blocca le modifiche a movimenti e fatture con data in un periodo contabile chiuso."""
    company = await get_db().companies.find_one({"id": company_id}, {"accounting_lock_date": 1})
    lock = (company or {}).get("accounting_lock_date")
    if lock and d <= lock:
        raise HTTPException(400, f"Il periodo fino al {lock[8:10]}/{lock[5:7]}/{lock[:4]} è chiuso in contabilità: "
                                 "non si possono più modificare movimenti e fatture con quella data.")
