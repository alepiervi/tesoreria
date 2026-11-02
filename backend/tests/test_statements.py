import io
import json
from pathlib import Path

from openpyxl import Workbook

from app.services.statements import parse_amount_any, parse_date_any, parse_statement

ESEMPI = Path(__file__).resolve().parent.parent.parent / "esempi"


def sample(name):
    return (ESEMPI / name).read_bytes()


# ---------- Lettura dei formati ----------

def test_amounts_and_dates():
    assert parse_amount_any("1.234,56") == 123456
    assert parse_amount_any("-1.234,56") == -123456
    assert parse_amount_any("(12,00)") == -1200
    assert parse_amount_any("12,5-") == -1250
    assert parse_amount_any("1,234.56") == 123456
    assert parse_amount_any("1.500") == 150000
    assert parse_amount_any("abc") is None
    assert parse_date_any("05.03.26") == "2026-03-05"
    assert parse_date_any("31/02/2026") is None


def test_csv_with_preamble_and_dare_avere():
    r = parse_statement("lista.csv", sample("estratto_conto_esempio.csv"))
    assert r["format"] == "csv" and len(r["movements"]) == 7
    assert r["movements"][0]["amount_cents"] == 390400
    assert r["movements"][1]["amount_cents"] == -150000
    assert r["closing_balance_cents"] == 1272520 and r["closing_balance_date"] == "2026-10-27"
    assert r["warnings"]  # riga dei totali ignorata


def test_csv_signed_amount_comma_separated():
    data = "Data,Valuta,Importo,Descrizione\n01/10/2026,01/10/2026,-45.20,POS\n02/10/2026,02/10/2026,1500.00,Bonifico\n"
    r = parse_statement("x.csv", data.encode("cp1252"))
    assert [m["amount_cents"] for m in r["movements"]] == [-4520, 150000]


def test_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.append(["Movimenti conto"])
    ws.append([])
    ws.append(["Data operazione", "Descrizione", "Uscite", "Entrate"])
    ws.append(["03/10/2026", "Affitto", 1200, None])
    ws.append(["04/10/2026", "Incasso cliente", None, 980.5])
    buf = io.BytesIO()
    wb.save(buf)
    r = parse_statement("mov.xlsx", buf.getvalue())
    assert r["format"] == "xlsx"
    assert [m["amount_cents"] for m in r["movements"]] == [-120000, 98050]


def test_camt053():
    r = parse_statement("estratto.xml", sample("estratto_conto_esempio_camt053.xml"))
    assert r["format"] == "camt" and len(r["movements"]) == 3
    assert r["iban"] == "IT60X0542811101000000123456"
    assert r["closing_balance_cents"] == 1318860
    assert "RHO TRASPORTI" in r["movements"][0]["description"]


def test_cbi():
    r = parse_statement("rh.txt", sample("estratto_conto_esempio_cbi.txt"))
    assert r["format"] == "cbi" and len(r["movements"]) == 3
    assert r["movements"][1]["amount_cents"] == -442140
    assert "FT 2026/398" in r["movements"][1]["description"]
    assert r["closing_balance_cents"] == 1318860


# ---------- Conti manuali e import ----------

def _gamma_manual(client, owner):
    gamma = next(c for c in client.get("/api/companies", headers=owner).json() if c["name"] == "Azienda Gamma Srl")
    accounts = client.get(f"/api/companies/{gamma['id']}/bank-accounts", headers=owner).json()
    return gamma["id"], next(a for a in accounts if a["is_manual"])


def test_import_flow_without_duplicates(client, owner):
    cid, acc = _gamma_manual(client, owner)
    files = {"file": ("lista.csv", sample("estratto_conto_esempio.csv"), "text/csv")}
    p = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner, files=files).json()
    assert p["new_count"] == 7 and p["duplicate_count"] == 0 and len(p["sample"]) == 7
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=files).json()
    assert r["imported"] == 7 and r["balance_updated"] is True
    assert r["account"]["balance_cents"] == 1272520
    # reimportare lo stesso file non crea doppioni
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=files).json()
    assert r["imported"] == 0 and r["duplicates"] == 7
    # i movimenti importati entrano nella riconciliazione
    queue = client.get(f"/api/reconciliation?company_id={cid}", headers=owner).json()
    assert any("TAU LOGISTICA" in t["description"] for t in queue)
    assert len(client.get(f"/api/bank-accounts/{acc['id']}/imports", headers=owner).json()) == 2


def test_import_with_manual_mapping(client, owner):
    _, acc = _gamma_manual(client, owner)
    data = "Giorno;Testo;Valore\n01/10/2026;Spesa;-10,00\n".encode()
    files = {"file": ("strano.csv", data, "text/csv")}
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner, files=files).json()
    # colonne non riconoscibili da sole: si chiede all'utente, mostrando le intestazioni
    assert r["needs_mapping"] is True and r["headers"] == ["Giorno", "Testo", "Valore"]
    assert client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=files).status_code == 400
    mapping = json.dumps({"date": 0, "amount": 2, "description": [1]})
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner,
                    files={"file": ("strano.csv", data, "text/csv")}, data={"mapping": mapping})
    assert r.status_code == 200 and r.json()["sample"][0]["amount_cents"] == -1000
    # file senza intestazione
    raw = "01/10/2026;Spesa;-10,00;x\n02/10/2026;Incasso;20,00;y\n".encode()
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner,
                    files={"file": ("raw.csv", raw, "text/csv")}).json()
    assert r["needs_mapping"] and r["headers"][0] == "Colonna 1"
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner,
                    files={"file": ("raw.csv", raw, "text/csv")}, data={"mapping": mapping}).json()
    assert r["imported"] == 2


def test_create_manual_account_and_permissions(client, owner, accountant):
    alfa = next(c for c in client.get("/api/companies", headers=owner).json() if c["name"] == "Azienda Alfa Srl")["id"]
    r = client.post(f"/api/companies/{alfa}/bank-accounts/manual", headers=owner,
                    json={"bank_name": "Banca D", "iban": "IT60 X054 2811 1010 0000 0123 456", "balance": "1.000,00"})
    assert r.status_code == 200 and r.json()["is_manual"] and "iban" not in r.json()
    acc_id = r.json()["id"]
    assert client.post(f"/api/bank-accounts/{acc_id}/sync", headers=owner).status_code == 400
    files = {"file": ("x.xml", sample("estratto_conto_esempio_camt053.xml"), "application/xml")}
    assert client.post(f"/api/bank-accounts/{acc_id}/statement/import", headers=accountant, files=files).status_code == 403
    bad = client.post(f"/api/companies/{alfa}/bank-accounts/manual", headers=owner, json={"bank_name": "X", "iban": "123"})
    assert bad.status_code == 400


def test_iban_mismatch_warning(client, owner):
    alfa = next(c for c in client.get("/api/companies", headers=owner).json() if c["name"] == "Azienda Alfa Srl")["id"]
    acc = client.post(f"/api/companies/{alfa}/bank-accounts/manual", headers=owner,
                      json={"bank_name": "Banca D", "iban": "IT02L1234512345123456789012"}).json()
    p = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner,
                    files={"file": ("x.xml", sample("estratto_conto_esempio_camt053.xml"), "application/xml")}).json()
    assert any("diverso" in w for w in p["warnings"])


def test_manual_account_becomes_automatic(client, owner):
    _, acc = _gamma_manual(client, owner)
    files = {"file": ("x.xml", sample("estratto_conto_esempio_camt053.xml"), "application/xml")}
    client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=files)
    cid = acc["company_id"]
    before = client.get(f"/api/companies/{cid}/transactions?account_id={acc['id']}&limit=500", headers=owner).json()["total"]
    r = client.post(f"/api/companies/{cid}/bank-accounts/connect", headers=owner,
                    json={"bank_name": "Banca A", "manual_account_id": acc["id"]})
    converted = r.json()["accounts"][0]
    assert converted["id"] == acc["id"] and converted["is_manual"] is False
    after = client.get(f"/api/companies/{cid}/transactions?account_id={acc['id']}&limit=500", headers=owner).json()["total"]
    assert after >= before  # i movimenti importati restano
    # ora l'import manuale non è più permesso, la sincronizzazione sì
    assert client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=files).status_code == 400
    assert client.post(f"/api/bank-accounts/{acc['id']}/sync", headers=owner).status_code == 200
