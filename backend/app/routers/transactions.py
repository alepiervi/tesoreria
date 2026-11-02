import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services import intercompany as ic
from ..services import reconciliation as rec
from ..services.invoices import payable
from ..services.categories import CATEGORIES, suggest_pattern
from ..utils import now_iso
from .common import assert_open, companies_with, load

router = APIRouter(tags=["transactions"])


class CategoryIn(BaseModel):
    category: str


class Target(BaseModel):
    type: str  # "invoice" | "deadline"
    id: str


class MatchIn(BaseModel):
    targets: list[Target]


class ExcludeIn(BaseModel):
    reason: str
    category: str | None = None


@router.get("/categories")
async def categories():
    return CATEGORIES


async def _with_note_counts(db, items: list[dict]) -> list[dict]:
    ids = [t["id"] for t in items]
    counts, open_q = {}, {}
    async for n in db.notes.find({"target_type": "transaction", "target_id": {"$in": ids}}, {"target_id": 1, "is_question": 1, "resolved": 1}):
        counts[n["target_id"]] = counts.get(n["target_id"], 0) + 1
        if n.get("is_question") and not n.get("resolved"):
            open_q[n["target_id"]] = True
    for t in items:
        t["notes_count"] = counts.get(t["id"], 0)
        t["open_question"] = open_q.get(t["id"], False)
    return items


@router.get("/companies/{company_id}/transactions")
async def list_transactions(
    company_id: str, status: str | None = None, category: str | None = None, q: str | None = None,
    date_from: str | None = None, date_to: str | None = None, account_id: str | None = None,
    direction: str | None = None, limit: int = Query(100, le=500), offset: int = 0,
    user: dict = Depends(get_current_user),
):
    await require(user, company_id, "view")
    query: dict = {"company_id": company_id}
    if status:
        query["status"] = status
    if category:
        query["category"] = category
    if account_id:
        query["account_id"] = account_id
    if q:
        query["description"] = {"$regex": re.escape(q), "$options": "i"}
    if date_from or date_to:
        query["date"] = {}
        if date_from:
            query["date"]["$gte"] = date_from
        if date_to:
            query["date"]["$lte"] = date_to
    if direction == "in":
        query["amount_cents"] = {"$gt": 0}
    elif direction == "out":
        query["amount_cents"] = {"$lt": 0}
    db = get_db()
    total = await db.transactions.count_documents(query)
    items = await db.transactions.find(query, {"_id": 0}).sort([("date", -1), ("created_at", -1)]) \
        .skip(offset).limit(limit).to_list(limit)
    accounts = {a["id"]: a for a in await db.bank_accounts.find({"company_id": company_id}, {"_id": 0}).to_list(100)}
    for t in items:
        acc = accounts.get(t.get("account_id"), {})
        t["account_label"] = f"{acc.get('bank_name', '')} {acc.get('iban_masked', '')}".strip()
    return {"items": await _with_note_counts(db, items), "total": total}


@router.patch("/transactions/{tx_id}")
async def set_category(tx_id: str, body: CategoryIn, user: dict = Depends(get_current_user)):
    tx, _ = await load("transactions", tx_id, user, "categorize")
    if body.category not in CATEGORIES:
        raise HTTPException(400, "Categoria non valida.")
    if tx["status"] == "escluso":
        await assert_open(tx["company_id"], tx["date"])
    await get_db().transactions.update_one({"id": tx_id}, {"$set": {"category": body.category, "category_manual": True}})
    if tx["status"] == "escluso":
        from ..services.accounting import sync_source
        await sync_source(get_db(), "transaction", tx_id)
    await audit.log(user, "categoria_modificata", tx["company_id"], tx_id, {"category": body.category})
    # il frontend propone di creare una regola con questo testo
    return {"ok": True, "suggested_pattern": suggest_pattern(tx["description"]),
            "direction": "in" if tx["amount_cents"] > 0 else "out"}


# ---------- Riconciliazione ----------

@router.get("/reconciliation")
async def reconciliation_queue(company_id: str | None = None, user: dict = Depends(get_current_user)):
    """Movimenti da riconciliare di tutte le aziende visibili, con le proposte di abbinamento."""
    db = get_db()
    scope = await companies_with(user, "view", company_id)
    ic_by_tx = {}
    for c in await ic.candidates(db, list(scope)):
        for side in ("out", "in"):
            if c[side]:
                ic_by_tx[c[side]["id"]] = c
    result = []
    for cid, info in scope.items():
        invoices, deadlines = await rec.open_targets(db, cid)
        txs = await db.transactions.find({"company_id": cid, "status": "da_riconciliare"}, {"_id": 0}) \
            .sort("date", -1).to_list(1000)
        txs = await _with_note_counts(db, txs)
        for t in txs:
            t["company_name"] = info["name"]
            t["can_reconcile"] = "reconcile" in info["permissions"]
            t["suggestions"] = rec.suggest(t, invoices, deadlines)
            cand = ic_by_tx.get(t["id"])
            if cand:
                other = cand["in"] if cand["out"] and cand["out"]["id"] == t["id"] else cand["out"]
                t["intercompany_suggestion"] = {
                    "kind": cand["kind"], "score": cand["score"], "reasons": cand["reasons"],
                    "pair": other, "other_company_id": other["company_id"] if other else cand.get("other_company_id"),
                    "other_company_name": other["company_name"] if other else cand.get("other_company_name"),
                }
            result.append(t)
    result.sort(key=lambda t: t["date"], reverse=True)
    return result


@router.get("/companies/{company_id}/open-items")
async def open_items(company_id: str, direction: str, q: str | None = None, user: dict = Depends(get_current_user)):
    """Fatture e scadenze aperte, per l'abbinamento manuale."""
    await require(user, company_id, "view")
    invoices, deadlines = await rec.open_targets(get_db(), company_id)
    items = []
    for i in invoices:
        if i["direction"] != direction:
            continue
        items.append(rec._inv_target(i, payable(i) - i.get("paid_cents", 0)))
    for d in deadlines:
        is_in = d["kind"] == "incasso"
        if (direction == "attiva") == is_in:
            items.append({"type": "deadline", "id": d["id"], "label": d["description"],
                          "amount_cents": d["amount_cents"], "due_date": d["due_date"]})
    if q:
        items = [i for i in items if q.lower() in i["label"].lower()]
    return sorted(items, key=lambda i: i.get("due_date") or "")


@router.post("/transactions/{tx_id}/match")
async def match(tx_id: str, body: MatchIn, user: dict = Depends(get_current_user)):
    tx, _ = await load("transactions", tx_id, user, "reconcile")
    if tx["status"] != "da_riconciliare":
        raise HTTPException(400, "Movimento già riconciliato.")
    await assert_open(tx["company_id"], tx["date"])
    try:
        tx = await rec.apply_match(get_db(), tx, [t.model_dump() for t in body.targets], user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit.log(user, "movimento_riconciliato", tx["company_id"], tx["description"],
                    {"abbinamenti": [a["label"] for a in tx["allocations"]]})
    return tx


@router.post("/transactions/{tx_id}/exclude")
async def exclude(tx_id: str, body: ExcludeIn, user: dict = Depends(get_current_user)):
    """Segna un movimento come 'senza fattura' (stipendi, commissioni, giroconti...)."""
    tx, _ = await load("transactions", tx_id, user, "reconcile")
    await assert_open(tx["company_id"], tx["date"])
    update = {"status": "escluso", "exclusion_reason": body.reason.strip(), "reconciled_by": user["id"],
              "reconciled_by_name": user.get("name", ""), "reconciled_at": now_iso()}
    if body.category:
        if body.category not in CATEGORIES:
            raise HTTPException(400, "Categoria non valida.")
        update.update(category=body.category, category_manual=True)
    await get_db().transactions.update_one({"id": tx_id}, {"$set": update})
    from ..services.accounting import sync_source
    await sync_source(get_db(), "transaction", tx_id)
    await audit.log(user, "movimento_senza_fattura", tx["company_id"], tx["description"], {"motivo": body.reason})
    return {"ok": True}


@router.post("/transactions/{tx_id}/unmatch")
async def unmatch(tx_id: str, user: dict = Depends(get_current_user)):
    tx, _ = await load("transactions", tx_id, user, "reconcile")
    if tx["status"] == "da_riconciliare":
        raise HTTPException(400, "Il movimento non è riconciliato.")
    await assert_open(tx["company_id"], tx["date"])
    if tx.get("intercompany"):
        await ic.undo(get_db(), tx)
        await audit.log(user, "intercompany_annullato", tx["company_id"], tx["description"])
        return await get_db().transactions.find_one({"id": tx_id}, {"_id": 0})
    tx = await rec.undo_match(get_db(), tx)
    await audit.log(user, "riconciliazione_annullata", tx["company_id"], tx["description"])
    return tx


@router.post("/reconciliation/auto")
async def auto_reconcile(company_id: str | None = None, user: dict = Depends(get_current_user)):
    """Conferma in blocco solo le proposte molto sicure (affidabilità alta e senza alternative vicine)."""
    db = get_db()
    scope = await companies_with(user, "reconcile", company_id)
    done = 2 * await ic.auto_confirm(db, list(scope), user)  # ogni coppia sistema due movimenti
    for cid in scope:
        txs = await db.transactions.find({"company_id": cid, "status": "da_riconciliare"}, {"_id": 0}).to_list(2000)
        for t in txs:
            invoices, deadlines = await rec.open_targets(db, cid)
            sugg = rec.suggest(t, invoices, deadlines)
            if not sugg or sugg[0]["score"] < 85:
                continue
            if len(sugg) > 1 and sugg[0]["score"] - sugg[1]["score"] < 15:
                continue
            try:
                await rec.apply_match(db, t, sugg[0]["targets"], user)
                done += 1
            except ValueError:
                continue
        if done:
            await audit.log(user, "riconciliazione_automatica", cid, details={"movimenti": done})
    return {"reconciled": done}
