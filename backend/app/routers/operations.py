"""Paghe, chiusura del mese, fatture da classificare, commesse, rimanenze, export per il gestionale."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services import accounting as acc
from ..services import account_suggest, inventory, month_close, payroll
from ..services.accounting_export import DEFAULT_EXPORT, EXPORT_FIELDS, export_journal, export_parties
from ..utils import new_id, now_iso, parse_date, to_cents
from .common import load

router = APIRouter(tags=["operations"])


async def _company(company_id: str, user: dict, perm: str) -> dict:
    await require(user, company_id, perm)
    return await get_db().companies.find_one({"id": company_id}, {"_id": 0})


# ---------------- paghe

class PayrollIn(BaseModel):
    month: str
    employees: int | None = None
    lordo: str = "0"
    contributi_ditta: str = "0"
    contributi_dipendente: str = "0"
    irpef: str = "0"
    altre_trattenute: str = "0"
    netto: str = "0"
    tfr: str = "0"
    pay_date: str | None = None
    cost_center_id: str | None = None
    note: str = ""


PAYROLL_PROMPT = (
    "Questo è il riepilogo paghe mensile (prospetto contabile o libro unico) di un'azienda italiana. Rispondi SOLO con JSON: "
    '{"mese": "AAAA-MM", "dipendenti": numero, "lordo": numero, "contributi_ditta": numero, "contributi_dipendente": numero, '
    '"irpef": numero, "altre_trattenute": numero, "netto": numero, "tfr": numero}. Importi in euro, totali di tutti i dipendenti. '
    "contributi_ditta = contributi INPS a carico azienda; irpef = ritenute fiscali (IRPEF e addizionali); "
    "tfr = quota TFR maturata nel mese. Se un dato manca usa 0."
)


@router.get("/companies/{company_id}/payrolls")
async def list_payrolls(company_id: str, year: int | None = None, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    q = {"company_id": company_id}
    if year:
        q["month"] = {"$regex": f"^{year}-"}
    items = await get_db().payrolls.find(q, {"_id": 0}).sort("month", -1).to_list(200)
    totals = {f: sum(i.get(f"{f}_cents", 0) for i in items) for f in payroll.FIELDS}
    return {"items": items, "totals": totals}


async def _save_payroll(company: dict, body: PayrollIn, user: dict, payroll_id: str | None = None) -> dict:
    db = get_db()
    try:
        p = payroll.from_body(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e) or "Dati non validi.")
    errors = payroll.check(p)
    if errors:
        raise HTTPException(400, " ".join(errors))
    dup = await db.payrolls.find_one({"company_id": company["id"], "month": p["month"]})
    if dup and dup["id"] != payroll_id:
        raise HTTPException(400, "Le paghe di questo mese sono già inserite: modificale invece di aggiungerle di nuovo.")
    doc = {**p, "id": payroll_id or new_id(), "company_id": company["id"], "updated_at": now_iso(),
           "updated_by_name": user.get("name") or user["email"]}
    try:
        await payroll.post(db, company, doc)
    except acc.AccountingError as e:
        raise HTTPException(400, str(e))
    await db.payrolls.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
    await audit.log(user, "paghe_registrate", company["id"], payroll.label(doc["month"]), {"netto": doc["netto_cents"]})
    return doc


@router.post("/companies/{company_id}/payrolls")
async def add_payroll(company_id: str, body: PayrollIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_payroll")
    return await _save_payroll(company, body, user)


@router.put("/payrolls/{payroll_id}")
async def update_payroll(payroll_id: str, body: PayrollIn, user: dict = Depends(get_current_user)):
    p, _ = await load("payrolls", payroll_id, user, "manage_payroll")
    company = await get_db().companies.find_one({"id": p["company_id"]}, {"_id": 0})
    return await _save_payroll(company, body, user, payroll_id)


@router.delete("/payrolls/{payroll_id}")
async def delete_payroll(payroll_id: str, user: dict = Depends(get_current_user)):
    p, _ = await load("payrolls", payroll_id, user, "manage_payroll")
    db = get_db()
    company = await db.companies.find_one({"id": p["company_id"]}, {"_id": 0})
    try:
        await payroll.remove(db, company, p)
    except acc.AccountingError as e:
        raise HTTPException(400, str(e))
    await db.payrolls.delete_one({"id": payroll_id})
    await audit.log(user, "paghe_eliminate", p["company_id"], payroll.label(p["month"]))
    return {"ok": True}


@router.post("/companies/{company_id}/payrolls/read")
async def read_payroll(company_id: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_payroll")
    from ..integrations.ai import get_ai
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "File troppo grande (massimo 10 MB).")
    ai = get_ai()
    result = await ai.read_document(data, file.content_type or "application/pdf", PAYROLL_PROMPT) if ai else None
    if not result:
        return {"read": False, "message": "Lettura automatica non disponibile con l'assistente in modalità demo: inserisci i totali "
                                          "dal riepilogo del consulente del lavoro."}
    return {"read": True, "values": {"month": result.get("mese"), "employees": result.get("dipendenti"),
                                     **{f: str(result.get(f) or 0) for f in payroll.FIELDS}}}


# ---------------- chiusura del mese

@router.get("/companies/{company_id}/month-close")
async def month_status(company_id: str, month: str | None = None, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    m = month or month_close.previous_month()
    try:
        parse_date(m + "-01")
    except ValueError:
        raise HTTPException(400, "Mese non valido.")
    return await month_close.checklist(get_db(), company, m)


class CheckIn(BaseModel):
    done: bool
    note: str = ""


@router.put("/companies/{company_id}/month-close/{month}/items/{item}")
async def tick(company_id: str, month: str, item: str, body: CheckIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    if item not in {"documenti", "revisione"}:
        raise HTTPException(400, "Questo controllo si aggiorna da solo.")
    await month_close.set_manual(get_db(), company_id, month, item, body.done, body.note.strip(), user)
    return {"ok": True}


@router.post("/companies/{company_id}/month-close/{month}/close")
async def close_month(company_id: str, month: str, force: bool = False, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "close_fiscal_year")
    db = get_db()
    status = await month_close.checklist(db, company, month)
    if not status["month_ended"]:
        raise HTTPException(400, "Il mese non è ancora finito.")
    if not status["ready"] and not force:
        raise HTTPException(400, f"Mancano ancora {status['missing']} controlli.")
    lock = await month_close.close(db, company, month, user)
    await audit.log(user, "mese_chiuso", company_id, month, {"forzato": force and not status["ready"]})
    return {"ok": True, "lock_date": lock}


@router.post("/companies/{company_id}/month-close/{month}/reopen")
async def reopen_month(company_id: str, month: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "close_fiscal_year")
    try:
        lock = await month_close.reopen(get_db(), company, month)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit.log(user, "mese_riaperto", company_id, month)
    return {"ok": True, "lock_date": lock or None}


# ---------------- fatture da classificare

@router.get("/companies/{company_id}/invoices-to-classify")
async def to_classify(company_id: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "view_accounting")
    db = get_db()
    chart = await acc.load_chart(db, company)
    items = await account_suggest.to_classify(db, company, chart)
    sugg = await account_suggest.suggestions(db, company, items, chart)
    options = [{"code": a["code"], "name": a["name"], "kind": a["kind"]} for a in chart.by_code.values()
               if a.get("postable") and a.get("active", True) and (a["kind"] == "costo" or a["code"].startswith("10."))]
    return {"items": [{**{k: i.get(k) for k in ("id", "number", "date", "counterparty_name", "counterparty_vat", "description",
                                                 "taxable_cents", "total_cents")}, "suggestion": sugg.get(i["id"])} for i in items],
            "options": options}


class ClassifyItem(BaseModel):
    invoice_id: str
    account_code: str


class ClassifyIn(BaseModel):
    items: list[ClassifyItem]
    remember_for_supplier: bool = True


@router.post("/companies/{company_id}/invoices-to-classify")
async def classify(company_id: str, body: ClassifyIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_accounting")
    db = get_db()
    chart = await acc.load_chart(db, company)
    done = 0
    for it in body.items:
        inv = await db.invoices.find_one({"id": it.invoice_id, "company_id": company_id}, {"_id": 0})
        if not inv or it.account_code not in chart.by_code:
            continue
        if acc.is_locked(company, inv.get("registration_date") or inv["date"]):
            continue
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"account_code": it.account_code}})
        if body.remember_for_supplier:
            key = acc.party_of(inv)[0]
            await db.supplier_accounts.update_one({"company_id": company_id, "party_key": key}, {"$set": {
                "company_id": company_id, "party_key": key, "party_name": inv["counterparty_name"],
                "account_code": it.account_code, "updated_at": now_iso()}}, upsert=True)
        await acc.sync_source(db, "invoice", inv["id"])
        done += 1
    if done:
        await audit.log(user, "fatture_classificate", company_id, details={"numero": done})
    return {"classified": done}


# ---------------- commesse

class ProjectIn(BaseModel):
    name: str
    description: str = ""
    customer: str = ""
    budget_revenue: str = "0"
    budget_cost: str = "0"
    start_date: str | None = None
    end_date: str | None = None
    status: str = "aperta"


def _project_doc(body: ProjectIn) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Indica il nome della commessa.")
    if body.status not in {"aperta", "chiusa", "sospesa"}:
        raise HTTPException(400, "Stato non valido.")
    try:
        for d in (body.start_date, body.end_date):
            if d:
                parse_date(d)
        rev, cost = to_cents(body.budget_revenue or 0), to_cents(body.budget_cost or 0)
    except ValueError:
        raise HTTPException(400, "Date o importi non validi.")
    return {"name": body.name.strip(), "description": body.description.strip(), "customer": body.customer.strip(), "kind": "commessa",
            "budget_revenue_cents": rev, "budget_cost_cents": cost, "start_date": body.start_date or None,
            "end_date": body.end_date or None, "status": body.status}


@router.get("/companies/{company_id}/projects")
async def projects(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    db = get_db()
    items = await db.cost_centers.find({"company_id": company_id, "kind": "commessa"}, {"_id": 0}).sort("name", 1).to_list(500)
    if not items:
        return {"items": []}
    accounts = {a["code"]: a async for a in db.accounts.find({"company_id": company_id}, {"_id": 0, "code": 1, "kind": 1})}
    ids = {i["id"] for i in items}
    actual = {i: {"ricavi": 0, "costi": 0} for i in ids}
    async for e in db.entries.find({"company_id": company_id, "lines.cost_center_id": {"$in": list(ids)}, "source": {"$ne": "chiusura"}},
                                   {"lines": 1}):
        for l in e["lines"]:
            cc = l.get("cost_center_id")
            if cc not in ids:
                continue
            kind = accounts.get(l["account"], {}).get("kind")
            if kind == "ricavo":
                actual[cc]["ricavi"] += l["avere"] - l["dare"]
            elif kind == "costo":
                actual[cc]["costi"] += l["dare"] - l["avere"]
    out = []
    for p in items:
        a = actual[p["id"]]
        br, bc = p.get("budget_revenue_cents", 0), p.get("budget_cost_cents", 0)
        out.append({**p, "ricavi_cents": a["ricavi"], "costi_cents": a["costi"], "margine_cents": a["ricavi"] - a["costi"],
                    "margine_previsto_cents": br - bc, "avanzamento_costi": a["costi"] / bc if bc else None,
                    "avanzamento_ricavi": a["ricavi"] / br if br else None,
                    "fuori_budget": bool(bc) and a["costi"] > bc})
    return {"items": out}


@router.post("/companies/{company_id}/projects")
async def add_project(company_id: str, body: ProjectIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "manage_accounting")
    doc = {"id": new_id(), "company_id": company_id, **_project_doc(body), "created_at": now_iso()}
    await get_db().cost_centers.insert_one(dict(doc))
    await audit.log(user, "commessa_creata", company_id, doc["name"])
    return doc


@router.put("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectIn, user: dict = Depends(get_current_user)):
    p, _ = await load("cost_centers", project_id, user, "manage_accounting")
    await get_db().cost_centers.update_one({"id": project_id}, {"$set": _project_doc(body)})
    return {"ok": True}


# ---------------- rimanenze di magazzino

class InventoryItem(BaseModel):
    description: str
    qty: float = 0
    unit_cost: str = "0"


class InventoryIn(BaseModel):
    year: int
    value: str = ""
    items: list[InventoryItem] = []
    note: str = ""


@router.get("/companies/{company_id}/inventories")
async def inventories(company_id: str, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "view_accounting")
    items = await get_db().inventories.find({"company_id": company_id}, {"_id": 0}).sort("year", -1).to_list(50)
    for i in items:
        i["total_cents"] = inventory.total_of(i)
    return {"items": items}


@router.put("/companies/{company_id}/inventories/{year}")
async def save_inventory(company_id: str, year: int, body: InventoryIn, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "manage_accounting")
    try:
        lines = [{"description": i.description.strip(), "qty": float(i.qty), "unit_cost_cents": to_cents(i.unit_cost or 0)}
                 for i in body.items if i.description.strip()]
        value = to_cents(body.value) if body.value.strip() else 0
    except ValueError:
        raise HTTPException(400, "Importi non validi.")
    if any(i["qty"] < 0 or i["unit_cost_cents"] < 0 for i in lines) or value < 0:
        raise HTTPException(400, "Quantità e importi non possono essere negativi.")
    doc = {"company_id": company_id, "year": year, "items": lines, "value_cents": value, "note": body.note.strip(),
           "updated_at": now_iso(), "updated_by_name": user.get("name") or user["email"]}
    try:
        await inventory.post(get_db(), company, doc)
    except acc.AccountingError as e:
        raise HTTPException(400, str(e))
    await get_db().inventories.update_one({"company_id": company_id, "year": year},
                                          {"$set": doc, "$setOnInsert": {"id": new_id()}}, upsert=True)
    await audit.log(user, "rimanenze_registrate", company_id, str(year), {"valore": inventory.total_of(doc)})
    return {"ok": True, "total_cents": inventory.total_of(doc)}


# ---------------- export per il gestionale del commercialista

class ExportCfgIn(BaseModel):
    format: str = "csv"
    separator: str = ";"
    decimal: str = ","
    date_format: str = "gg/mm/aaaa"
    header: bool = True
    columns: list[str] = DEFAULT_EXPORT["columns"]
    account_map: dict[str, str] = {}
    causale_map: dict[str, str] = {}


@router.get("/companies/{company_id}/export-settings")
async def export_settings(company_id: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "export")
    return {"settings": {**DEFAULT_EXPORT, **(company.get("export_settings") or {})}, "fields": EXPORT_FIELDS}


@router.put("/companies/{company_id}/export-settings")
async def save_export_settings(company_id: str, body: ExportCfgIn, user: dict = Depends(get_current_user)):
    await _company(company_id, user, "export")
    cfg = body.model_dump()
    if cfg["format"] not in {"csv", "xlsx"} or cfg["separator"] not in {";", ",", "tab", "|"} or cfg["decimal"] not in {",", "."}:
        raise HTTPException(400, "Formato non valido.")
    cfg["columns"] = [c for c in cfg["columns"] if c in EXPORT_FIELDS]
    if not cfg["columns"]:
        raise HTTPException(400, "Scegli almeno una colonna.")
    cfg["account_map"] = {k: v.strip() for k, v in cfg["account_map"].items() if v and v.strip()}
    await get_db().companies.update_one({"id": company_id}, {"$set": {"export_settings": cfg}})
    return {"ok": True}


@router.get("/companies/{company_id}/journal-export")
async def journal_export(company_id: str, date_from: str, date_to: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "export")
    await require(user, company_id, "view_accounting")
    try:
        parse_date(date_from)
        parse_date(date_to)
    except ValueError:
        raise HTTPException(400, "Date non valide.")
    content, media, name = await export_journal(get_db(), company, date_from, date_to, company.get("export_settings") or {})
    await audit.log(user, "export_contabile", company_id, name)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/companies/{company_id}/parties-export")
async def parties_export(company_id: str, user: dict = Depends(get_current_user)):
    company = await _company(company_id, user, "export")
    content, media, name = await export_parties(get_db(), company)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


