"""Report mensile in PDF (per il titolare, i soci o da portare in banca)."""
import io
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..utils import parse_date, today
from .budget import budget_status
from .categories import NEUTRAL_CATEGORIES
from .forecast import weekly_forecast
from .loans import CREDIT_LINES, summary as loan_summary
from .receivables import aging

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
          "ottobre", "novembre", "dicembre"]
INK = colors.HexColor("#15171C")
MUTED = colors.HexColor("#5B6170")
LINE = colors.HexColor("#E3E5E8")
ACCENT = colors.HexColor("#2346D8")
WARN = colors.HexColor("#A8480F")


def eur(cents: int, signed: bool = False) -> str:
    v = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    sign = "- " if cents < 0 else ("+ " if signed and cents > 0 else "")
    return f"{sign}{v} €"


def _styles():
    ss = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, alignment=0,
                             textColor=INK, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=ss["Normal"], fontName="Helvetica", fontSize=9, textColor=MUTED, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=INK,
                             spaceBefore=12, spaceAfter=6),
        "p": ParagraphStyle("p", parent=ss["Normal"], fontName="Helvetica", fontSize=9, textColor=INK, leading=12),
        "small": ParagraphStyle("small", parent=ss["Normal"], fontName="Helvetica", fontSize=8, textColor=MUTED, leading=10),
        "r": ParagraphStyle("r", parent=ss["Normal"], fontName="Helvetica", fontSize=9, alignment=TA_RIGHT),
    }


def _table(rows: list[list], widths: list[float], money_cols: tuple = (), total: bool = False) -> Table:
    t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for c in money_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if total:
        style += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9), ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK)]
    t.setStyle(TableStyle(style))
    return t


async def build_monthly_pdf(db, company_ids: list[str], month: str, title: str | None = None) -> bytes:
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    prev_start = (start - timedelta(days=1)).replace(day=1)
    companies = {c["id"]: c for c in await db.companies.find({"id": {"$in": company_ids}}, {"_id": 0}).to_list(100)}
    names = {k: v["name"] for k, v in companies.items()}
    single = len(company_ids) == 1
    heading = names[company_ids[0]] if single else (title or "Gruppo")
    S = _styles()
    story = [Paragraph(f"Report mensile · {heading}", S["h1"]),
             Paragraph(f"{MONTHS[m - 1].capitalize()} {y} · creato il {today().strftime('%d/%m/%Y')}"
                       + ("" if single else " · " + ", ".join(sorted(names.values()))), S["sub"])]

    # 1. Liquidità attuale
    accounts = await db.bank_accounts.find({"company_id": {"$in": company_ids}, "status": {"$ne": "scollegato"}}, {"_id": 0}).to_list(200)
    rows = [["Azienda", "Conto", "Saldo", "Aggiornato al"]]
    for a in sorted(accounts, key=lambda a: (names.get(a["company_id"], ""), a["bank_name"])):
        rows.append([names.get(a["company_id"], ""), f"{a['bank_name']} {a['iban_masked']}", eur(a.get("balance_cents", 0)),
                     parse_date(a["balance_date"]).strftime("%d/%m/%Y") if a.get("balance_date") else ""])
    rows.append(["Totale", "", eur(sum(a.get("balance_cents", 0) for a in accounts)), ""])
    story += [Paragraph("Liquidità", S["h2"]), _table(rows, [50, 62, 32, 26], (2,), total=True)]
    loans = [loan_summary(l) for l in await db.loans.find({"company_id": {"$in": company_ids}, "active": {"$ne": False}}, {"_id": 0}).to_list(200)]
    credit = sum(l.get("available_cents", 0) for l in loans if l["kind"] in CREDIT_LINES)
    if credit:
        story.append(Paragraph(f"Fidi e anticipi ancora disponibili: <b>{eur(credit)}</b>", S["p"]))

    # 2. Entrate e uscite del mese per categoria
    async def flows(s: date, e: date) -> dict:
        out: dict[str, list[int]] = {}
        async for t in db.transactions.find({"company_id": {"$in": company_ids}, "date": {"$gte": s.isoformat(), "$lte": e.isoformat()},
                                             "category": {"$nin": list(NEUTRAL_CATEGORIES)}}, {"category": 1, "amount_cents": 1}):
            r = out.setdefault(t["category"], [0, 0])
            r[0 if t["amount_cents"] > 0 else 1] += abs(t["amount_cents"])
        return out
    cur, prev = await flows(start, end), await flows(prev_start, start - timedelta(days=1))
    rows = [["Categoria", "Entrate", "Uscite", "Netto", "Mese prima"]]
    tin = tout = 0
    for cat in sorted(cur, key=lambda c: -(cur[c][0] + cur[c][1])):
        i, o = cur[cat]
        tin, tout = tin + i, tout + o
        p = prev.get(cat, [0, 0])
        rows.append([cat, eur(i) if i else "", eur(o) if o else "", eur(i - o, True), eur(p[0] - p[1], True)])
    ptot = sum(v[0] - v[1] for v in prev.values())
    rows.append(["Totale", eur(tin), eur(tout), eur(tin - tout, True), eur(ptot, True)])
    story += [Paragraph("Entrate e uscite del mese", S["h2"]),
              Paragraph("Esclusi i trasferimenti tra conti e tra aziende del gruppo.", S["small"]),
              _table(rows, [56, 28, 28, 28, 30], (1, 2, 3, 4), total=True)]

    # 3. Budget (per singola azienda)
    if single:
        b = await budget_status(db, company_ids[0], y, m)
        if b["has_budget"]:
            rows = [["Categoria", "Budget", "Reale", "%"]]
            for r in b["rows"]:
                if r["budget_cents"]:
                    rows.append([r["category"] + (" (entrata)" if r["kind"] == "entrata" else ""), eur(r["budget_cents"]),
                                 eur(r["actual_cents"]), f"{r['pct']}%" if r["pct"] is not None else ""])
            story += [Paragraph("Budget del mese", S["h2"]), _table(rows, [70, 34, 34, 22], (1, 2, 3))]

    # 4. Crediti e debiti
    rec = await aging(db, company_ids, names, "attiva")
    pay = await aging(db, company_ids, names, "passiva")
    short = {"non_scaduto": "Non scaduto", "d0_30": "1-30 gg", "d31_60": "31-60 gg", "d61_90": "61-90 gg",
             "oltre_90": "Oltre 90 gg"}
    rows = [["", *[short[b["id"]] for b in rec["buckets"]], "Totale"]]
    rows.append(["Crediti verso clienti", *[eur(b["amount_cents"]) for b in rec["buckets"]], eur(rec["total_cents"])])
    rows.append(["Debiti verso fornitori", *[eur(b["amount_cents"]) for b in pay["buckets"]], eur(pay["total_cents"])])
    story += [Paragraph("Crediti e debiti per anzianità", S["h2"]),
              _table(rows, [36, 24, 26, 20, 20, 22, 24], (1, 2, 3, 4, 5, 6))]
    late = [p for p in rec["parties"] if p["open_cents"] and p["max_overdue_days"] > 0][:6]
    if late:
        rows = [["Cliente", "Azienda", "Scaduto da", "Da incassare", "Ritardo medio"]]
        for p in late:
            rows.append([p["name"][:34], p["company_name"][:24], f"{p['max_overdue_days']} gg", eur(p["open_cents"]),
                         f"{p['avg_delay_days']} gg" if p["avg_delay_days"] is not None else "—"])
        story += [Spacer(1, 4 * mm), Paragraph("Clienti con pagamenti in ritardo", S["p"]), _table(rows, [52, 40, 22, 30, 26], (2, 3, 4))]

    # 5. Previsione
    fc = await weekly_forecast(db, company_ids, 8)
    rows = [["Settimana", "Entrate", "Uscite", "Saldo a fine settimana"]]
    for w in fc["weeks"]:
        rows.append([f"{w['week']} · dal {parse_date(w['start']).strftime('%d/%m')}", eur(w["inflow_cents"]),
                     eur(w["outflow_cents"]), eur(w["balance_end_cents"])])
    tbl = _table(rows, [44, 36, 36, 50], (1, 2, 3))
    for i, w in enumerate(fc["weeks"], start=1):
        if w["balance_end_cents"] < 0:
            tbl.setStyle(TableStyle([("TEXTCOLOR", (3, i), (3, i), WARN)]))
    story += [Paragraph("Previsione di cassa (8 settimane)", S["h2"]), tbl]

    # 6. Finanziamenti
    amort = [l for l in loans if l["kind"] not in CREDIT_LINES]
    if amort or credit:
        rows = [["Finanziamento", "Azienda", "Rata", "Rate rimaste", "Debito residuo"]]
        for l in amort:
            rows.append([f"{l['kind_label']} {l['lender']}"[:40], names.get(l["company_id"], "")[:24], eur(l["installment_cents"]),
                         str(l["remaining_installments"]), eur(l["residual_cents"])])
        for l in loans:
            if l["kind"] in CREDIT_LINES:
                rows.append([f"{l['kind_label']} {l['lender']}"[:40], names.get(l["company_id"], "")[:24], "",
                             "", f"usati {eur(l.get('used_cents', 0))} su {eur(l.get('limit_cents', 0))}"])
        story += [Paragraph("Finanziamenti e fidi", S["h2"]), _table(rows, [50, 36, 26, 22, 36], (2, 3, 4))]

    # 7. Da sistemare
    to_rec = await db.transactions.count_documents({"company_id": {"$in": company_ids}, "status": "da_riconciliare"})
    questions = await db.notes.count_documents({"company_id": {"$in": company_ids}, "is_question": True, "resolved": False})
    story += [Paragraph("Da sistemare", S["h2"]),
              Paragraph(f"Movimenti da riconciliare: <b>{to_rec}</b> · Chiarimenti aperti: <b>{questions}</b>", S["p"]),
              Spacer(1, 8 * mm),
              Paragraph("Report generato da Tesoreria di gruppo. Le stime (IVA, previsione) si basano sui dati registrati "
                        "nel programma e vanno verificate con il commercialista.", S["small"])]

    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"Report {heading} · {MONTHS[m - 1]} {y}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f"Report mensile {heading} {month}", author="Tesoreria di gruppo")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
