"""Crea due estratti conto PDF di prova (conto corrente con colonne Dare/Avere e carta di credito) in esempi/."""
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def bank_pdf(path, rows, closing):
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, h - 20 * mm, "Banca Esempio Spa - Estratto conto")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 27 * mm, "Intestatario: Azienda Gamma Srl   IBAN IT30X7648350305641395376724")
    y = h - 40 * mm
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((20, "Data"), (40, "Valuta"), (60, "Descrizione operazione"), (150, "Dare"), (175, "Avere")):
        c.drawString(x * mm, y, t)
    c.setFont("Helvetica", 9)
    y -= 6 * mm
    c.drawString(60 * mm, y, "SALDO INIZIALE")
    c.drawRightString(195 * mm, y, "12.330,00")
    y -= 6 * mm
    for d, v, desc, extra, amount in rows:
        c.drawString(20 * mm, y, d)
        c.drawString(40 * mm, y, v)
        c.drawString(60 * mm, y, desc)
        if amount < 0:
            c.drawRightString(165 * mm, y, f"{-amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        else:
            c.drawRightString(195 * mm, y, f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        y -= 5 * mm
        if extra:
            c.drawString(60 * mm, y, extra)
            y -= 5 * mm
    y -= 3 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(60 * mm, y, "SALDO FINALE AL 31/10/2026")
    c.drawRightString(195 * mm, y, closing)
    c.showPage()
    c.save()


def card_pdf(path):
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(20 * mm, h - 20 * mm, "Carta Business - Estratto conto di ottobre 2026")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 27 * mm, "Carta n. **** **** **** 4821   Titolare: Azienda Gamma Srl")
    y = h - 40 * mm
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((20, "Data"), (45, "Descrizione"), (175, "Importo EUR")):
        c.drawString(x * mm, y, t)
    c.setFont("Helvetica", 9)
    y -= 6 * mm
    rows = [("02/10/26", "PAGAMENTO SALDO PRECEDENTE - GRAZIE", "-1.250,00"), ("03/10/26", "AUTOSTRADE PER L'ITALIA ROMA", "42,30"),
            ("07/10/26", "Q8 STAZIONE DI SERVIZIO MILANO", "85,00"), ("12/10/26", "AMAZON MARKETPLACE EU", "129,90"),
            ("15/10/26", "RIMBORSO AMAZON MARKETPLACE", "-29,90"), ("21/10/26", "HOTEL CENTRALE BOLOGNA", "210,00"),
            ("28/10/26", "MICROSOFT 365 BUSINESS", "12,60")]
    for d, desc, amount in rows:
        c.drawString(20 * mm, y, d)
        c.drawString(45 * mm, y, desc)
        c.drawRightString(195 * mm, y, amount)
        y -= 5 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(45 * mm, y, "SALDO DA ADDEBITARE IL 15/11/2026 SU C/C")
    c.drawRightString(195 * mm, y, "449,90")
    c.showPage()
    c.save()


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "esempi")
    bank_pdf(out / "estratto_conto_esempio.pdf", [
        ("02/10/2026", "02/10/2026", "BONIFICO A VOSTRO FAVORE DA RHO TRASPORTI SRL", "SALDO FT 41/2026", 5300.00),
        ("05/10/2026", "05/10/2026", "ADDEBITO SDD AFFITTO MAGAZZINO", "", -1500.00),
        ("15/10/2026", "15/10/2026", "ADDEBITO SALDO CARTA DI CREDITO", "E/C SETTEMBRE", -1250.00),
        ("16/10/2026", "16/10/2026", "PAGAMENTO F24 DELEGA 0001", "", -421.00),
        ("27/10/2026", "27/10/2026", "BONIFICO STIPENDI OTTOBRE", "", -11200.00),
    ], "3.259,00")
    card_pdf(out / "estratto_carta_esempio.pdf")
    print("ok", out)
