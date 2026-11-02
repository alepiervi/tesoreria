from .db import get_db
from .utils import new_id, now_iso


async def log(user: dict | None, action: str, company_id: str | None = None,
              target: str | None = None, details: dict | None = None):
    """Scrive una riga nel registro attività (chi ha fatto cosa e quando)."""
    await get_db().audit.insert_one({
        "id": new_id(),
        "at": now_iso(),
        "user_id": user["id"] if user else None,
        "user_email": user["email"] if user else None,
        "user_name": user.get("name") if user else None,
        "action": action,
        "company_id": company_id,
        "target": target,
        "details": details or {},
    })
