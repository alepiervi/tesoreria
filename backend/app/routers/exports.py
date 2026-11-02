import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from .. import audit
from ..db import get_db
from ..deps import get_current_user, require
from ..services.export import build_csv, build_xlsx, build_xml_zip

router = APIRouter(tags=["exports"])


@router.get("/companies/{company_id}/export")
async def export(company_id: str, date_from: str, date_to: str, format: str = "xlsx",
                 user: dict = Depends(get_current_user)):
    await require(user, company_id, "export")
    if date_from > date_to:
        raise HTTPException(400, "La data iniziale è successiva a quella finale.")
    db = get_db()
    company = await db.companies.find_one({"id": company_id}, {"_id": 0})
    period = f"{date_from} → {date_to}"
    date_q = {"$gte": date_from, "$lte": date_to}
    transactions = await db.transactions.find({"company_id": company_id, "date": date_q}, {"_id": 0}) \
        .sort("date", 1).to_list(50000)
    invoices = await db.invoices.find({"company_id": company_id, "date": date_q}, {"_id": 0}).sort("date", 1).to_list(20000)
    accounts = {a["id"]: a for a in await db.bank_accounts.find({"company_id": company_id}, {"_id": 0}).to_list(100)}
    slug = re.sub(r"[^A-Za-z0-9]+", "_", company["name"]).strip("_").lower()
    base = f"{slug}_{date_from}_{date_to}"

    if format == "xlsx":
        deadlines = await db.deadlines.find({"company_id": company_id, "due_date": date_q}, {"_id": 0}) \
            .sort("due_date", 1).to_list(20000)
        notes_by_tx: dict[str, list] = {}
        async for n in db.notes.find({"company_id": company_id, "target_type": "transaction"}, {"_id": 0}):
            notes_by_tx.setdefault(n["target_id"], []).append(n)
        content = build_xlsx(company, period, transactions, invoices, deadlines, accounts, notes_by_tx)
        media, filename = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{base}.xlsx"
    elif format == "csv":
        content = build_csv(transactions, accounts)
        media, filename = "text/csv", f"prima_nota_{base}.csv"
    elif format == "xml":
        ids = [i["id"] for i in invoices]
        names = {i["id"]: f"{i['direction']}_{re.sub(r'[^A-Za-z0-9]+', '_', i['number'])}_{i['id'][:6]}.xml" for i in invoices}
        xml_docs = [(names[x["invoice_id"]], x["xml"]) async for x in
                    db.invoice_xml.find({"invoice_id": {"$in": ids}}, {"_id": 0})]
        if not xml_docs:
            raise HTTPException(404, "Nessuna fattura XML nel periodo scelto.")
        content = build_xml_zip(xml_docs)
        media, filename = "application/zip", f"fatture_xml_{base}.zip"
    else:
        raise HTTPException(400, "Formato non supportato: usa xlsx, csv o xml.")

    await audit.log(user, "export", company_id, filename, {"formato": format, "periodo": period})
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/monthly")
async def monthly_report(month: str, company_id: str | None = None, user: dict = Depends(get_current_user)):
    """Report mensile in PDF. Senza company_id: tutte le aziende che l'utente può esportare."""
    from ..services.report import build_monthly_pdf
    from .common import companies_with
    if not re.fullmatch(r"\d{4}-\d{2}", month) or not 1 <= int(month[5:]) <= 12:
        raise HTTPException(400, "Mese non valido (formato AAAA-MM).")
    scope = await companies_with(user, "export", company_id)
    if not scope:
        raise HTTPException(403, "Il tuo ruolo non permette di scaricare i report.")
    pdf = await build_monthly_pdf(get_db(), list(scope), month, None if company_id else
                                  ("Gruppo" if len(scope) > 1 else None))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", scope[company_id]["name"]).strip("_").lower() if company_id else "gruppo"
    await audit.log(user, "report_mensile", company_id, month)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="report_{slug}_{month}.pdf"'})
