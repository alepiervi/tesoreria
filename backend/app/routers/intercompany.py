from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services import intercompany as ic
from ..services.categories import CATEGORIES
from ..utils import new_id, now_iso
from .common import assert_open, companies_with

router = APIRouter(tags=["intercompany"])


class ConfirmIn(BaseModel):
    tx_ids: list[str]
    other_company_id: str | None = None


class RuleIn(BaseModel):
    company_id: str | None = None  # None = tutte le aziende del gruppo (solo titolare)
    pattern: str
    direction: str = "any"  # in | out | any
    category: str
    apply_existing: bool = True


# ---------- Intercompany ----------

@router.get("/intercompany")
async def overview(date_from: str | None = None, user: dict = Depends(get_current_user)):
    db = get_db()
    scope = await companies_with(user, "view")
    reconcilable = await companies_with(user, "reconcile")
    cands = await ic.candidates(db, list(scope))
    for c in cands:
        ids = [x["company_id"] for x in (c["out"], c["in"]) if x]
        c["can_confirm"] = all(i in reconcilable for i in ids)
    return {"candidates": cands, **await ic.positions(db, list(scope), date_from)}


@router.post("/intercompany/confirm")
async def confirm(body: ConfirmIn, user: dict = Depends(get_current_user)):
    db = get_db()
    for tx_id in body.tx_ids:
        tx = await db.transactions.find_one({"id": tx_id})
        if not tx:
            raise HTTPException(404, "Movimento non trovato.")
        await require(user, tx["company_id"], "reconcile")
        await assert_open(tx["company_id"], tx["date"])
    try:
        txs = await ic.confirm(db, body.tx_ids, body.other_company_id, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    for t in txs:
        await audit.log(user, "intercompany_confermato", t["company_id"], t["description"])
    return {"ok": True}


@router.post("/intercompany/auto")
async def auto(user: dict = Depends(get_current_user)):
    scope = await companies_with(user, "reconcile")
    done = await ic.auto_confirm(get_db(), list(scope), user)
    if done:
        await audit.log(user, "intercompany_automatico", details={"coppie": done})
    return {"confirmed": done}


# ---------- Regole di categoria ----------

@router.get("/category-rules")
async def list_rules(user: dict = Depends(get_current_user)):
    scope = await companies_with(user, "view")
    rules = await get_db().category_rules.find({"company_id": {"$in": [*scope, None]}}, {"_id": 0}) \
        .sort("created_at", -1).to_list(2000)
    for r in rules:
        r["company_name"] = scope[r["company_id"]]["name"] if r["company_id"] else "Tutte le aziende"
    return rules


@router.post("/category-rules")
async def create_rule(body: RuleIn, user: dict = Depends(get_current_user)):
    db = get_db()
    pattern = " ".join(body.pattern.lower().split())
    if len(pattern) < 3:
        raise HTTPException(400, "Il testo della regola deve avere almeno 3 caratteri.")
    if body.category not in CATEGORIES:
        raise HTTPException(400, "Categoria non valida.")
    if body.direction not in {"in", "out", "any"}:
        raise HTTPException(400, "Direzione non valida.")
    if body.company_id:
        await require(user, body.company_id, "categorize")
        targets = [body.company_id]
    else:
        if not user.get("is_owner"):
            raise HTTPException(403, "Solo il titolare può creare regole valide per tutto il gruppo.")
        targets = list(await companies_with(user, "categorize"))
    existing = await db.category_rules.find_one({"company_id": body.company_id, "pattern": pattern,
                                                 "direction": body.direction})
    if existing:
        await db.category_rules.update_one({"id": existing["id"]}, {"$set": {"category": body.category}})
        rule_id = existing["id"]
    else:
        rule_id = new_id()
        await db.category_rules.insert_one({
            "id": rule_id, "company_id": body.company_id, "pattern": pattern, "direction": body.direction,
            "category": body.category, "created_by": user["id"], "created_by_name": user.get("name", ""),
            "created_at": now_iso()})
    updated = 0
    if body.apply_existing:
        import re
        q = {"company_id": {"$in": targets}, "category_manual": {"$ne": True},
             "description": {"$regex": re.escape(pattern), "$options": "i"}}
        if body.direction == "in":
            q["amount_cents"] = {"$gt": 0}
        elif body.direction == "out":
            q["amount_cents"] = {"$lt": 0}
        res = await db.transactions.update_many(q, {"$set": {"category": body.category}})
        updated = res.modified_count
    await audit.log(user, "regola_categoria", body.company_id, pattern, {"categoria": body.category, "aggiornati": updated})
    return {"id": rule_id, "updated": updated}


@router.delete("/category-rules/{rule_id}")
async def delete_rule(rule_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    rule = await db.category_rules.find_one({"id": rule_id})
    if not rule:
        raise HTTPException(404, "Regola non trovata.")
    if rule["company_id"]:
        await require(user, rule["company_id"], "categorize")
    elif not user.get("is_owner"):
        raise HTTPException(403, "Solo il titolare può eliminare le regole di gruppo.")
    await db.category_rules.delete_one({"id": rule_id})
    return {"ok": True}
