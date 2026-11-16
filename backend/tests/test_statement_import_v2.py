"""Estratti con descrizione a destra (es. BPM), Excel HTML, saldo per somma, possibili doppioni e annullamento."""
import json

from tests.bpm_pdf import bpm_pdf

from app.services.statement_pdf import parse_pdf
from app.services.statements import parse_statement


def new_account(client, h, balance="0"):
    cid = next(c for c in client.get("/api/companies", headers=h).json() if c["name"] == "Azienda Gamma Srl")["id"]
    r = client.post(f"/api/companies/{cid}/bank-accounts/manual", headers=h,
                    json={"bank_name": "Banco BPM", "label": "Test v2", "balance": balance, "balance_date": "2025-12-31"})
    assert r.status_code == 200, r.text
    return r.json()


def test_pdf_description_right_of_amounts():
    r = parse_pdf(bpm_pdf())
    assert [m["amount_cents"] for m in r["movements"]] == [530000, -150000, -1250, -225075, 98000]
    assert r["movements"][0]["description"] == "BONIFICO A VOSTRO FAVORE DA ROSSI SRL CAUSALE: SALDO FATTURA 12/2025 RIF. 4471"
    assert r["movements"][3]["description"].endswith("IMPORTO 2.250,75")  # importo nella descrizione: resta testo
    assert r["movements"][2]["value_date"] == "2026-01-09"
    assert r["opening_balance_cents"] == 1000000 and r["closing_balance_cents"] == 1251675 and r["balance_check"] == "ok"
    assert not any("Pagina" in m["description"] for m in r["movements"])


HTML_XLS = """<html><body><table>
<tr><td>Banco BPM - Lista movimenti</td></tr>
<tr><th>Data contabile</th><th>Data valuta</th><th>Descrizione</th><th>Importo</th></tr>
<tr><td>03/02/2026</td><td>03/02/2026</td><td>BONIFICO DA VERDI SNC<br>FT 3/2026</td><td>1.200,00</td></tr>
<tr><td>05/02/2026</td><td>05/02/2026</td><td>ADDEBITO F24</td><td>-300,50</td></tr>
</table></body></html>"""


def test_html_excel_and_excel_serial_dates():
    r = parse_statement("movimenti.xls", HTML_XLS.encode())
    assert r["format"] == "html" and [m["amount_cents"] for m in r["movements"]] == [120000, -30050]
    assert r["movements"][0]["description"] == "BONIFICO DA VERDI SNC FT 3/2026"
    from app.services.statements import parse_date_any
    assert parse_date_any(46055) == "2026-02-02"


def test_balance_by_sum_similar_duplicates_and_undo(client, owner):
    acc = new_account(client, owner)
    pdf = {"file": ("trimestrale.pdf", bpm_pdf(), "application/pdf")}
    p = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner, files=pdf).json()
    assert p["balance_check"] == "ok" and p["balance_plan"]["base_cents"] == 1000000 and len(p["rows"]) == 5
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=pdf).json()
    assert r["imported"] == 5 and r["account"]["balance_cents"] == 1251675

    # Excel successivo che si sovrappone di un movimento (stesso importo, data vicina, descrizione diversa)
    html = HTML_XLS.replace("03/02/2026</td><td>03/02/2026</td><td>BONIFICO DA VERDI SNC<br>FT 3/2026</td><td>1.200,00",
                            "21/01/2026</td><td>20/01/2026</td><td>VERS. CONTANTI</td><td>980,00")
    xls = {"file": ("movimenti.xls", html.encode(), "application/vnd.ms-excel")}
    p = client.post(f"/api/bank-accounts/{acc['id']}/statement/preview", headers=owner, files=xls).json()
    assert p["similar_count"] == 1 and p["new_count"] == 1 and p["rows"][0]["similar"]["description"] == "VERSAMENTO CONTANTI"
    assert p["balance_plan"] == {"mode": "sum", "base_cents": 1251675, "after_date": None, "base_label": "saldo attuale del conto"}
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=xls).json()
    assert r["imported"] == 1 and r["account"]["balance_cents"] == 1251675 - 30050 and r["account"]["balance_date"] == "2026-02-05"

    # se l'utente conferma il doppione, viene importato
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner, files=xls, data={"include": json.dumps([0])}).json()
    assert r["imported"] == 1 and r["account"]["balance_cents"] == 1251675 - 30050 + 98000

    imports = client.get(f"/api/bank-accounts/{acc['id']}/imports", headers=owner).json()
    assert len(imports) == 3
    last = imports[0]
    r = client.delete(f"/api/statement-imports/{last['id']}", headers=owner)
    assert r.status_code == 200 and r.json()["removed"] == 1 and r.json()["account"]["balance_cents"] == 1251675 - 30050
    assert client.delete(f"/api/statement-imports/{last['id']}", headers=owner).status_code == 404
    # annullando il trimestrale (non l'ultimo) si tolgono i suoi movimenti dal saldo
    first = imports[2]
    r = client.delete(f"/api/statement-imports/{first['id']}", headers=owner).json()
    assert r["removed"] == 5 and r["account"]["balance_cents"] == 1251675 - 30050 - 251675
    txs = client.get(f"/api/companies/{acc['company_id']}/transactions", headers=owner, params={"account_id": acc["id"]}).json()
    items = txs["items"] if isinstance(txs, dict) else txs
    assert all(t["account_id"] != acc["id"] or t["description"] == "ADDEBITO F24" for t in items)


def test_first_import_without_opening_counts_only_after_typed_balance(client, owner):
    acc = new_account(client, owner, balance="5.000")  # saldo scritto a mano al 31/12/2025
    html = HTML_XLS.replace("03/02/2026</td><td>03/02/2026", "30/12/2025</td><td>30/12/2025")
    r = client.post(f"/api/bank-accounts/{acc['id']}/statement/import", headers=owner,
                    files={"file": ("m.xls", html.encode(), "application/vnd.ms-excel")}).json()
    assert r["imported"] == 2 and r["account"]["balance_cents"] == 500000 - 30050
