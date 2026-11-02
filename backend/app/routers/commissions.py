"""Provvigioni sulle attivazioni dei partner: import, abbinamento, listino, gare, rendiconti."""
import io
import json
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services import commissions as cm
from ..utils import new_id, now_iso, to_cents, today
from .common import load

router = APIRouter(tags=["commissions"])
MAX_FILE = 15 * 1024 * 1024


async def _company(company_id: str, user: dict, perm: str) -> dict:
    await require(user, company_id, perm)
    return await get_db().companies.find_one({"id": company_id}, {"_id": 0})


def _month(m: str | None) -> str:
    m = m or today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m):
        raise HTTPException(400, "Mese non valido.")
    return m


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(400, "File troppo grande (massimo 15 MB).")
    return data


def _mapping(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        m = json.loads(text)
        return m if isinstance(m, dict) else None
    except json.JSONDecodeError:
        raise HTTPException(400, "Mappatura non valida.")


# ---------------- panoramica

@router.get("/companies/{company_id}/commissions/overview")
async def overview(company_id: str, month: str | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    db = get_db()
    out = await cm.overview(db, company_id, _month(month))
    out["imports"] = await db.commission_imports.find({"company_id": company_id}, {"_id": 0}).sort("at", -1).to_list(10)
    out["setup"] = {k: await db[c].count_documents({"company_id": company_id}) for k, c in (
        ("partners", "commission_partners"), ("offers", "commission_offers"), ("beneficiaries", "commission_beneficiaries"),
        ("sales", "commission_sales"), ("activations", "commission_activations"))}
    return out


# ---------------- partner

class PartnerIn(BaseModel):
    name: str
    chargeback_months: int = 6


@router.get("/companies/{company_id}/commission-partners")
async def partners(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    return await get_db().commission_partners.find({"company_id": company_id}, {"_id": 0}).sort("name", 1).to_list(200)


@router.post("/companies/{company_id}/commission-partners")
async def add_partner(company_id: str, body: PartnerIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_commissions")
    if not body.name.strip():
        raise HTTPException(400, "Indica il nome del partner.")
    if not 0 <= body.chargeback_months <= 36:
        raise HTTPException(400, "Periodo di storno non valido.")
    doc = {"id": new_id(), "company_id": company_id, "name": body.name.strip(), "chargeback_months": body.chargeback_months,
           "mapping": None, "status_map": {}, "created_at": now_iso()}
    await get_db().commission_partners.insert_one(dict(doc))
    return doc


@router.put("/commission-partners/{partner_id}")
async def update_partner(partner_id: str, body: PartnerIn, user: dict = Depends(get_current_user)):
    p, _ = await load("commission_partners", partner_id, user, "manage_commissions")
    await get_db().commission_partners.update_one({"id": partner_id}, {"$set": {"name": body.name.strip() or p["name"],
                                                                                "chargeback_months": body.chargeback_months}})
    return {"ok": True}


@router.delete("/commission-partners/{partner_id}")
async def delete_partner(partner_id: str, user: dict = Depends(get_current_user)):
    p, _ = await load("commission_partners", partner_id, user, "manage_commissions")
    db = get_db()
    if await db.commission_activations.find_one({"partner_id": partner_id}):
        raise HTTPException(400, "Il partner ha delle attivazioni: non si può eliminare.")
    await db.commission_partners.delete_one({"id": partner_id})
    await db.commission_offers.delete_many({"partner_id": partner_id})
    return {"ok": True}


@router.post("/commission-partners/{partner_id}/import")
async def import_partner(partner_id: str, file: UploadFile = File(...), mapping: str | None = Form(None),
                         user: dict = Depends(get_current_user)):
    p, _ = await load("commission_partners", partner_id, user, "manage_commissions")
    try:
        result = await cm.import_partner_file(get_db(), p["company_id"], p, file.filename or "file.csv", await _read(file),
                                              _mapping(mapping), user)
    except cm.CommissionError as e:
        raise HTTPException(400, str(e))
    if not result.get("needs_mapping"):
        await audit.log(user, "avanzamenti_importati", p["company_id"], f"{p['name']} · {file.filename}",
                        {"nuove": result["new"], "aggiornate": result["updated"]})
    return result


@router.get("/commission-partners/{partner_id}/statuses")
async def partner_statuses(partner_id: str, user: dict = Depends(get_current_user)):
    p, _ = await load("commission_partners", partner_id, user, "view_commissions")
    counts: dict[str, dict] = {}
    async for a in get_db().commission_activations.find({"partner_id": partner_id}, {"raw_status": 1}):
        k = cm.norm(a.get("raw_status"))
        c = counts.setdefault(k, {"raw": a.get("raw_status") or "", "count": 0})
        c["count"] += 1
    smap = p.get("status_map") or {}
    rows = [{"key": k, "raw": v["raw"], "count": v["count"], "status": smap.get(k)} for k, v in counts.items()]
    for k, st in smap.items():
        if k not in counts:
            rows.append({"key": k, "raw": k, "count": 0, "status": st})
    return {"rows": sorted(rows, key=lambda r: (r["status"] is not None, -r["count"])), "statuses": cm.STATUSES}


class StatusMapIn(BaseModel):
    status_map: dict[str, str | None]


@router.put("/commission-partners/{partner_id}/statuses")
async def set_statuses(partner_id: str, body: StatusMapIn, user: dict = Depends(get_current_user)):
    p, _ = await load("commission_partners", partner_id, user, "manage_commissions")
    smap = {**(p.get("status_map") or {})}
    for k, v in body.status_map.items():
        if v and v not in cm.STATUSES:
            raise HTTPException(400, "Stato non valido.")
        if v:
            smap[cm.norm(k)] = v
        else:
            smap.pop(cm.norm(k), None)
    db = get_db()
    await db.commission_partners.update_one({"id": partner_id}, {"$set": {"status_map": smap}})
    changed = await cm.apply_status_map(db, p["company_id"], {**p, "status_map": smap})
    return {"ok": True, "updated": changed}


# ---------------- backoffice

@router.post("/companies/{company_id}/commissions/backoffice")
async def import_backoffice(company_id: str, file: UploadFile = File(...), mapping: str | None = Form(None),
                            user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_commissions")
    try:
        result = await cm.import_backoffice(get_db(), company_id, file.filename or "file.csv", await _read(file), _mapping(mapping), user)
    except cm.CommissionError as e:
        raise HTTPException(400, str(e))
    if not result.get("needs_mapping"):
        await audit.log(user, "backoffice_importato", company_id, file.filename, {"righe": result["rows"]})
    return result


# ---------------- listino

class OfferIn(BaseModel):
    partner_id: str
    name: str
    match: str = ""
    revenue: str = "0"
    payout_struttura: str = "0"
    payout_dipendente: str = "0"
    active: bool = True


def _offer_doc(body: OfferIn) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Indica il nome dell'offerta.")
    try:
        values = {k: to_cents(getattr(body, k) or 0) for k in ("revenue", "payout_struttura", "payout_dipendente")}
    except ValueError:
        raise HTTPException(400, "Importi non validi.")
    if any(v < 0 for v in values.values()):
        raise HTTPException(400, "Gli importi non possono essere negativi.")
    return {"partner_id": body.partner_id, "name": body.name.strip(), "match": (body.match or body.name).strip(),
            "revenue_cents": values["revenue"], "payout_struttura_cents": values["payout_struttura"],
            "payout_dipendente_cents": values["payout_dipendente"], "active": body.active}


@router.get("/companies/{company_id}/commission-offers")
async def offers(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    db = get_db()
    items = await db.commission_offers.find({"company_id": company_id}, {"_id": 0}).sort("name", 1).to_list(5000)
    # offerte presenti nei file ma non ancora nel listino
    unpriced: dict[tuple, int] = {}
    async for a in db.commission_activations.find({"company_id": company_id, "offer_id": None}, {"partner_id": 1, "partner_name": 1, "offer": 1}):
        k = (a["partner_id"], a.get("partner_name", ""), a.get("offer") or "")
        unpriced[k] = unpriced.get(k, 0) + 1
    return {"items": items, "unpriced": [{"partner_id": k[0], "partner": k[1], "offer": k[2], "count": n}
                                          for k, n in sorted(unpriced.items(), key=lambda x: -x[1])]}


@router.post("/companies/{company_id}/commission-offers")
async def add_offer(company_id: str, body: OfferIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_commissions")
    db = get_db()
    if not await db.commission_partners.find_one({"id": body.partner_id, "company_id": company_id}):
        raise HTTPException(400, "Partner non valido.")
    doc = {"id": new_id(), "company_id": company_id, **_offer_doc(body), "created_at": now_iso()}
    await db.commission_offers.insert_one(dict(doc))
    await cm.reprice(db, company_id)
    await audit.log(user, "listino_provvigioni", company_id, doc["name"])
    return doc


@router.put("/commission-offers/{offer_id}")
async def update_offer(offer_id: str, body: OfferIn, user: dict = Depends(get_current_user)):
    o, _ = await load("commission_offers", offer_id, user, "manage_commissions")
    db = get_db()
    await db.commission_offers.update_one({"id": offer_id}, {"$set": _offer_doc(body)})
    await cm.reprice(db, o["company_id"])
    await audit.log(user, "listino_provvigioni", o["company_id"], body.name)
    return {"ok": True}


@router.delete("/commission-offers/{offer_id}")
async def delete_offer(offer_id: str, user: dict = Depends(get_current_user)):
    o, _ = await load("commission_offers", offer_id, user, "manage_commissions")
    db = get_db()
    await db.commission_offers.delete_one({"id": offer_id})
    await cm.reprice(db, o["company_id"])
    return {"ok": True}


# ---------------- strutture e dipendenti

class BeneficiaryIn(BaseModel):
    kind: str
    name: str
    codes: list[str] = []
    tax_code: str = ""
    iban: str = ""
    email: str = ""
    group_company_id: str | None = None
    active: bool = True


def _ben_doc(body: BeneficiaryIn) -> dict:
    if body.kind not in {"struttura", "dipendente"}:
        raise HTTPException(400, "Tipo non valido.")
    if not body.name.strip():
        raise HTTPException(400, "Indica il nome.")
    codes = sorted({cm.norm_code(c) for c in body.codes if cm.norm_code(c)})
    if not codes:
        raise HTTPException(400, "Indica almeno un codice venditore (quello che compare nel file del backoffice).")
    return {"kind": body.kind, "name": body.name.strip(), "codes": codes, "tax_code": body.tax_code.strip().upper(),
            "iban": body.iban.replace(" ", "").upper(), "email": body.email.strip(), "group_company_id": body.group_company_id or None,
            "active": body.active}


async def _check_codes(company_id: str, codes: list[str], exclude: str | None = None):
    async for b in get_db().commission_beneficiaries.find({"company_id": company_id, "codes": {"$in": codes}}):
        if b["id"] != exclude:
            dup = sorted(set(codes) & set(b["codes"]))
            raise HTTPException(400, f"Il codice {', '.join(dup)} è già di {b['name']}.")


@router.get("/companies/{company_id}/commission-beneficiaries")
async def beneficiaries(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    db = get_db()
    items = await db.commission_beneficiaries.find({"company_id": company_id}, {"_id": 0}).sort([("kind", -1), ("name", 1)]).to_list(5000)
    known = {c for b in items for c in b["codes"]}
    unknown: dict[str, int] = {}
    async for s in db.commission_sales.find({"company_id": company_id}, {"seller_code": 1}):
        if s["seller_code"] not in known:
            unknown[s["seller_code"]] = unknown.get(s["seller_code"], 0) + 1
    return {"items": items, "unknown_codes": [{"code": k, "sales": v} for k, v in sorted(unknown.items(), key=lambda x: -x[1])]}


@router.post("/companies/{company_id}/commission-beneficiaries")
async def add_beneficiary(company_id: str, body: BeneficiaryIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_commissions")
    doc = {"id": new_id(), "company_id": company_id, **_ben_doc(body), "created_at": now_iso()}
    await _check_codes(company_id, doc["codes"])
    db = get_db()
    await db.commission_beneficiaries.insert_one(dict(doc))
    await cm.rematch(db, company_id)
    await audit.log(user, "percettore_provvigioni", company_id, doc["name"])
    return doc


@router.put("/commission-beneficiaries/{ben_id}")
async def update_beneficiary(ben_id: str, body: BeneficiaryIn, user: dict = Depends(get_current_user)):
    b, _ = await load("commission_beneficiaries", ben_id, user, "manage_commissions")
    doc = _ben_doc(body)
    await _check_codes(b["company_id"], doc["codes"], ben_id)
    db = get_db()
    await db.commission_beneficiaries.update_one({"id": ben_id}, {"$set": doc})
    await cm.rematch(db, b["company_id"])
    return {"ok": True}


@router.delete("/commission-beneficiaries/{ben_id}")
async def delete_beneficiary(ben_id: str, user: dict = Depends(get_current_user)):
    b, _ = await load("commission_beneficiaries", ben_id, user, "manage_commissions")
    db = get_db()
    if await db.commission_statements.find_one({"beneficiary_id": ben_id}):
        raise HTTPException(400, "Ha già dei rendiconti approvati: disattivalo invece di eliminarlo.")
    await db.commission_beneficiaries.delete_one({"id": ben_id})
    await db.commission_activations.update_many({"beneficiary_id": ben_id, "paid_statement_id": None},
                                                {"$set": {"beneficiary_id": None, "assignment": None}})
    await cm.rematch(db, b["company_id"])
    return {"ok": True}


# ---------------- gare

class TierIn(BaseModel):
    min: int
    bonus: str = "0"
    per_activation: str = "0"


class ContestIn(BaseModel):
    name: str
    kind: str = "tutti"
    partner_id: str | None = None
    valid_from: str
    valid_to: str | None = None
    tiers: list[TierIn]
    active: bool = True


def _contest_doc(body: ContestIn) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Indica il nome della gara.")
    if body.kind not in {"tutti", "struttura", "dipendente"}:
        raise HTTPException(400, "Destinatari non validi.")
    for m in (body.valid_from, body.valid_to):
        if m:
            _month(m)
    tiers = []
    try:
        for t in body.tiers:
            if t.min < 1:
                raise HTTPException(400, "La soglia deve essere almeno 1 attivazione.")
            tiers.append({"min": t.min, "bonus_cents": to_cents(t.bonus or 0), "per_activation_cents": to_cents(t.per_activation or 0)})
    except ValueError:
        raise HTTPException(400, "Importi non validi.")
    if not tiers:
        raise HTTPException(400, "Aggiungi almeno una soglia.")
    return {"name": body.name.strip(), "kind": body.kind, "partner_id": body.partner_id or None, "valid_from": body.valid_from,
            "valid_to": body.valid_to or None, "tiers": sorted(tiers, key=lambda t: t["min"]), "active": body.active}


@router.get("/companies/{company_id}/commission-contests")
async def contests(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    return await get_db().commission_contests.find({"company_id": company_id}, {"_id": 0}).sort("valid_from", -1).to_list(500)


@router.post("/companies/{company_id}/commission-contests")
async def add_contest(company_id: str, body: ContestIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_commissions")
    doc = {"id": new_id(), "company_id": company_id, **_contest_doc(body), "created_at": now_iso()}
    await get_db().commission_contests.insert_one(dict(doc))
    await audit.log(user, "gara_provvigioni", company_id, doc["name"])
    return doc


@router.put("/commission-contests/{contest_id}")
async def update_contest(contest_id: str, body: ContestIn, user: dict = Depends(get_current_user)):
    await load("commission_contests", contest_id, user, "manage_commissions")
    await get_db().commission_contests.update_one({"id": contest_id}, {"$set": _contest_doc(body)})
    return {"ok": True}


@router.delete("/commission-contests/{contest_id}")
async def delete_contest(contest_id: str, user: dict = Depends(get_current_user)):
    await load("commission_contests", contest_id, user, "manage_commissions")
    await get_db().commission_contests.delete_one({"id": contest_id})
    return {"ok": True}


# ---------------- attivazioni

@router.get("/companies/{company_id}/commission-activations")
async def activations(company_id: str, partner_id: str | None = None, status: str | None = None, assigned: str | None = None,
                      beneficiary_id: str | None = None, q: str | None = None, month: str | None = None,
                      limit: int = Query(100, le=1000), offset: int = 0, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    query: dict = {"company_id": company_id}
    if partner_id:
        query["partner_id"] = partner_id
    if status:
        query["status"] = None if status == "sconosciuto" else status
    if assigned == "no":
        query["beneficiary_id"] = None
    elif assigned == "si":
        query["beneficiary_id"] = {"$ne": None}
    if beneficiary_id:
        query["beneficiary_id"] = beneficiary_id
    if month:
        m = _month(month)
        query["$or"] = [{"activation_date": {"$gte": f"{m}-01", "$lte": cm.month_end(m)}},
                        {"status_date": {"$gte": f"{m}-01", "$lte": cm.month_end(m)}}]
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query.setdefault("$and", []).append({"$or": [{"customer_cf": rx}, {"customer_name": rx}, {"external_id": rx}, {"account": rx}, {"offer": rx}]})
    db = get_db()
    total = await db.commission_activations.count_documents(query)
    items = await db.commission_activations.find(query, {"_id": 0}).sort("status_date", -1).skip(offset).to_list(limit)
    bens = {b["id"]: b for b in await db.commission_beneficiaries.find({"company_id": company_id}, {"_id": 0, "id": 1, "name": 1, "kind": 1}).to_list(5000)}
    offers = {o["id"]: o for o in await db.commission_offers.find({"company_id": company_id}, {"_id": 0}).to_list(5000)}
    for a in items:
        b = bens.get(a.get("beneficiary_id"))
        a["beneficiary_name"] = b["name"] if b else None
        a["beneficiary_kind"] = b["kind"] if b else None
        o = offers.get(a.get("offer_id"))
        a["offer_name"] = o["name"] if o else None
        a["payout_cents"] = cm._payout(o, b["kind"]) if (o and b) else None
    return {"total": total, "items": items}


class AssignIn(BaseModel):
    beneficiary_id: str | None = None


@router.post("/commission-activations/{activation_id}/assign")
async def assign(activation_id: str, body: AssignIn, user: dict = Depends(get_current_user)):
    a, _ = await load("commission_activations", activation_id, user, "manage_commissions")
    db = get_db()
    if a.get("paid_statement_id"):
        raise HTTPException(400, "L'attivazione è già in un rendiconto approvato: riaprilo per cambiare l'assegnazione.")
    if body.beneficiary_id:
        b = await db.commission_beneficiaries.find_one({"id": body.beneficiary_id, "company_id": a["company_id"]})
        if not b:
            raise HTTPException(400, "Struttura o dipendente non valido.")
        await db.commission_activations.update_one({"id": activation_id}, {"$set": {
            "beneficiary_id": b["id"], "assignment": "manuale", "match_note": f"Assegnata a mano da {user.get('name') or user['email']}"}})
    else:
        await db.commission_activations.update_one({"id": activation_id}, {"$set": {"assignment": None, "beneficiary_id": None}})
        await cm.rematch(db, a["company_id"])
    await audit.log(user, "attivazione_assegnata", a["company_id"], a["external_id"])
    return {"ok": True}


# ---------------- rendiconti

@router.get("/companies/{company_id}/commission-statements")
async def statements(company_id: str, month: str | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    return await cm.compute_month(get_db(), company_id, _month(month))


class ApproveIn(BaseModel):
    month: str
    beneficiary_ids: list[str] | None = None


@router.post("/companies/{company_id}/commission-statements/approve")
async def approve(company_id: str, body: ApproveIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_commissions")
    db = get_db()
    settings = await db.commission_settings.find_one({"company_id": company_id}) or {}
    try:
        done = await cm.approve(db, company_id, _month(body.month), body.beneficiary_ids, user, settings.get("pay_day", 15))
    except cm.CommissionError as e:
        raise HTTPException(400, str(e))
    await audit.log(user, "provvigioni_approvate", company_id, body.month, {"rendiconti": len(done),
                                                                           "totale": sum(s["total_cents"] for s in done)})
    return {"approved": len(done), "total_cents": sum(s["total_cents"] for s in done if s["total_cents"] > 0)}


@router.post("/commission-statements/{statement_id}/reopen")
async def reopen(statement_id: str, user: dict = Depends(get_current_user)):
    s, _ = await load("commission_statements", statement_id, user, "manage_commissions")
    try:
        await cm.reopen(get_db(), s)
    except cm.CommissionError as e:
        raise HTTPException(400, str(e))
    await audit.log(user, "provvigioni_riaperte", s["company_id"], f"{s['beneficiary_name']} {s['month']}")
    return {"ok": True}


@router.post("/commission-statements/{statement_id}/paid")
async def mark_paid(statement_id: str, user: dict = Depends(get_current_user)):
    s, _ = await load("commission_statements", statement_id, user, "manage_commissions")
    if s["status"] != "approvato":
        raise HTTPException(400, "Il rendiconto non è da pagare.")
    await get_db().commission_statements.update_one({"id": statement_id}, {"$set": {"status": "pagato", "paid_at": now_iso()}})
    return {"ok": True}


@router.get("/companies/{company_id}/commission-statements/export")
async def export_month(company_id: str, month: str, kind: str = "tutti", user: dict = Depends(get_current_user)):
    """Excel del mese: riepilogo per percettore e dettaglio righe (da mandare alle strutture o al consulente del lavoro)."""
    company = await _company(company_id, user, "view_commissions")
    data = await cm.compute_month(get_db(), company_id, _month(month))
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Riepilogo"
    ws.append(["Percettore", "Tipo", "Codice fiscale", "IBAN", "Attivazioni", "Storni", "Gare", "Riporto", "Totale", "Stato"])
    for c in ws[1]:
        c.font = Font(bold=True)
    det = wb.create_sheet("Dettaglio")
    det.append(["Percettore", "Tipo riga", "Data", "Descrizione", "Importo"])
    for c in det[1]:
        c.font = Font(bold=True)
    for r in data["rows"]:
        b = r["beneficiary"]
        if kind != "tutti" and b["kind"] != kind:
            continue
        by = {t: sum(x["amount_cents"] for x in r["lines"] if x["type"] == t) / 100 for t in ("attivazione", "storno", "gara", "riporto")}
        ws.append([b["name"], b["kind"], b.get("tax_code", ""), b.get("iban", ""), by["attivazione"], by["storno"], by["gara"], by["riporto"],
                   r["total_cents"] / 100, r["status"]])
        for x in r["lines"]:
            det.append([b["name"], x["type"], x.get("date", ""), x["description"], x["amount_cents"] / 100])
    for sheet, cols in ((ws, "EFGHI"), (det, "E")):
        for col in cols:
            for cell in sheet[col][1:]:
                cell.number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 32
    det.column_dimensions["D"].width = 80
    buf = io.BytesIO()
    wb.save(buf)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", company["name"]).strip("_").lower()
    name = f"provvigioni_{'bonus_dipendenti_' if kind == 'dipendente' else ''}{slug}_{month}.xlsx"
    await audit.log(user, "export", company_id, name)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class SettingsIn(BaseModel):
    pay_day: int = 15


@router.put("/companies/{company_id}/commission-settings")
async def save_settings(company_id: str, body: SettingsIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_commissions")
    if not 1 <= body.pay_day <= 28:
        raise HTTPException(400, "Giorno non valido (1-28).")
    await get_db().commission_settings.update_one({"company_id": company_id}, {"$set": {"company_id": company_id, "pay_day": body.pay_day}},
                                                  upsert=True)
    return {"ok": True}


@router.get("/companies/{company_id}/commission-settings")
async def get_settings(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_commissions")
    s = await get_db().commission_settings.find_one({"company_id": company_id}, {"_id": 0}) or {}
    return {"pay_day": s.get("pay_day", 15), "backoffice_mapping": s.get("backoffice_mapping"),
            "statuses": cm.STATUSES}
