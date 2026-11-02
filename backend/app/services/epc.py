"""QR code per bonifico SEPA (standard EPC, "Girocode"): il cliente lo inquadra con l'app della banca e trova
il bonifico già compilato. Non serve nessun contratto con un fornitore di pagamenti."""
import io

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def payload(name: str, iban: str, amount_cents: int, text: str) -> str:
    """Contenuto del QR secondo le linee guida EPC069-12 (versione 002, UTF-8)."""
    iban = iban.replace(" ", "").upper()
    return "\n".join(["BCD", "002", "1", "SCT", "", name[:70], iban, f"EUR{amount_cents / 100:.2f}", "", "", text[:140]])


def payment_notice_pdf(company: dict, customer: str, iban: str, amount_cents: int, text: str, due: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    amount = f"{amount_cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 25 * mm, f"Avviso di pagamento · {company['name']}")
    c.setFont("Helvetica", 11)
    y = h - 40 * mm
    for label, value in (("Cliente", customer), ("Importo", amount), ("Scadenza", due), ("Beneficiario", company["name"]),
                         ("IBAN", iban), ("Causale", text)):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y, label)
        c.setFont("Helvetica", 11)
        c.drawString(55 * mm, y, value)
        y -= 8 * mm
    qr = QrCodeWidget(payload(company["name"], iban, amount_cents, text), barLevel="M")
    x1, y1, x2, y2 = qr.getBounds()
    size = 55 * mm
    d = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    d.add(qr)
    renderPDF.draw(d, c, 20 * mm, y - size - 5 * mm)
    c.setFont("Helvetica", 10)
    c.drawString(80 * mm, y - 25 * mm, "Inquadra il QR code con l'app della tua banca:")
    c.drawString(80 * mm, y - 31 * mm, "il bonifico si compila da solo (standard SEPA EPC).")
    c.showPage()
    c.save()
    return buf.getvalue()
