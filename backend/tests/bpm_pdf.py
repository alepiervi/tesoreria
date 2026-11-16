"""Estratto conto di prova con le colonne Data | Valuta | Dare | Avere | Descrizione (descrizione a destra, su più righe)."""
import io

from reportlab.pdfgen import canvas

ROWS = [
    ("02/01/2026", "02/01/2026", "", "5.300,00", ["BONIFICO A VOSTRO FAVORE DA ROSSI SRL", "CAUSALE: SALDO FATTURA 12/2025 RIF. 4471"]),
    ("05/01/2026", "05/01/2026", "1.500,00", "", ["PAGAMENTO UTENZE ENEL ENERGIA", "ADDEBITO SDD CORE 33001"]),
    ("10/01/2026", "09/01/2026", "12,50", "", ["COMMISSIONI E SPESE"]),
    ("15/01/2026", "15/01/2026", "2.250,75", "", ["BONIFICO SEPA A FAVORE DI BIANCHI SPA", "FT 88 DEL 30/12/2025 IMPORTO 2.250,75"]),
    ("20/01/2026", "20/01/2026", "", "980,00", ["VERSAMENTO CONTANTI"]),
]


def bpm_pdf(page_break: bool = True) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 8)

    def header(y):
        c.drawString(40, y, "Banco BPM - Estratto conto IT60X0503411101000000123456")
        y -= 30
        for x, t in ((40, "DATA CONTABILE"), (120, "DATA VALUTA"), (220, "DARE"), (290, "AVERE"), (350, "DESCRIZIONE OPERAZIONE")):
            c.drawString(x, y, t)
        return y - 18

    y = header(800)
    c.drawString(40, y, "SALDO INIZIALE")
    c.drawRightString(320, y, "10.000,00")
    y -= 18
    for n, (d, v, dare, avere, desc) in enumerate(ROWS):
        if page_break and n == 3:
            c.drawString(40, 60, "Banco BPM S.p.A. Sede legale Milano - Pagina 1 di 2")
            c.showPage()
            c.setFont("Helvetica", 8)
            y = header(800)
        c.drawString(40, y, d)
        c.drawString(120, y, v)
        if dare:
            c.drawRightString(250, y, dare)
        if avere:
            c.drawRightString(320, y, avere)
        for i, line in enumerate(desc):
            c.drawString(350, y - i * 10, line)
        y -= 10 * len(desc) + 8
    y -= 10
    c.drawString(40, y, "SALDO FINALE AL 31/01/2026")
    c.drawRightString(320, y, "12.516,75")
    c.drawString(40, 60, "Banco BPM S.p.A. Sede legale Milano - Pagina 2 di 2")
    c.showPage()
    c.save()
    return buf.getvalue()
