"""Estratti conto in PDF e carte di credito."""
import io
from pathlib import Path

from reportlab.pdfgen import canvas

from app import db as db_module
from app.services.categories import categorize, categorize_card
from app.services.statement_pdf import parse_pdf

ESEMPI = Path(__file__).resolve().parents[2] / "esempi"


def gamma(client, h):
    return next(c["id"] for c in client.get("/api/companies", headers=h).json() if c["name"] == "Azienda Gamma Srl")


def manual_account(client, h, cid):
    return next(a for a in client.get(f"/api/companies/{cid}/bank-accounts", headers=h).json() if a["is_manual"])


def find(client, coll, q):
    async def go():
        return await db_module.get_db()[coll].find(q, {"_id": 0}).to_list(1000)
    return client.portal.call(go)


def test_parse_bank_pdf_with_columns():
    r = parse_pdf((ESEMPI / "estratto_conto_esempio.pdf").read_bytes())
    amounts = [m["amount_cents"] for m in r["movements"]]
    assert amounts == [530000, -150000, -125000, -42100, -1120000]
    assert r["closing_balance_cents"] == 325900 and r["closing_balance_date"] == "2026-10-31"
    assert r["movements"][0]["description"].endswith("SALDO FT 41/2026")  # riga di continuazione
    assert not r["warnings"] and r["iban"].startswith("IT30")


def test_parse_card_pdf_signs():
    r = parse_pdf((ESEMPI / "estratto_carta_esempio.pdf").read_bytes(), card=True)
    by = {m["description"]: m["amount_cents"] for m in r["movements"]}
    assert by["AUTOSTRADE PER L'ITALIA ROMA"] == -4230
    assert by["RIMBORSO AMAZON MARKETPLACE"] == 2990 and by["PAGAMENTO SALDO PRECEDENTE - GRAZIE"] == 125000
    assert r["closing_balance_cents"] == -44990
    spese = sum(v for k, v in by.items() if not k.startswith("PAGAMENTO"))
    assert spese == r["closing_balance_cents"]


def test_card_categories():
    assert categorize("ADDEBITO SALDO CARTA DI CREDITO E/C SETTEMBRE", -125000) == "Giroconti"
    assert categorize_card("PAGAMENTO SALDO PRECEDENTE - GRAZIE", 125000) == "Giroconti"
    assert categorize_card("Q8 STAZIONE DI SERVIZIO CARBURANTE", -8500) != "Giroconti"
    assert categorize("COMMISSIONI NEXI POS", -1200) == "Oneri bancari"


def test_import_pdf_into_manual_account(client, owner):
    cid = gamma(client, owner)
    acc = manual_account(client, owner, cid)
    pdf = (ESEMPI / "estratto_conto_esempio.pdf").read_bytes()
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner, files={"file": ("ec.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["format"] == "pdf" and p["new_count"] == 5 and p["closing_balance_cents"] == 325900
    assert any("diverso" in w for w in p["warnings"])  # IBAN del file diverso da quello del conto
    inv = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner,
                      files={"file": ("ec.pdf", pdf, "application/pdf")}, data={"invert": "true"}).json()
    assert inv["sample"][0]["amount_cents"] == -530000
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files={"file": ("ec.pdf", pdf, "application/pdf")})
    assert r.status_code == 200 and r.json()["imported"] == 5
    txs = find(client, "transactions", {"account_id": acc["id"], "description": {"$regex": "CARTA DI CREDITO"}})
    assert txs and txs[0]["category"] == "Giroconti"
    again = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files={"file": ("ec.pdf", pdf, "application/pdf")})
    assert again.json()["imported"] == 0 and again.json()["duplicates"] == 5


def test_card_account_and_import(client, owner):
    cid = gamma(client, owner)
    bank = manual_account(client, owner, cid)
    r = client.post(f"/api/companies/{cid}/bank-accounts/manual", headers=owner, json={
        "bank_name": "Nexi", "label": "Carta Business", "account_type": "carta", "card_last4": "4821",
        "linked_account_id": bank["id"], "card_debit_day": 15, "balance": "1.250"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["account_type"] == "carta" and card["balance_cents"] == -125000 and card["iban_masked"] == "•••• 4821"
    assert client.post(f"/api/companies/{cid}/bank-accounts/manual", headers=owner, json={
        "bank_name": "X", "account_type": "carta", "card_last4": "12"}).status_code == 400
    pdf = (ESEMPI / "estratto_carta_esempio.pdf").read_bytes()
    p = client.post(f"/api/bank-accounts/{card['id']}/statement/preview", headers=owner, files={"file": ("c.pdf", pdf, "application/pdf")}).json()
    assert p["is_card"] and p["closing_balance_cents"] == -44990
    r = client.post(f"/api/bank-accounts/{card['id']}/statement/import", headers=owner, files={"file": ("c.pdf", pdf, "application/pdf")})
    assert r.status_code == 200 and r.json()["imported"] == 7
    assert r.json()["account"]["balance_cents"] == -44990
    txs = {t["description"]: t for t in find(client, "transactions", {"account_id": card["id"]})}
    assert txs["PAGAMENTO SALDO PRECEDENTE - GRAZIE"]["category"] == "Giroconti"
    assert txs["AUTOSTRADE PER L'ITALIA ROMA"]["category"] == "Carburante e trasporti"
    # il saldo scritto a mano per una carta è sempre un debito
    r = client.post(f"/api/bank-accounts/{card['id']}/statement/import", headers=owner, files={"file": ("c.pdf", pdf, "application/pdf")},
                    data={"closing_balance": "500", "closing_balance_date": "2026-11-15"})
    assert r.json()["account"]["balance_cents"] == -50000


def test_scanned_pdf_without_ai(client, owner):
    cid = gamma(client, owner)
    acc = manual_account(client, owner, cid)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(100, 100, 200, 200, fill=1)  # solo grafica, nessun testo: come una scansione
    c.showPage()
    c.save()
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner,
                    files={"file": ("scan.pdf", buf.getvalue(), "application/pdf")})
    assert r.status_code == 400 and "CSV" in r.json()["detail"]
