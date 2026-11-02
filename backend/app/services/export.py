"""Export per il commercialista: Excel, CSV (prima nota) e archivio XML delle fatture."""
from .invoices import payable
import csv
import io
import zipfile

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

STATUS_LABELS = {"da_riconciliare": "Da riconciliare", "riconciliato": "Riconciliato", "escluso": "Senza fattura"}


def _eur(cents: int | None):
    return round((cents or 0) / 100, 2)


def _sheet(wb, title: str, headers: list[str], rows: list[list], money_cols: set[int] = frozenset()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="15171C")
    for r in rows:
        ws.append(r)
    for col in money_cols:
        for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            for cell in row:
                cell.number_format = '#,##0.00 "€"'
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if i - 1 < len(r)] + [8])
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)
    ws.freeze_panes = "A2"
    return ws


def build_xlsx(company: dict, period: str, transactions: list[dict], invoices: list[dict],
               deadlines: list[dict], accounts: dict[str, dict], notes_by_tx: dict[str, list]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)

    tx_rows = []
    for t in transactions:
        acc = accounts.get(t.get("account_id"), {})
        notes = " | ".join(f"{n['author_name']}: {n['text']}" for n in notes_by_tx.get(t["id"], []))
        tx_rows.append([
            t["date"], acc.get("bank_name", ""), acc.get("iban_masked", ""), t["description"], t.get("category", ""),
            _eur(t["amount_cents"]) if t["amount_cents"] > 0 else None,
            _eur(-t["amount_cents"]) if t["amount_cents"] < 0 else None,
            STATUS_LABELS.get(t.get("status"), t.get("status")),
            "; ".join(a["label"] for a in t.get("allocations", []) or []) or (t.get("exclusion_reason") or ""),
            notes,
        ])
    _sheet(wb, "Prima nota", ["Data", "Banca", "Conto", "Descrizione", "Categoria", "Entrata", "Uscita",
                              "Stato", "Abbinato a", "Note"], tx_rows, {6, 7})

    inv_rows = [[i["date"], "Attiva" if i["direction"] == "attiva" else "Passiva", i["number"],
                 i.get("counterparty_name", ""), i.get("counterparty_vat", ""), _eur(i["total_cents"]),
                 _eur(i.get("paid_cents", 0)), _eur(payable(i) - i.get("paid_cents", 0)),
                 i.get("due_date", ""), i.get("status", "")] for i in invoices]
    _sheet(wb, "Fatture", ["Data", "Tipo", "Numero", "Controparte", "P.IVA", "Totale", "Pagato", "Residuo",
                           "Scadenza", "Stato"], inv_rows, {6, 7, 8})

    dl_rows = [[d["due_date"], d["kind"], d["description"], _eur(d["amount_cents"]), d.get("status", "")]
               for d in deadlines]
    _sheet(wb, "Scadenze", ["Scadenza", "Tipo", "Descrizione", "Importo", "Stato"], dl_rows, {4})

    info = wb.create_sheet("Info", 0)
    info.append(["Azienda", company["name"]])
    info.append(["Partita IVA", company.get("vat_number", "")])
    info.append(["Periodo", period])
    info.append(["Movimenti", len(transactions)])
    info.append(["Fatture", len(invoices)])
    info.column_dimensions["A"].width = 16
    info.column_dimensions["B"].width = 40

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_csv(transactions: list[dict], accounts: dict[str, dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Data", "Banca", "Descrizione", "Categoria", "Importo", "Stato", "Abbinato a"])
    for t in transactions:
        acc = accounts.get(t.get("account_id"), {})
        w.writerow([t["date"], acc.get("bank_name", ""), t["description"], t.get("category", ""),
                    f"{t['amount_cents'] / 100:.2f}".replace(".", ","),
                    STATUS_LABELS.get(t.get("status"), t.get("status")),
                    "; ".join(a["label"] for a in t.get("allocations", []) or [])])
    # BOM per far aprire correttamente il file a Excel
    return ("﻿" + buf.getvalue()).encode("utf-8")


def build_xml_zip(xml_docs: list[tuple[str, str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, xml in xml_docs:
            z.writestr(name, xml)
    return buf.getvalue()
