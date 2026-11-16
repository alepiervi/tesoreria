import io
import re
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..integrations import acube
from ..integrations.acube import AcubeError
from ..integrations.sdi import get_sdi_provider
from ..services.fatturapa import FatturaPAError, parse_fatturapa, unwrap_p7m
from ..services.invoices import register_invoice
from ..utils import now_iso, to_cents
from .common import assert_open, load

router = APIRouter(tags=["invoices"])

MAX_XML_BYTES = 5 * 1024 * 1024
MAX_ZIP_BYTES = 60 * 1024 * 1024
MAX_ZIP_FILES = 5000


def _expand(name: str, data: bytes, depth: int = 0) -> list[tuple[str, bytes]]:
    """Un file ZIP (es. scarico massivo dal cassetto fiscale) diventa l'elenco delle fatture che contiene."""
    if data[:2] != b"PK":
        return [(name, data)]
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise FatturaPAError("Il file ZIP è danneggiato.")
    out, total = [], 0
    for info in zf.infolist()[:MAX_ZIP_FILES]:
        low = info.filename.lower()
        if info.is_dir() or "metadato" in low or "__macosx" in low or not low.endswith((".xml", ".p7m", ".zip")):
            continue
        total += info.file_size
        if info.file_size > MAX_ZIP_BYTES or total > 4 * MAX_ZIP_BYTES:
            raise FatturaPAError("Lo ZIP è troppo grande: dividilo in più parti.")
        inner = zf.read(info)
        if low.endswith(".zip") and depth < 2:
            out += _expand(info.filename, inner, depth + 1)
        elif not low.endswith(".zip"):
            out.append((info.filename.rsplit("/", 1)[-1], inner))
    return out


class InvoiceIn(BaseModel):
    direction: str  # attiva | passiva
    number: str
    date: str
    due_date: str
    counterparty_name: str
    counterparty_vat: str = ""
    total: str  # importo in euro, es. "1.220,00"
    vat_rate: float = 22
    description: str = ""
    iban: str = ""


@router.get("/companies/{company_id}/invoices")
async def list_invoices(company_id: str, direction: str | None = None, status: str | None = None,
                        q: str | None = None, user: dict = Depends(get_current_user)):
    await require(user, company_id, "view")
    query: dict = {"company_id": company_id}
    if direction:
        query["direction"] = direction
    if status == "open":
        query["status"] = {"$in": ["aperta", "parziale"]}
    elif status:
        query["status"] = status
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"number": rx}, {"counterparty_name": rx}]
    return await get_db().invoices.find(query, {"_id": 0}).sort("date", -1).to_list(2000)


@router.post("/companies/{company_id}/invoices/import")  # accetta .xml e .p7m
async def import_xml(company_id: str, files: list[UploadFile] = File(...), user: dict = Depends(get_current_user)):
    """Importa una o più fatture XML (FatturaPA) scaricate dal cassetto fiscale o dal gestionale."""
    await require(user, company_id, "manage_invoices")
    db = get_db()
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    results = []
    for f in files:
        data = await f.read(MAX_ZIP_BYTES + 1)
        limit = MAX_ZIP_BYTES if data[:2] == b"PK" else MAX_XML_BYTES
        if len(data) > limit:
            results.append({"file": f.filename, "ok": False, "error": "File troppo grande."})
            continue
        try:
            entries = _expand(f.filename or "", data)
        except FatturaPAError as e:
            results.append({"file": f.filename, "ok": False, "error": str(e)})
            continue
        if not entries:
            results.append({"file": f.filename, "ok": False, "error": "Nello ZIP non ci sono fatture (.xml o .p7m)."})
        for name, content in entries:
            try:
                docs = parse_fatturapa(content)
                xml_text = unwrap_p7m(content.lstrip(b"\xef\xbb\xbf \r\n\t")).decode("utf-8", errors="replace")
                for doc in docs:
                    inv, created = await register_invoice(db, company, doc, "xml", xml_text)
                    results.append({"file": name, "ok": True, "created": created, "invoice_id": inv["id"],
                                    "number": inv["number"], "direction": inv["direction"],
                                    "counterparty": inv["counterparty_name"], "total_cents": inv["total_cents"]})
            except (FatturaPAError, ValueError) as e:
                results.append({"file": name, "ok": False, "error": str(e)})
    imported = sum(1 for r in results if r.get("ok") and r.get("created"))
    if imported:
        await audit.log(user, "fatture_importate", company_id, details={"numero": imported})
        from ..services.vat import sync_vat_deadlines
        await sync_vat_deadlines(db, company)
    return {"results": results, "imported": imported}


@router.post("/companies/{company_id}/invoices/sync-sdi")
async def sync_sdi(company_id: str, user: dict = Depends(get_current_user)):
    """Scarica le fatture ricevute tramite l'intermediario SDI."""
    await require(user, company_id, "manage_invoices")
    db = get_db()
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    provider = get_sdi_provider()
    if provider is None:
        raise HTTPException(400, "Il collegamento con il cassetto fiscale non è attivo: importa i file XML o ZIP delle fatture.")
    started = now_iso()
    try:
        xmls = await provider.fetch_new_invoices(company)
    except AcubeError as e:
        raise HTTPException(502, str(e))
    created = 0
    for xml in xmls:
        for doc in parse_fatturapa(xml.encode("utf-8")):
            _, was_created = await register_invoice(db, company, doc, "sdi", xml)
            created += int(was_created)
    await db.companies.update_one({"id": company_id}, {"$set": {"acube_last_sync": started}})
    await audit.log(user, "sdi_sincronizzato", company_id, details={"nuove": created})
    if created:
        from ..services.vat import sync_vat_deadlines
        await sync_vat_deadlines(db, company)
    return {"imported": created}


@router.post("/companies/{company_id}/invoices")
async def create_manual(company_id: str, body: InvoiceIn, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_invoices")
    if body.direction not in {"attiva", "passiva"}:
        raise HTTPException(400, "Tipo fattura non valido.")
    try:
        total_cents = to_cents(body.total)
    except ValueError:
        raise HTTPException(400, "Importo non valido.")
    if total_cents <= 0:
        raise HTTPException(400, "L'importo deve essere maggiore di zero.")
    db = get_db()
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    party = {"name": body.counterparty_name.strip(), "vat": body.counterparty_vat.strip()}
    me = {"name": company["name"], "vat": company.get("vat_number", "")}
    doc = {"number": body.number.strip(), "date": body.date, "total_cents": total_cents, "vat_rate": body.vat_rate,
           "installments": [{"due_date": body.due_date, "amount_cents": total_cents}],
           "iban": body.iban.strip(), "description": body.description,
           "seller": me if body.direction == "attiva" else party,
           "buyer": party if body.direction == "attiva" else me}
    inv, created = await register_invoice(db, company, doc, "manuale", direction=body.direction)
    if not created:
        raise HTTPException(409, "Esiste già una fattura con questo numero, data e controparte.")
    await audit.log(user, "fattura_inserita", company_id, f"{inv['number']} {inv['counterparty_name']}")
    from ..services.vat import sync_vat_deadlines
    await sync_vat_deadlines(db, company)
    return inv


@router.get("/invoices/{invoice_id}/xml")
async def download_xml(invoice_id: str, user: dict = Depends(get_current_user)):
    inv, _ = await load("invoices", invoice_id, user, "view")
    doc = await get_db().invoice_xml.find_one({"invoice_id": invoice_id})
    if not doc:
        raise HTTPException(404, "XML non disponibile per questa fattura.")
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", inv["number"])
    return Response(doc["xml"], media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="fattura_{safe}.xml"'})


@router.delete("/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, user: dict = Depends(get_current_user)):
    inv, _ = await load("invoices", invoice_id, user, "manage_invoices")
    if inv.get("paid_cents", 0) > 0:
        raise HTTPException(400, "La fattura ha pagamenti abbinati: annulla prima le riconciliazioni.")
    await assert_open(inv["company_id"], inv.get("registration_date") or inv["date"])
    db = get_db()
    await db.invoices.delete_one({"id": invoice_id})
    from ..services.accounting import sync_source
    await sync_source(db, "invoice", invoice_id)
    await db.invoice_xml.delete_many({"invoice_id": invoice_id})
    await db.deadlines.delete_many({"invoice_id": invoice_id})
    await audit.log(user, "fattura_eliminata", inv["company_id"], f"{inv['number']} {inv['counterparty_name']}")
    return {"ok": True}


def _need_acube():
    p = get_sdi_provider()
    if not p or p.name != "acube":
        raise HTTPException(400, "Il collegamento automatico con il cassetto fiscale non è ancora configurato.")


@router.get("/companies/{company_id}/cassetto")
async def cassetto_status(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_invoices")
    company = await get_db().companies.find_one({"id": company_id}, {"_id": 0})
    p = get_sdi_provider()
    out = {"provider": p.name if p else None, "activated_at": company.get("acube_activated_at"),
           "last_sync": company.get("acube_last_sync")}
    if p and p.name == "acube":
        try:
            out.update(await acube.status(company))
        except AcubeError as e:
            out["error"] = str(e)
    return out


@router.post("/companies/{company_id}/cassetto/activate")
async def cassetto_activate(company_id: str, user: dict = Depends(get_current_user)):
    await require(user, company_id, "manage_invoices")
    _need_acube()
    db = get_db()
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    try:
        result = await acube.activate(company, user.get("email", ""))
    except AcubeError as e:
        raise HTTPException(502, str(e))
    await db.companies.update_one({"id": company_id}, {"$set": {"acube_activated_at": now_iso()}})
    await audit.log(user, "cassetto_fiscale_attivato", company_id, details={"partita_iva": result.get("fiscal_id")})
    return {**result, "activated_at": now_iso()}
