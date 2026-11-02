"""Riconciliazione: abbinamento dei movimenti bancari con fatture e scadenze.

Il punteggio di ogni proposta somma più indizi: importo identico, numero fattura
nella causale, nome della controparte nella causale, data vicina alla scadenza.
"""
import re
from itertools import combinations

from ..utils import now_iso, parse_date
from .invoices import invoice_status, payable, refresh_invoice_deadlines

STOPWORDS = {"srl", "spa", "snc", "sas", "srls", "studio", "societa", "società", "della", "delle",
             "group", "italia", "servizi", "fornitura"}

DONE = {"pagato", "incassato", "annullato"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zà-ù0-9]+", text.lower()) if len(t) >= 4 and t not in STOPWORDS}


def _number_core(number: str) -> str:
    """'FT 341/2026' -> '341'"""
    m = re.search(r"\d+", number or "")
    return m.group(0).lstrip("0") if m else ""


def _confidence(score: int) -> str:
    if score >= 80:
        return "alta"
    if score >= 55:
        return "media"
    return "bassa"


def _date_points(tx_date: str, due_date: str, issue_date: str | None = None) -> tuple[int, str | None]:
    try:
        tx = parse_date(tx_date)
        if issue_date and tx < parse_date(issue_date):
            return -40, None
        diff = abs((tx - parse_date(due_date)).days)
    except Exception:
        return 0, None
    if diff <= 7:
        return 12, "data vicina alla scadenza"
    if diff <= 30:
        return 6, None
    return 0, None


async def open_targets(db, company_id: str) -> tuple[list[dict], list[dict]]:
    invoices = await db.invoices.find(
        {"company_id": company_id, "status": {"$in": ["aperta", "parziale"]}, "total_cents": {"$gt": 0}},
        {"_id": 0}).to_list(5000)
    deadlines = await db.deadlines.find(
        {"company_id": company_id, "invoice_id": None, "status": {"$nin": list(DONE)}},
        {"_id": 0}).to_list(5000)
    return invoices, deadlines


def suggest(tx: dict, invoices: list[dict], deadlines: list[dict], limit: int = 3) -> list[dict]:
    amount = abs(tx["amount_cents"])
    direction = "attiva" if tx["amount_cents"] > 0 else "passiva"
    desc = tx.get("description", "")
    desc_tokens = _tokens(desc)
    desc_numbers = set(re.findall(r"\d+", desc))
    proposals = []

    candidates = [i for i in invoices if i["direction"] == direction]
    for inv in candidates:
        residual = payable(inv) - inv.get("paid_cents", 0)
        score, reasons = 0, []
        if residual == amount:
            score += 55
            reasons.append("importo identico")
        elif amount and abs(residual - amount) <= max(100, amount * 0.01):
            score += 25
            reasons.append("importo quasi identico")
        else:
            continue
        core = _number_core(inv["number"])
        if len(core) >= 2 and core in desc_numbers:
            score += 30
            reasons.append("numero fattura nella causale")
        if _tokens(inv.get("counterparty_name", "")) & desc_tokens:
            score += 18
            reasons.append("controparte nella causale")
        pts, why = _date_points(tx["date"], inv["due_date"], inv["date"])
        score += pts
        if why:
            reasons.append(why)
        proposals.append({"score": score, "reasons": reasons, "targets": [_inv_target(inv, residual)]})

    # Un bonifico che salda due fatture della stessa controparte
    by_party: dict[str, list] = {}
    for inv in candidates:
        by_party.setdefault(inv.get("counterparty_vat") or inv.get("counterparty_name"), []).append(inv)
    for group in by_party.values():
        if len(group) < 2 or len(group) > 12:
            continue
        for a, b in combinations(group, 2):
            ra = payable(a) - a.get("paid_cents", 0)
            rb = payable(b) - b.get("paid_cents", 0)
            if ra + rb != amount:
                continue
            score, reasons = 50, ["somma di due fatture"]
            if _tokens(a.get("counterparty_name", "")) & desc_tokens:
                score += 18
                reasons.append("controparte nella causale")
            for inv in (a, b):
                core = _number_core(inv["number"])
                if len(core) >= 2 and core in desc_numbers:
                    score += 10
            proposals.append({"score": score, "reasons": reasons,
                              "targets": [_inv_target(a, ra), _inv_target(b, rb)]})

    # Scadenze senza fattura (F24, rate, spese inserite a mano)
    for d in deadlines:
        is_out = d["kind"] != "incasso"
        if is_out != (tx["amount_cents"] < 0):
            continue
        if d["amount_cents"] != amount:
            continue
        score, reasons = 50, ["importo identico a una scadenza"]
        if _tokens(d.get("description", "")) & desc_tokens:
            score += 20
            reasons.append("descrizione simile")
        if d["kind"] == "f24" and "f24" in desc.lower():
            score += 20
            reasons.append("pagamento F24")
        pts, why = _date_points(tx["date"], d["due_date"])
        score += pts
        if why:
            reasons.append(why)
        proposals.append({"score": score, "reasons": reasons, "targets": [{
            "type": "deadline", "id": d["id"], "label": d["description"],
            "amount_cents": d["amount_cents"], "due_date": d["due_date"]}]})

    proposals = [p for p in proposals if p["score"] >= 35]
    proposals.sort(key=lambda p: -p["score"])
    for p in proposals:
        p["score"] = min(p["score"], 100)
        p["confidence"] = _confidence(p["score"])
    return proposals[:limit]


def _inv_target(inv: dict, residual: int) -> dict:
    kind = "Fattura attiva" if inv["direction"] == "attiva" else "Fattura passiva"
    return {"type": "invoice", "id": inv["id"],
            "label": f"{kind} {inv['number']} · {inv.get('counterparty_name', '')}",
            "amount_cents": residual, "due_date": inv.get("due_date")}


async def apply_match(db, tx: dict, targets: list[dict], user: dict) -> dict:
    """Collega il movimento alle fatture/scadenze indicate e aggiorna gli importi pagati."""
    remaining = abs(tx["amount_cents"])
    allocations = []
    for t in targets:
        if t["type"] == "invoice":
            inv = await db.invoices.find_one({"id": t["id"], "company_id": tx["company_id"]})
            if not inv:
                raise ValueError("Fattura non trovata.")
            residual = payable(inv) - inv.get("paid_cents", 0)
            alloc = min(residual, remaining)
            if alloc <= 0:
                continue
            paid = inv.get("paid_cents", 0) + alloc
            status = invoice_status(payable(inv), paid)
            paid_at = tx["date"] if status == "pagata" else None
            await db.invoices.update_one({"id": inv["id"]}, {"$set": {"paid_cents": paid, "status": status,
                                                                     "paid_at": paid_at}})
            inv.update(paid_cents=paid, status=status)
            await refresh_invoice_deadlines(db, inv)
            allocations.append({"type": "invoice", "id": inv["id"], "amount_cents": alloc,
                                "label": f"Fattura {inv['number']} · {inv.get('counterparty_name', '')}"})
            remaining -= alloc
        elif t["type"] == "deadline":
            d = await db.deadlines.find_one({"id": t["id"], "company_id": tx["company_id"]})
            if not d:
                raise ValueError("Scadenza non trovata.")
            done = "incassato" if d["kind"] == "incasso" else "pagato"
            await db.deadlines.update_one({"id": d["id"]}, {"$set": {"status": done, "transaction_id": tx["id"]}})
            alloc = min(d["amount_cents"], remaining)
            allocations.append({"type": "deadline", "id": d["id"], "amount_cents": alloc, "label": d["description"]})
            remaining -= alloc
    if not allocations:
        raise ValueError("Niente da abbinare: le fatture scelte risultano già pagate.")
    update = {"status": "riconciliato", "allocations": allocations, "unallocated_cents": remaining,
              "reconciled_by": user["id"], "reconciled_by_name": user.get("name", ""), "reconciled_at": now_iso()}
    await db.transactions.update_one({"id": tx["id"]}, {"$set": update})
    tx.update(update)
    await _after_change(db, tx)
    return tx


async def _after_change(db, tx: dict):
    """Aggiorna la contabilità (registrazione del movimento e ritenute da versare)."""
    from .accounting import sync_source
    from .withholding import sync_withholding_deadlines
    await sync_source(db, "transaction", tx["id"])
    company = await db.companies.find_one({"id": tx["company_id"]}, {"_id": 0})
    await sync_withholding_deadlines(db, company)


async def undo_match(db, tx: dict) -> dict:
    for a in tx.get("allocations", []):
        if a["type"] == "invoice":
            inv = await db.invoices.find_one({"id": a["id"]})
            if inv:
                paid = max(0, inv.get("paid_cents", 0) - a["amount_cents"])
                status = invoice_status(payable(inv), paid)
                await db.invoices.update_one({"id": inv["id"]}, {"$set": {"paid_cents": paid, "status": status,
                                                                         "paid_at": None}})
                inv.update(paid_cents=paid, status=status)
                await refresh_invoice_deadlines(db, inv)
        elif a["type"] == "deadline":
            d = await db.deadlines.find_one({"id": a["id"]})
            if d:
                back = "aperta" if d["kind"] == "incasso" else "da_pagare"
                await db.deadlines.update_one({"id": d["id"]}, {"$set": {"status": back, "transaction_id": None}})
    update = {"status": "da_riconciliare", "allocations": [], "unallocated_cents": None,
              "reconciled_by": None, "reconciled_by_name": None, "reconciled_at": None, "exclusion_reason": None}
    await db.transactions.update_one({"id": tx["id"]}, {"$set": update})
    tx.update(update)
    await _after_change(db, tx)
    return tx
