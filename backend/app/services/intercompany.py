"""Movimenti tra aziende del gruppo (intercompany) e giroconti tra conti della stessa azienda.

Un bonifico da Alfa a Beta compare come uscita in Alfa ed entrata in Beta: per il gruppo non è
né un costo né un ricavo. Questi movimenti vengono riconosciuti, abbinati tra loro ed esclusi
dai totali consolidati. Restano visibili nelle singole aziende.
"""
from .invoices import payable
import re
from datetime import timedelta

from ..utils import now_iso, parse_date, today

LEGAL = {"srl", "s.r.l.", "spa", "s.p.a.", "snc", "sas", "srls", "società", "societa", "azienda", "impresa", "group",
         "gruppo", "italia", "di", "e", "&"}
WINDOW_DAYS = 4
LOOKBACK_DAYS = 180


def name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-zà-ù0-9]+", name.lower()) if len(t) >= 3 and t not in LEGAL}


def mentions(description: str, company: dict) -> bool:
    toks = name_tokens(company["name"])
    words = set(re.findall(r"[a-zà-ù0-9]+", description.lower()))
    return bool(toks) and toks <= words


async def candidates(db, company_ids: list[str]) -> list[dict]:
    """Coppie di movimenti che sembrano trasferimenti interni. Ognuna ha un punteggio da 0 a 100."""
    companies = {c["id"]: c for c in await db.companies.find({}, {"_id": 0}).to_list(500)}
    since = (today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    # si guardano i movimenti di tutte le aziende del gruppo, ma si propongono solo coppie visibili all'utente
    txs = await db.transactions.find({"status": "da_riconciliare", "date": {"$gte": since}}, {"_id": 0}).to_list(20000)
    outs = [t for t in txs if t["amount_cents"] < 0]
    ins_by_amount: dict[int, list] = {}
    for t in txs:
        if t["amount_cents"] > 0:
            ins_by_amount.setdefault(t["amount_cents"], []).append(t)

    result, used = [], set()
    for a in sorted(outs, key=lambda t: t["date"]):
        for b in ins_by_amount.get(-a["amount_cents"], []):
            if b["id"] in used or a["id"] in used:
                continue
            if a["company_id"] not in company_ids and b["company_id"] not in company_ids:
                continue
            if abs((parse_date(a["date"]) - parse_date(b["date"])).days) > WINDOW_DAYS:
                continue
            same = a["company_id"] == b["company_id"]
            if same and a.get("account_id") == b.get("account_id"):
                continue
            score, reasons = 50, ["stesso importo, date vicine"]
            if same:
                kind = "giroconto"
                if "giroconto" in (a["description"] + b["description"]).lower():
                    score += 35
                    reasons.append("causale di giroconto")
                else:
                    score += 15
                    reasons.append("tra due conti della stessa azienda")
            else:
                kind = "intercompany"
                if mentions(a["description"], companies[b["company_id"]]):
                    score += 25
                    reasons.append(f"la causale cita {companies[b['company_id']]['name']}")
                if mentions(b["description"], companies[a["company_id"]]):
                    score += 25
                    reasons.append(f"la causale cita {companies[a['company_id']]['name']}")
            used.update({a["id"], b["id"]})
            result.append({"kind": kind, "score": min(score, 100), "reasons": reasons,
                           "out": _brief(a, companies), "in": _brief(b, companies)})
            break

    # Movimenti che citano un'altra azienda del gruppo ma senza la controparte (es. conto non collegato)
    for t in txs:
        if t["id"] in used or t["company_id"] not in company_ids:
            continue
        for c in companies.values():
            if c["id"] != t["company_id"] and mentions(t["description"], c):
                result.append({"kind": "intercompany", "score": 60,
                               "reasons": [f"la causale cita {c['name']}", "controparte non trovata"],
                               "out": _brief(t, companies) if t["amount_cents"] < 0 else None,
                               "in": _brief(t, companies) if t["amount_cents"] > 0 else None,
                               "other_company_id": c["id"], "other_company_name": c["name"]})
                break
    result.sort(key=lambda r: -r["score"])
    return result


def _brief(t: dict, companies: dict) -> dict:
    return {"id": t["id"], "company_id": t["company_id"], "company_name": companies[t["company_id"]]["name"],
            "date": t["date"], "description": t["description"], "amount_cents": t["amount_cents"]}


async def confirm(db, tx_ids: list[str], other_company_id: str | None, user: dict) -> list[dict]:
    """Segna uno o due movimenti come trasferimento interno."""
    txs = [await db.transactions.find_one({"id": i}, {"_id": 0}) for i in tx_ids]
    if any(t is None for t in txs) or not 1 <= len(txs) <= 2:
        raise ValueError("Movimenti non trovati.")
    if any(t["status"] != "da_riconciliare" for t in txs):
        raise ValueError("Uno dei movimenti è già sistemato: annulla prima l'abbinamento.")
    if len(txs) == 2:
        a, b = txs
        if a["amount_cents"] != -b["amount_cents"]:
            raise ValueError("I due movimenti devono avere lo stesso importo, uno in uscita e uno in entrata.")
    names = {c["id"]: c["name"] async for c in db.companies.find({}, {"id": 1, "name": 1})}
    for t in txs:
        other = [x for x in txs if x["id"] != t["id"]]
        other_cid = other[0]["company_id"] if other else other_company_id
        if not other_cid or other_cid not in names:
            raise ValueError("Indica l'altra azienda del gruppo.")
        same = other_cid == t["company_id"]
        update = {
            "status": "escluso", "category": "Giroconti" if same else "Intercompany", "category_manual": True,
            "exclusion_reason": "Giroconto tra conti dell'azienda" if same else f"Movimento con {names[other_cid]}",
            "intercompany": {"company_id": other_cid, "pair_tx_id": other[0]["id"] if other else None},
            "reconciled_by": user["id"], "reconciled_by_name": user.get("name", ""), "reconciled_at": now_iso(),
        }
        await db.transactions.update_one({"id": t["id"]}, {"$set": update})
        t.update(update)
    from .accounting import sync_transactions
    await sync_transactions(db, [t["id"] for t in txs])
    return txs


async def undo(db, tx: dict) -> list[str]:
    """Annulla un trasferimento interno (anche sull'altro movimento della coppia)."""
    ids = [tx["id"]]
    pair = (tx.get("intercompany") or {}).get("pair_tx_id")
    if pair:
        ids.append(pair)
    await db.transactions.update_many({"id": {"$in": ids}}, {"$set": {
        "status": "da_riconciliare", "intercompany": None, "exclusion_reason": None, "category_manual": False,
        "reconciled_by": None, "reconciled_by_name": None, "reconciled_at": None}})
    from .accounting import sync_transactions
    await sync_transactions(db, ids)
    return ids


async def auto_confirm(db, company_ids: list[str], user: dict, min_score: int = 85) -> int:
    done = 0
    for c in await candidates(db, company_ids):
        if c["score"] < min_score or not c["out"] or not c["in"]:
            continue
        if c["out"]["company_id"] not in company_ids or c["in"]["company_id"] not in company_ids:
            continue
        try:
            await confirm(db, [c["out"]["id"], c["in"]["id"]], None, user)
            done += 1
        except ValueError:
            continue
    return done


async def positions(db, company_ids: list[str], date_from: str | None = None) -> dict:
    """Situazione tra le aziende: trasferimenti netti e fatture aperte tra aziende del gruppo."""
    names = {c["id"]: c["name"] async for c in db.companies.find({}, {"id": 1, "name": 1})}
    q = {"company_id": {"$in": company_ids}, "intercompany": {"$ne": None}, "category": "Intercompany"}
    if date_from:
        q["date"] = {"$gte": date_from}
    flows: dict[tuple, int] = {}
    movements = []
    async for t in db.transactions.find(q, {"_id": 0}).sort("date", -1):
        other = t["intercompany"]["company_id"]
        if t["amount_cents"] < 0:
            key = (t["company_id"], other)
            flows[key] = flows.get(key, 0) - t["amount_cents"]
        elif not t["intercompany"].get("pair_tx_id"):
            # entrata senza la controparte registrata: la si conta dal lato di chi riceve
            key = (other, t["company_id"])
            flows[key] = flows.get(key, 0) + t["amount_cents"]
        movements.append({**{k: t[k] for k in ("id", "company_id", "date", "description", "amount_cents")},
                          "company_name": names.get(t["company_id"]), "other_company_name": names.get(other)})
    pairs = {}
    for (src, dst), amount in flows.items():
        a, b = sorted([src, dst])
        p = pairs.setdefault((a, b), {"a": a, "b": b, "a_to_b": 0, "b_to_a": 0})
        p["a_to_b" if src == a else "b_to_a"] += amount
    transfer_rows = []
    for p in pairs.values():
        net = p["a_to_b"] - p["b_to_a"]
        giver, receiver = (p["a"], p["b"]) if net >= 0 else (p["b"], p["a"])
        transfer_rows.append({"from_company": names.get(giver), "to_company": names.get(receiver),
                              "from_company_id": giver, "to_company_id": receiver,
                              "sent_cents": p["a_to_b"] if giver == p["a"] else p["b_to_a"],
                              "returned_cents": p["b_to_a"] if giver == p["a"] else p["a_to_b"],
                              "net_cents": abs(net)})
    transfer_rows.sort(key=lambda r: -r["net_cents"])

    invoices = []
    async for i in db.invoices.find({"intercompany_company_id": {"$ne": None}, "direction": "attiva",
                                     "status": {"$in": ["aperta", "parziale"]},
                                     "$or": [{"company_id": {"$in": company_ids}},
                                             {"intercompany_company_id": {"$in": company_ids}}]}, {"_id": 0}):
        invoices.append({"invoice_id": i["id"], "number": i["number"], "date": i["date"], "due_date": i["due_date"],
                         "creditor": names.get(i["company_id"]), "debtor": names.get(i["intercompany_company_id"]),
                         "residual_cents": payable(i) - i.get("paid_cents", 0)})
    return {"transfers": transfer_rows, "open_invoices": invoices, "movements": movements[:200]}
