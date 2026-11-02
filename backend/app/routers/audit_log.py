from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import get_db
from ..deps import get_current_user, get_memberships
from ..permissions import has_permission

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(company_id: str | None = None, limit: int = Query(200, le=1000),
                     user: dict = Depends(get_current_user)):
    allowed = [m["company_id"] for m in await get_memberships(user["id"])
               if has_permission(m["role"], "view_audit")]
    if not allowed:
        raise HTTPException(403, "Il tuo ruolo non permette di vedere il registro attività.")
    if company_id:
        if company_id not in allowed:
            raise HTTPException(404, "Azienda non trovata.")
        query = {"company_id": company_id}
    elif user.get("is_owner"):
        query = {}
    else:
        query = {"company_id": {"$in": allowed}}
    return await get_db().audit.find(query, {"_id": 0}).sort("at", -1).limit(limit).to_list(limit)
