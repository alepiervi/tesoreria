"""Export di libri e prospetti contabili in Excel (e il bilancio anche in PDF)."""
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import accounting_reports as rep

KINDS = {"journal": "libro_giornale", "trial": "bilancio_di_verifica", "statements": "bilancio",
         "vat_sales": "registro_iva_vendite", "vat_purchases": "registro_iva_acquisti"}


def _e(c):
    return round((c or 0) / 100, 2)


def _sheet(wb, title, headers, rows, money=(), bold_rows=()):
    ws = wb.create_sheet(title[:31])
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="15171C")
    for i, r in enumerate(rows, start=2):
        ws.append(r)
        if i - 2 in bold_rows:
            for c in ws[i]:
                c.font = Font(bold=True)
    for col in money:
        for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            for c in row:
                c.number_format = '#,##0.00'
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:500] if i - 1 < len(r) and r[i - 1] is not None] + [8])
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 70)
    ws.freeze_panes = "A2"
    return ws


async def build(db, company: dict, kind: str, date_from: str, date_to: str, fmt: str = "xlsx") -> tuple[bytes, str, str]:
    if kind not in KINDS:
        raise ValueError("Tipo di export non valido.")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", company["name"]).strip("_").lower()
    base = f"{KINDS[kind]}_{slug}_{date_from}_{date_to}"
    if kind == "statements" and fmt == "pdf":
        data = await rep.financial_statements(db, company["id"], int(date_to[:4]), date_to)
        return statements_pdf(company, data), "application/pdf", f"{base}.pdf"
    wb = Workbook()
    wb.remove(wb.active)
    cid = company["id"]
    if kind == "journal":
        j = await rep.journal(db, cid, date_from, date_to, limit=10 ** 7)
        rows = []
        for e in j["items"]:
            for n, l in enumerate(e["lines"]):
                rows.append([e["number"] if n == 0 else None, e["date"] if n == 0 else None, e["causale"] if n == 0 else None,
                             e["description"] if n == 0 else None, l["account"], l["account_name"], l.get("party_name") or "",
                             _e(l["dare"]) or None, _e(l["avere"]) or None])
        rows.append([None, None, None, "Totali", None, None, None, _e(j["totals"]["dare"]), _e(j["totals"]["avere"])])
        _sheet(wb, "Libro giornale", ["N.", "Data", "Causale", "Descrizione", "Conto", "Nome conto", "Controparte", "Dare", "Avere"],
               rows, (8, 9), (len(rows) - 1,))
    elif kind == "trial":
        tb = await rep.trial_balance(db, cid, date_from, date_to)
        rows = [["   " * (r["level"] - 1) + r["code"], r["name"], _e(r["dare"]), _e(r["avere"]),
                 _e(r["saldo"]) if r["saldo"] > 0 else None, _e(-r["saldo"]) if r["saldo"] < 0 else None] for r in tb["rows"]]
        rows.append(["", "Totali", _e(tb["totals"]["dare"]), _e(tb["totals"]["avere"]), _e(tb["saldi"]["dare"]), _e(tb["saldi"]["avere"])])
        _sheet(wb, "Bilancio di verifica", ["Conto", "Descrizione", "Dare", "Avere", "Saldo dare", "Saldo avere"], rows, (3, 4, 5, 6),
               tuple(i for i, r in enumerate(tb["rows"]) if r["level"] == 1) + (len(rows) - 1,))
    elif kind == "statements":
        data = await rep.financial_statements(db, cid, int(date_to[:4]), date_to)
        for title, items in (("Attivo", data["attivo"]), ("Passivo", data["passivo"])):
            rows = [["   " * r["level"] + r["label"], _e(r["amount"]), _e(r["previous"])] for r in items]
            rows.append(["Totale", _e(data["totale_attivo" if title == "Attivo" else "totale_passivo"]), None])
            _sheet(wb, f"SP {title}", ["Voce", str(data["year"]), str(data["year"] - 1)], rows, (2, 3),
                   tuple(i for i, r in enumerate(items) if r["level"] == 0) + (len(rows) - 1,))
        rows = [["   " * r["level"] + r["label"], _e(r["amount"]), _e(r["previous"])] for r in data["conto_economico"]]
        s = data["sintesi"]
        rows += [["Differenza tra valore e costi della produzione (A - B)", _e(s["differenza"]), None],
                 ["Risultato prima delle imposte", _e(s["risultato_ante_imposte"]), None],
                 ["Utile (perdita) dell'esercizio", _e(s["utile"]), _e(s["utile_precedente"])]]
        _sheet(wb, "Conto economico", ["Voce", str(data["year"]), str(data["year"] - 1)], rows, (2, 3),
               tuple(i for i, r in enumerate(data["conto_economico"]) if r["level"] == 0) + (len(rows) - 1,))
    else:
        direction = "attiva" if kind == "vat_sales" else "passiva"
        reg = await rep.vat_registers(db, cid, direction, date_from, date_to)
        rows = []
        for r in reg["rows"]:
            for n, b in enumerate(r["rates"]):
                rows.append([r["protocol"] if n == 0 else None, r["registration_date"] if n == 0 else None, r["date"] if n == 0 else None,
                             r["number"] if n == 0 else None, r["party"] if n == 0 else None, r["vat_number"] if n == 0 else None,
                             f"{b['rate']:g}%" if b["rate"] else (b.get("nature") or "esente"), _e(b["taxable_cents"]), _e(b["vat_cents"]),
                             _e(r["total_cents"]) if n == 0 else None, "split payment" if r["split_payment"] else ""])
        _sheet(wb, "Registro", ["Prot.", "Data reg.", "Data doc.", "Numero", "Controparte", "P.IVA", "Aliquota", "Imponibile", "IVA",
                                "Totale", "Note"], rows, (8, 9, 10))
        _sheet(wb, "Riepilogo aliquote", ["Aliquota", "Imponibile", "IVA"],
               [[s["label"], _e(s["taxable_cents"]), _e(s["vat_cents"])] for s in reg["summary"]]
               + [["Totale", _e(reg["totals"]["taxable_cents"]), _e(reg["totals"]["vat_cents"])]], (2, 3))
    info = wb.create_sheet("Info", 0)
    for row in (["Azienda", company["name"]], ["Partita IVA", company.get("vat_number", "")], ["Periodo", f"{date_from} → {date_to}"]):
        info.append(row)
    info.column_dimensions["A"].width = 14
    info.column_dimensions["B"].width = 50
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{base}.xlsx"


def statements_pdf(company: dict, data: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .report import _styles, eur
    S = _styles()
    y = data["year"]
    story = [Paragraph(f"Bilancio {y} · {company['name']}", S["h1"]),
             Paragraph(f"Situazione al {data['date_to'][8:10]}/{data['date_to'][5:7]}/{data['date_to'][:4]} · schema CEE semplificato · "
                       f"P.IVA {company.get('vat_number', '')}", S["sub"])]

    def table(title, rows, total_label=None, total=None, total_prev=None):
        body = [["", str(y), str(y - 1)]]
        bold = []
        for r in rows:
            body.append([("    " * r["level"]) + r["label"], eur(r["amount"]), eur(r["previous"])])
            if r["level"] == 0:
                bold.append(len(body) - 1)
        if total_label:
            body.append([total_label, eur(total), eur(total_prev) if total_prev is not None else ""])
            bold.append(len(body) - 1)
        t = Table(body, colWidths=[110 * mm, 32 * mm, 32 * mm], repeatRows=1)
        style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6170")), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                 ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#E3E5E8")),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        for i in bold:
            style.append(("FONT", (0, i), (-1, i), "Helvetica-Bold", 8.5))
        t.setStyle(TableStyle(style))
        return [Paragraph(title, S["h2"]), t]

    story += table("Stato patrimoniale · Attivo", data["attivo"], "Totale attivo", data["totale_attivo"])
    story += table("Stato patrimoniale · Passivo", data["passivo"], "Totale passivo e netto", data["totale_passivo"])
    s = data["sintesi"]
    story += table("Conto economico", data["conto_economico"], "Utile (perdita) dell'esercizio", s["utile"], s["utile_precedente"])
    story += [Spacer(1, 4 * mm), Paragraph(
        f"Differenza tra valore e costi della produzione: <b>{eur(s['differenza'])}</b> · Risultato prima delle imposte: "
        f"<b>{eur(s['risultato_ante_imposte'])}</b>", S["p"]),
        Spacer(1, 6 * mm),
        Paragraph("Prospetto gestionale generato da Tesoreria di gruppo dalle registrazioni in partita doppia. Non sostituisce il "
                  "bilancio d'esercizio redatto e depositato a norma di legge.", S["small"])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                      title=f"Bilancio {y} {company['name']}").build(story)
    return buf.getvalue()


# ------------------------------------------------------------------ prima nota per il gestionale del commercialista

EXPORT_FIELDS = {
    "data": "Data registrazione", "numero": "Numero registrazione", "causale": "Causale", "causale_descrizione": "Descrizione causale",
    "descrizione": "Descrizione", "numero_documento": "Numero documento", "data_documento": "Data documento",
    "conto": "Conto", "conto_descrizione": "Descrizione conto", "conto_esterno": "Conto nel gestionale",
    "dare": "Dare", "avere": "Avere", "importo": "Importo", "segno": "Segno (D/A)",
    "controparte": "Cliente/fornitore", "partita_iva": "Partita IVA", "centro_costo": "Centro di costo", "nota_riga": "Nota di riga",
}
DEFAULT_EXPORT = {
    "format": "csv", "separator": ";", "decimal": ",", "date_format": "gg/mm/aaaa", "header": True,
    "columns": ["data", "numero", "causale", "descrizione", "numero_documento", "conto_esterno", "conto_descrizione",
                "dare", "avere", "controparte", "partita_iva"],
    "account_map": {}, "causale_map": {},
}


def _fmt_date(iso: str | None, fmt: str) -> str:
    if not iso:
        return ""
    y, m, d = iso[:4], iso[5:7], iso[8:10]
    return {"gg/mm/aaaa": f"{d}/{m}/{y}", "aaaa-mm-gg": iso[:10], "ggmmaaaa": f"{d}{m}{y}", "aaaammgg": f"{y}{m}{d}"}.get(fmt, iso[:10])


async def export_journal(db, company: dict, date_from: str, date_to: str, cfg: dict) -> tuple[bytes, str, str]:
    import csv
    from .accounting import CAUSALI
    cfg = {**DEFAULT_EXPORT, **(cfg or {})}
    cols = [c for c in cfg["columns"] if c in EXPORT_FIELDS] or DEFAULT_EXPORT["columns"]
    centers = {c["id"]: c["name"] for c in await db.cost_centers.find({"company_id": company["id"]}, {"_id": 0}).to_list(500)}
    j = await rep.journal(db, company["id"], date_from, date_to, limit=10 ** 7)

    def money(c):
        if cfg["format"] == "xlsx":
            return _e(c)
        text = f"{(c or 0) / 100:.2f}"
        return text.replace(".", ",") if cfg["decimal"] == "," else text

    rows = []
    for e in j["items"]:
        for l in e["lines"]:
            amount = l["dare"] or l["avere"]
            party_vat = l.get("party_key") if l.get("party_key") and l["party_key"].isdigit() else ""
            values = {
                "data": _fmt_date(e["date"], cfg["date_format"]), "numero": e.get("number"),
                "causale": cfg["causale_map"].get(e["causale"], e["causale"]), "causale_descrizione": CAUSALI.get(e["causale"], ""),
                "descrizione": e.get("description") or "", "numero_documento": e.get("doc_number") or "",
                "data_documento": _fmt_date(e.get("doc_date"), cfg["date_format"]), "conto": l["account"],
                "conto_descrizione": l.get("account_name", ""), "conto_esterno": cfg["account_map"].get(l["account"], l["account"]),
                "dare": money(l["dare"]) if l["dare"] else ("" if cfg["format"] == "csv" else None),
                "avere": money(l["avere"]) if l["avere"] else ("" if cfg["format"] == "csv" else None),
                "importo": money(amount), "segno": "D" if l["dare"] else "A", "controparte": l.get("party_name") or "",
                "partita_iva": party_vat, "centro_costo": centers.get(l.get("cost_center_id"), ""), "nota_riga": l.get("description") or "",
            }
            rows.append([values[c] for c in cols])
    slug = re.sub(r"[^A-Za-z0-9]+", "_", company["name"]).strip("_").lower()
    name = f"prima_nota_{slug}_{date_from}_{date_to}"
    headers = [EXPORT_FIELDS[c] for c in cols]
    if cfg["format"] == "xlsx":
        wb = Workbook()
        wb.remove(wb.active)
        _sheet(wb, "Prima nota", headers, rows, money=[i + 1 for i, c in enumerate(cols) if c in {"dare", "avere", "importo"}])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{name}.xlsx"
    buf = io.StringIO()
    sep = {"tab": "\t"}.get(cfg["separator"], cfg["separator"] or ";")
    w = csv.writer(buf, delimiter=sep, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    if cfg["header"]:
        w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"{name}.csv"


async def export_parties(db, company: dict) -> tuple[bytes, str, str]:
    """Anagrafica clienti e fornitori presenti nelle fatture (per l'import nel gestionale)."""
    import csv
    seen = {}
    async for i in db.invoices.find({"company_id": company["id"]}, {"_id": 0, "counterparty_name": 1, "counterparty_vat": 1, "direction": 1}):
        key = (i.get("counterparty_vat") or i["counterparty_name"]).upper()
        r = seen.setdefault(key, {"name": i["counterparty_name"], "vat": i.get("counterparty_vat") or "", "kinds": set()})
        r["kinds"].add("Cliente" if i["direction"] == "attiva" else "Fornitore")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Ragione sociale", "Partita IVA", "Tipo"])
    for r in sorted(seen.values(), key=lambda r: r["name"].lower()):
        w.writerow([r["name"], r["vat"], " e ".join(sorted(r["kinds"]))])
    slug = re.sub(r"[^A-Za-z0-9]+", "_", company["name"]).strip("_").lower()
    return buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", f"anagrafica_clienti_fornitori_{slug}.csv"
