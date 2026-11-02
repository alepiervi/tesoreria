"""Contabilità generale: piano dei conti, prima nota, libri, bilancio, cespiti, ratei e risconti, chiusure."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services import accounting as acc
from ..services import accounting_close as close
from ..services import accounting_reports as rep
from ..services.categories import CATEGORIES
from ..utils import new_id, now_iso, parse_date, to_cents, today
from .common import load

router = APIRouter(tags=["accounting"])


def _err(e: Exception):
    raise HTTPException(400, str(e))


async def _company(company_id: str, user: dict, perm: str) -> dict:
    await require(user, company_id, perm)
    return await get_db().companies.find_one({"id": company_id}, {"_id": 0})


def _year_range(year: int | None, date_from: str | None, date_to: str | None) -> tuple[str, str]:
    y = year or today().year
    return date_from or f"{y}-01-01", date_to or f"{y}-12-31"


# ---------------- piano dei conti

class AccountIn(BaseModel):
    parent_code: str
    name: str
    cee: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    cee: str | None = None
    cee_neg: str | None = None
    active: bool | None = None


class SettingsIn(BaseModel):
    category_map: dict[str, str] = {}
    enabled: bool = True


@router.get("/companies/{company_id}/accounts")
async def list_accounts(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    accounts = list((await rep.chart_of(get_db(), company_id)).values())
    tb = await rep.trial_balance(get_db(), company_id, *_year_range(year, None, None))
    sums = {r["code"]: r for r in tb["rows"]}
    for a in accounts:
        r = sums.get(a["code"])
        a["dare"], a["avere"], a["saldo"] = (r["dare"], r["avere"], r["saldo"]) if r else (0, 0, 0)
    return accounts


@router.post("/companies/{company_id}/accounts")
async def add_account(company_id: str, body: AccountIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    db = get_db()
    parent = await db.accounts.find_one({"company_id": company_id, "code": body.parent_code})
    if not parent or parent["level"] != 2:
        raise HTTPException(400, "Scegli un conto di secondo livello (es. 60.02) sotto cui creare il sottoconto.")
    if not body.name.strip():
        raise HTTPException(400, "Indica il nome del conto.")
    used = {a["code"] async for a in db.accounts.find({"company_id": company_id, "code": {"$regex": f"^{re.escape(body.parent_code)}\\."}})}
    n = next(i for i in range(50, 100) if f"{body.parent_code}.{i:02d}" not in used)
    code = f"{body.parent_code}.{n:02d}"
    sibling = await db.accounts.find_one({"company_id": company_id, "code": {"$regex": f"^{re.escape(body.parent_code)}\\."}, "postable": True})
    doc = {"id": new_id(), "company_id": company_id, "code": code, "name": body.name.strip(), "kind": parent["kind"], "level": 3,
           "postable": True, "cee": body.cee or (sibling or {}).get("cee"), "cee_neg": (sibling or {}).get("cee_neg"),
           "key": None, "party": None, "system": False, "active": True}
    await db.accounts.insert_one(dict(doc))
    await audit.log(user, "conto_creato", company_id, f"{code} {doc['name']}")
    doc.pop("_id", None)
    return doc


@router.patch("/companies/{company_id}/accounts/{code}")
async def update_account(company_id: str, code: str, body: AccountUpdate, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    if "name" in changes and not changes["name"].strip():
        raise HTTPException(400, "Il nome non può essere vuoto.")
    res = await get_db().accounts.update_one({"company_id": company_id, "code": code}, {"$set": changes})
    if not res.matched_count:
        raise HTTPException(404, "Conto non trovato.")
    return {"ok": True}


@router.delete("/companies/{company_id}/accounts/{code}")
async def delete_account(company_id: str, code: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    db = get_db()
    a = await db.accounts.find_one({"company_id": company_id, "code": code})
    if not a:
        raise HTTPException(404, "Conto non trovato.")
    if a.get("system"):
        raise HTTPException(400, "I conti di base non si eliminano: puoi rinominarli o disattivarli.")
    if await db.entries.find_one({"company_id": company_id, "lines.account": code}):
        raise HTTPException(400, "Il conto ha delle registrazioni: non si può eliminare.")
    await db.accounts.delete_one({"id": a["id"]})
    return {"ok": True}


@router.get("/companies/{company_id}/accounting-settings")
async def get_settings(company_id: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    chart = await acc.load_chart(get_db(), company)
    return {"category_map": {c: chart.for_category(c) for c in CATEGORIES if c not in {"Intercompany", "Giroconti"}},
            "enabled": company.get("accounting_enabled", True), "lock_date": company.get("accounting_lock_date")}


@router.put("/companies/{company_id}/accounting-settings")
async def put_settings(company_id: str, body: SettingsIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_accounting")
    db = get_db()
    chart = await acc.load_chart(db, company)
    for cat, code in body.category_map.items():
        if cat not in CATEGORIES or code not in chart.by_code or not chart.by_code[code].get("postable"):
            raise HTTPException(400, f"Collegamento non valido per {cat}.")
    await db.companies.update_one({"id": company_id}, {"$set": {"accounting_category_map": body.category_map,
                                                                "accounting_enabled": body.enabled}})
    stats = await acc.sync_company(db, company_id)
    await audit.log(user, "impostazioni_contabili", company_id)
    return {"ok": True, "sync": stats}


@router.post("/companies/{company_id}/accounting/sync")
async def sync(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    return await acc.sync_company(get_db(), company_id)


# ---------------- prima nota

class LineIn(BaseModel):
    account: str
    dare: int = 0
    avere: int = 0
    party_name: str | None = None
    cost_center_id: str | None = None
    description: str | None = None


class EntryIn(BaseModel):
    date: str
    causale: str = "GEN"
    description: str = ""
    doc_number: str | None = None
    doc_date: str | None = None
    lines: list[LineIn]


@router.get("/companies/{company_id}/entries")
async def journal(company_id: str, year: int | None = None, date_from: str | None = None, date_to: str | None = None,
                  account: str | None = None, q: str | None = None, source: str | None = None,
                  limit: int = Query(200, le=1000), offset: int = 0, newest_first: bool = False,
                  user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    f, t = _year_range(year, date_from, date_to)
    return await rep.journal(get_db(), company_id, f, t, account, q, source, limit, offset, newest_first)


@router.get("/companies/{company_id}/entry-templates")
async def templates(company_id: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    return {"templates": await close.templates_for(get_db(), company), "causali": acc.CAUSALI}


@router.post("/companies/{company_id}/entries")
async def create_entry(company_id: str, body: EntryIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_accounting")
    try:
        e = await acc.save_manual_entry(get_db(), company, body.model_dump(), user)
    except (acc.AccountingError, ValueError) as ex:
        _err(ex)
    await audit.log(user, "registrazione_manuale", company_id, e["description"])
    return e


@router.put("/entries/{entry_id}")
async def update_entry(entry_id: str, body: EntryIn, user: dict = Depends(get_current_user)):
    e, _ = await load("entries", entry_id, user, "manage_accounting")
    company = await get_db().companies.find_one({"id": e["company_id"]}, {"_id": 0})
    try:
        out = await acc.save_manual_entry(get_db(), company, body.model_dump(), user, entry_id)
    except (acc.AccountingError, ValueError) as ex:
        _err(ex)
    await audit.log(user, "registrazione_modificata", e["company_id"], out["description"])
    return out


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, user: dict = Depends(get_current_user)):
    e, _ = await load("entries", entry_id, user, "manage_accounting")
    company = await get_db().companies.find_one({"id": e["company_id"]}, {"_id": 0})
    if e["source"] != "manuale":
        raise HTTPException(400, "Le registrazioni automatiche si eliminano annullando l'operazione d'origine.")
    if acc.is_locked(company, e["date"]):
        raise HTTPException(400, "La registrazione è in un periodo chiuso.")
    await get_db().entries.delete_one({"id": entry_id})
    await audit.log(user, "registrazione_eliminata", e["company_id"], e["description"])
    return {"ok": True}


# ---------------- mastrini, verifica, bilancio, registri

@router.get("/companies/{company_id}/ledger")
async def ledger(company_id: str, account: str, year: int | None = None, date_from: str | None = None,
                 date_to: str | None = None, party_key: str | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    try:
        return await rep.ledger(get_db(), company_id, account, *_year_range(year, date_from, date_to), party_key)
    except ValueError as ex:
        raise HTTPException(404, str(ex))


@router.get("/companies/{company_id}/parties")
async def parties(company_id: str, account: str, date_to: str | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    return await rep.parties(get_db(), company_id, account, date_to or today().isoformat())


@router.get("/companies/{company_id}/trial-balance")
async def trial(company_id: str, year: int | None = None, date_from: str | None = None, date_to: str | None = None,
                user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    return await rep.trial_balance(get_db(), company_id, *_year_range(year, date_from, date_to))


@router.get("/companies/{company_id}/statements")
async def statements(company_id: str, year: int | None = None, date_to: str | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    y = year or today().year
    return await rep.financial_statements(get_db(), company_id, y, date_to, cost_center_id="")


@router.get("/companies/{company_id}/vat-registers")
async def vat_registers(company_id: str, direction: str = "attiva", year: int | None = None, date_from: str | None = None,
                        date_to: str | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    if direction not in {"attiva", "passiva"}:
        raise HTTPException(400, "Registro non valido.")
    return await rep.vat_registers(get_db(), company_id, direction, *_year_range(year, date_from, date_to))


@router.get("/companies/{company_id}/accounting-checks")
async def checks(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    return await rep.checks(get_db(), company_id)


@router.post("/companies/{company_id}/vat-settlements")
async def vat_settlements(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_accounting")
    n = await close.post_vat_settlements(get_db(), company, year or today().year)
    await audit.log(user, "liquidazioni_iva_registrate", company_id, details={"periodi": n})
    return {"posted": n}


# ---------------- centri di costo

class CostCenterIn(BaseModel):
    name: str
    description: str = ""


@router.get("/companies/{company_id}/cost-centers")
async def list_cc(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view")
    return await get_db().cost_centers.find({"company_id": company_id}, {"_id": 0}).sort("name", 1).to_list(200)


@router.post("/companies/{company_id}/cost-centers")
async def add_cc(company_id: str, body: CostCenterIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    if not body.name.strip():
        raise HTTPException(400, "Indica il nome.")
    doc = {"id": new_id(), "company_id": company_id, "name": body.name.strip(), "description": body.description.strip(),
           "created_at": now_iso()}
    await get_db().cost_centers.insert_one(dict(doc))
    return doc


@router.delete("/cost-centers/{cc_id}")
async def delete_cc(cc_id: str, user: dict = Depends(get_current_user)):
    cc, _ = await load("cost_centers", cc_id, user, "manage_accounting")
    if await get_db().entries.find_one({"company_id": cc["company_id"], "lines.cost_center_id": cc_id}):
        raise HTTPException(400, "Il centro di costo è usato in alcune registrazioni.")
    await get_db().cost_centers.delete_one({"id": cc_id})
    return {"ok": True}


@router.get("/companies/{company_id}/cost-center-report")
async def cc_report(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    return await rep.cost_center_report(get_db(), company_id, *_year_range(year, None, None))


# ---------------- contabilizzazione di fatture e movimenti

class InvoiceAccountingIn(BaseModel):
    account_code: str | None = None
    cost_center_id: str | None = None
    remember_for_supplier: bool = True


class AssetFromInvoiceIn(BaseModel):
    category: str
    name: str = ""
    first_year_half: bool = True


class TxCostCenterIn(BaseModel):
    cost_center_id: str | None = None


@router.get("/invoices/{invoice_id}/accounting")
async def invoice_accounting(invoice_id: str, user: dict = Depends(get_current_user)):
    inv, _ = await load("invoices", invoice_id, user, "view_accounting")
    db = get_db()
    company = await db.companies.find_one({"id": inv["company_id"]}, {"_id": 0})
    chart = await acc.load_chart(db, company)
    entry = await db.entries.find_one({"source_key": f"inv:{invoice_id}"}, {"_id": 0})
    if entry:
        for l in entry["lines"]:
            l["account_name"] = chart.name(l["account"])
    kinds = {"costo", "attivo"} if inv["direction"] == "passiva" else {"ricavo"}
    options = [{"code": a["code"], "name": a["name"], "kind": a["kind"]} for a in chart.by_code.values()
               if a.get("postable") and a["kind"] in kinds and a.get("active", True)
               and (a["kind"] != "attivo" or a["code"].startswith("10."))]
    return {"entry": entry, "options": options, "account_code": inv.get("account_code"),
            "cost_center_id": inv.get("cost_center_id"), "locked": acc.is_locked(company, (entry or {}).get("date", "9999")),
            "asset_categories": {k: v[0] for k, v in close.ASSET_CATEGORIES.items()}}


@router.put("/invoices/{invoice_id}/accounting")
async def set_invoice_accounting(invoice_id: str, body: InvoiceAccountingIn, user: dict = Depends(get_current_user)):
    inv, _ = await load("invoices", invoice_id, user, "manage_accounting")
    db = get_db()
    company = await db.companies.find_one({"id": inv["company_id"]}, {"_id": 0})
    if acc.is_locked(company, inv.get("registration_date") or inv["date"]):
        raise HTTPException(400, "La fattura è registrata in un periodo chiuso.")
    chart = await acc.load_chart(db, company)
    if body.account_code and body.account_code not in chart.by_code:
        raise HTTPException(400, "Conto non valido.")
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"account_code": body.account_code, "cost_center_id": body.cost_center_id}})
    if body.remember_for_supplier and body.account_code and inv["direction"] == "passiva":
        key = acc.party_of(inv)[0]
        await db.supplier_accounts.update_one({"company_id": inv["company_id"], "party_key": key}, {"$set": {
            "company_id": inv["company_id"], "party_key": key, "party_name": inv["counterparty_name"],
            "account_code": body.account_code, "updated_at": now_iso()}}, upsert=True)
        # le altre fatture dello stesso fornitore ancora sul conto predefinito seguono la nuova scelta
        async for other in db.invoices.find({"company_id": inv["company_id"], "direction": "passiva", "account_code": None}):
            if acc.party_of(other)[0] == key:
                await acc.sync_source(db, "invoice", other["id"])
    await acc.sync_source(db, "invoice", invoice_id)
    await audit.log(user, "contabilizzazione_fattura", inv["company_id"], inv["number"], {"conto": body.account_code})
    return {"ok": True}


@router.post("/invoices/{invoice_id}/as-asset")
async def invoice_as_asset(invoice_id: str, body: AssetFromInvoiceIn, user: dict = Depends(get_current_user)):
    inv, _ = await load("invoices", invoice_id, user, "manage_accounting")
    if inv["direction"] != "passiva":
        raise HTTPException(400, "Solo le fatture di acquisto possono diventare un cespite.")
    if body.category not in close.ASSET_CATEGORIES:
        raise HTTPException(400, "Categoria non valida.")
    db = get_db()
    company = await db.companies.find_one({"id": inv["company_id"]}, {"_id": 0})
    chart = await acc.load_chart(db, company)
    label, rate, asset_key, _, _ = close.ASSET_CATEGORIES[body.category]
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"account_code": chart.k(asset_key)}})
    await acc.sync_source(db, "invoice", invoice_id)
    asset = {"id": new_id(), "company_id": inv["company_id"], "name": body.name.strip() or inv.get("description") or label,
             "category": body.category, "rate": rate, "cost_cents": inv.get("taxable_cents") or inv["total_cents"],
             "purchase_date": inv["date"], "first_year_half": body.first_year_half, "invoice_id": invoice_id,
             "supplier": inv["counterparty_name"], "accumulated_before_cents": 0, "accumulated_before_year": None,
             "disposed_date": None, "cost_center_id": inv.get("cost_center_id"), "created_at": now_iso()}
    await db.assets.insert_one(dict(asset))
    await audit.log(user, "cespite_da_fattura", inv["company_id"], asset["name"])
    return close.asset_summary(asset, today().year)


@router.put("/transactions/{tx_id}/cost-center")
async def tx_cost_center(tx_id: str, body: TxCostCenterIn, user: dict = Depends(get_current_user)):
    tx, _ = await load("transactions", tx_id, user, "categorize")
    await get_db().transactions.update_one({"id": tx_id}, {"$set": {"cost_center_id": body.cost_center_id}})
    await acc.sync_source(get_db(), "transaction", tx_id)
    return {"ok": True}


# ---------------- cespiti

class AssetIn(BaseModel):
    name: str
    category: str
    cost: str
    purchase_date: str
    rate: float | None = None
    first_year_half: bool = True
    accumulated_before: str = ""
    accumulated_before_year: int | None = None
    disposed_date: str | None = None
    cost_center_id: str | None = None


def _asset_doc(body: AssetIn) -> dict:
    if body.category not in close.ASSET_CATEGORIES:
        raise HTTPException(400, "Categoria non valida.")
    try:
        parse_date(body.purchase_date)
        cost = to_cents(body.cost)
        before = to_cents(body.accumulated_before) if body.accumulated_before.strip() else 0
    except ValueError:
        raise HTTPException(400, "Data o importo non validi.")
    if cost <= 0 or before < 0 or before > cost:
        raise HTTPException(400, "Controlla costo e ammortamenti già fatti.")
    rate = body.rate if body.rate is not None else close.ASSET_CATEGORIES[body.category][1]
    if not 0 < rate <= 100:
        raise HTTPException(400, "Aliquota non valida.")
    return {"name": body.name.strip() or close.ASSET_CATEGORIES[body.category][0], "category": body.category, "rate": rate,
            "cost_cents": cost, "purchase_date": body.purchase_date, "first_year_half": body.first_year_half,
            "accumulated_before_cents": before, "accumulated_before_year": body.accumulated_before_year if before else None,
            "disposed_date": body.disposed_date or None, "cost_center_id": body.cost_center_id}


@router.get("/companies/{company_id}/assets")
async def list_assets(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    y = year or today().year
    items = [close.asset_summary(a, y) for a in await get_db().assets.find({"company_id": company_id}, {"_id": 0}).to_list(2000)]
    posted = await get_db().entries.find_one({"company_id": company_id, "source_key": f"amm:{y}"}, {"_id": 0, "lines": 0})
    return {"year": y, "items": sorted(items, key=lambda a: a["purchase_date"]),
            "categories": {k: {"label": v[0], "rate": v[1]} for k, v in close.ASSET_CATEGORIES.items()},
            "totals": {"cost": sum(a["cost_cents"] for a in items), "fund": sum(a["fund_cents"] for a in items),
                       "quota": sum(a["quota_cents"] for a in items)},
            "posted": posted}


@router.post("/companies/{company_id}/assets")
async def add_asset(company_id: str, body: AssetIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    doc = {"id": new_id(), "company_id": company_id, **_asset_doc(body), "invoice_id": None, "created_at": now_iso()}
    await get_db().assets.insert_one(dict(doc))
    await audit.log(user, "cespite_creato", company_id, doc["name"])
    return close.asset_summary(doc, today().year)


@router.put("/assets/{asset_id}")
async def update_asset(asset_id: str, body: AssetIn, user: dict = Depends(get_current_user)):
    a, _ = await load("assets", asset_id, user, "manage_accounting")
    await get_db().assets.update_one({"id": asset_id}, {"$set": _asset_doc(body)})
    return {"ok": True}


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, user: dict = Depends(get_current_user)):
    a, _ = await load("assets", asset_id, user, "manage_accounting")
    await get_db().assets.delete_one({"id": asset_id})
    await audit.log(user, "cespite_eliminato", a["company_id"], a["name"])
    return {"ok": True}


@router.get("/assets/{asset_id}/schedule")
async def asset_plan(asset_id: str, user: dict = Depends(get_current_user)):
    a, _ = await load("assets", asset_id, user, "view_accounting")
    return {"asset": close.asset_summary(a, today().year), "rows": close.asset_schedule(a)}


@router.post("/companies/{company_id}/depreciation")
async def depreciation(company_id: str, year: int, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_accounting")
    try:
        r = await close.post_depreciation(get_db(), company, year)
    except acc.AccountingError as ex:
        _err(ex)
    await audit.log(user, "ammortamenti_registrati", company_id, str(year), {"totale": r["total_cents"]})
    return r


# ---------------- ratei e risconti

class AccrualIn(BaseModel):
    kind: str
    description: str
    amount: str
    start: str
    end: str
    account_code: str
    year: int
    cost_center_id: str | None = None


@router.get("/companies/{company_id}/accruals")
async def list_accruals(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    q = {"company_id": company_id}
    if year:
        q["year"] = year
    items = await get_db().accruals.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "kinds": {k: v[0] for k, v in close.ACCRUAL_KINDS.items()}}


@router.post("/companies/{company_id}/accruals")
async def add_accrual(company_id: str, body: AccrualIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_accounting")
    if body.kind not in close.ACCRUAL_KINDS:
        raise HTTPException(400, "Tipo non valido.")
    try:
        amount = to_cents(body.amount)
        year_end = f"{body.year}-12-31"
        portion = close.accrual_amount(body.kind, amount, body.start, body.end, year_end)
    except (ValueError, acc.AccountingError) as ex:
        _err(ex)
    if portion <= 0:
        raise HTTPException(400, "Per queste date non c'è nulla da rettificare a fine anno.")
    chart = await acc.load_chart(get_db(), company)
    expected = close.ACCRUAL_KINDS[body.kind][2]
    if chart.by_code.get(body.account_code, {}).get("kind") != expected:
        raise HTTPException(400, f"Scegli un conto di {expected}.")
    doc = {"id": new_id(), "company_id": company_id, "kind": body.kind, "description": body.description.strip(),
           "amount_cents": amount, "start": body.start, "end": body.end, "account_code": body.account_code,
           "year": body.year, "year_end": year_end, "portion_cents": portion, "cost_center_id": body.cost_center_id,
           "created_by": user["id"], "created_at": now_iso()}
    try:
        await close.post_accrual(get_db(), company, doc)
    except acc.AccountingError as ex:
        _err(ex)
    await get_db().accruals.insert_one(dict(doc))
    await audit.log(user, "rateo_risconto", company_id, doc["description"], {"importo": portion})
    return doc


@router.delete("/accruals/{accrual_id}")
async def delete_accrual(accrual_id: str, user: dict = Depends(get_current_user)):
    a, _ = await load("accruals", accrual_id, user, "manage_accounting")
    db = get_db()
    company = await db.companies.find_one({"id": a["company_id"]}, {"_id": 0})
    for key in (f"rat:{a['id']}", f"rat:{a['id']}:storno"):
        if await acc.upsert_auto_entry(db, company, key, None) == "bloccata":
            raise HTTPException(400, "L'esercizio è chiuso.")
    await db.accruals.delete_one({"id": accrual_id})
    return {"ok": True}


# ---------------- esercizi

@router.get("/companies/{company_id}/fiscal-years")
async def years(company_id: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    return {"years": await close.fiscal_years(get_db(), company), "lock_date": company.get("accounting_lock_date")}


@router.post("/companies/{company_id}/fiscal-years/{year}/close")
async def close_year(company_id: str, year: int, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "close_fiscal_year")
    try:
        r = await close.close_year(get_db(), company, year, user)
    except acc.AccountingError as ex:
        _err(ex)
    await audit.log(user, "esercizio_chiuso", company_id, str(year), {"risultato": r["result_cents"]})
    return r


@router.post("/companies/{company_id}/fiscal-years/{year}/reopen")
async def reopen(company_id: str, year: int, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "close_fiscal_year")
    try:
        await close.reopen_year(get_db(), company, year)
    except acc.AccountingError as ex:
        _err(ex)
    await audit.log(user, "esercizio_riaperto", company_id, str(year))
    return {"ok": True}


# ---------------- export

@router.get("/companies/{company_id}/accounting-export")
async def export(company_id: str, kind: str, year: int | None = None, date_from: str | None = None,
                 date_to: str | None = None, format: str = "xlsx", user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    from ..services.accounting_export import build
    try:
        content, media, filename = await build(get_db(), company, kind, *_year_range(year, date_from, date_to), format)
    except ValueError as ex:
        _err(ex)
    await audit.log(user, "export_contabile", company_id, filename)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

