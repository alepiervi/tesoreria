from datetime import date, timedelta

from app.integrations.sdi import build_fatturapa_xml
from app.services.fatturapa import parse_fatturapa
from tests.conftest import login


def companies(client, headers):
    return {c["name"]: c for c in client.get("/api/companies", headers=headers).json()}


# ---------- Accesso e ruoli ----------

def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"email": "titolare@demo.it", "password": "sbagliata"})
    assert r.status_code == 401


def test_lockout_after_failed_attempts(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": "x"})
    r = client.post("/api/auth/login", json={"email": "amministrazione@demo.it", "password": "Demo2026demo"})
    assert r.status_code == 429


def test_accountant_sees_only_assigned_companies(client, owner, accountant):
    assert len(companies(client, owner)) == 3
    mine = companies(client, accountant)
    assert set(mine) == {"Azienda Alfa Srl", "Azienda Beta Srl"}
    assert mine["Azienda Alfa Srl"]["role"] == "commercialista"


def test_accountant_cannot_access_other_company(client, owner, accountant):
    gamma = companies(client, owner)["Azienda Gamma Srl"]["id"]
    assert client.get(f"/api/companies/{gamma}/transactions", headers=accountant).status_code == 404


def test_group_dashboard_scoped_by_role(client, owner, accountant):
    o = client.get("/api/dashboard/group", headers=owner).json()
    a = client.get("/api/dashboard/group", headers=accountant).json()
    assert len(o["companies"]) == 3 and len(a["companies"]) == 2
    assert o["totals"]["balance_cents"] > a["totals"]["balance_cents"]
    assert len(o["monthly"]) == 6
    assert len(o["forecast"]["weeks"]) == 8


def test_accountant_cannot_pay_or_reconcile(client, accountant):
    queue = client.get("/api/reconciliation", headers=accountant).json()
    tx = queue[0]
    assert tx["can_reconcile"] is False
    r = client.post(f"/api/transactions/{tx['id']}/exclude", json={"reason": "x"}, headers=accountant)
    assert r.status_code == 403
    deadlines = client.get("/api/deadlines", headers=accountant).json()
    payable = next(d for d in deadlines if d["kind"] != "incasso")
    r = client.post(f"/api/deadlines/{payable['id']}/authorize", json={"account_id": "x"}, headers=accountant)
    assert r.status_code == 403


def test_2fa_flow(client, owner):
    import pyotp
    setup = client.post("/api/auth/2fa/setup", headers=owner).json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert client.post("/api/auth/2fa/enable", json={"code": code}, headers=owner).status_code == 200
    r = client.post("/api/auth/login", json={"email": "titolare@demo.it", "password": "Demo2026demo"})
    assert r.status_code == 401 and r.json()["detail"] == "2fa_required"
    r = client.post("/api/auth/login", json={"email": "titolare@demo.it", "password": "Demo2026demo",
                                             "totp_code": pyotp.TOTP(setup["secret"]).now()})
    assert r.status_code == 200


# ---------- Inviti e revoche ----------

def test_invite_accept_and_revoke(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]["id"]
    inv = client.post("/api/invites", headers=owner, json={
        "email": "nuovo@studio.it", "name": "Nuovo", "role": "lettura", "company_ids": [alfa]}).json()
    token = inv["invite_url"].rsplit("/", 1)[-1]
    info = client.get(f"/api/invites/token/{token}").json()
    assert info["companies"] == ["Azienda Alfa Srl"] and info["existing_user"] is False
    assert client.post(f"/api/invites/token/{token}/accept", json={"password": "corta"}).status_code == 400
    r = client.post(f"/api/invites/token/{token}/accept", json={"name": "Nuovo", "password": "PasswordSicura1"})
    assert r.status_code == 200
    new_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert list(companies(client, new_headers)) == ["Azienda Alfa Srl"]
    # sola lettura: non può caricare documenti
    r = client.post(f"/api/companies/{alfa}/documents", headers=new_headers,
                    files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}, data={"category": "Altro"})
    assert r.status_code == 403
    # revoca
    members = client.get("/api/members", headers=owner).json()
    user_id = next(m["id"] for m in members if m["email"] == "nuovo@studio.it")
    assert client.delete(f"/api/members/{user_id}/companies/{alfa}", headers=owner).status_code == 200
    assert companies(client, new_headers) == {}
    # il link non si può riusare
    assert client.get(f"/api/invites/token/{token}").status_code == 404


def test_cannot_remove_last_owner(client, owner):
    alfa = companies(client, owner)["Azienda Alfa Srl"]["id"]
    me = client.get("/api/auth/me", headers=owner).json()["user"]["id"]
    assert client.delete(f"/api/members/{me}/companies/{alfa}", headers=owner).status_code == 400


def test_only_owner_manages_members(client, admin):
    assert client.get("/api/members", headers=admin).status_code == 403


# ---------- Riconciliazione ----------

def test_suggestions_and_match(client, admin):
    queue = client.get("/api/reconciliation", headers=admin).json()
    delta = next(t for t in queue if "FT 125" in t["description"])
    best = delta["suggestions"][0]
    assert best["confidence"] == "alta"
    assert "125/2026" in best["targets"][0]["label"]
    r = client.post(f"/api/transactions/{delta['id']}/match", headers=admin,
                    json={"targets": [{"type": t["type"], "id": t["id"]} for t in best["targets"]]})
    assert r.status_code == 200
    alfa = delta["company_id"]
    inv = next(i for i in client.get(f"/api/companies/{alfa}/invoices", headers=admin).json() if i["number"] == "125/2026")
    assert inv["status"] == "pagata"
    deadlines = client.get(f"/api/deadlines?company_id={alfa}&scope=all", headers=admin).json()
    assert next(d for d in deadlines if d.get("invoice_id") == inv["id"])["status"] == "incassato"
    # annullamento
    assert client.post(f"/api/transactions/{delta['id']}/unmatch", headers=admin).status_code == 200
    inv = next(i for i in client.get(f"/api/companies/{alfa}/invoices", headers=admin).json() if i["number"] == "125/2026")
    assert inv["status"] == "aperta" and inv["paid_cents"] == 0


def test_two_invoice_suggestion(client, admin):
    queue = client.get("/api/reconciliation", headers=admin).json()
    tx = next(t for t in queue if "FT 77 E 79" in t["description"])
    assert len(tx["suggestions"][0]["targets"]) == 2


def test_auto_reconcile_only_confident(client, owner):
    before = len(client.get("/api/reconciliation", headers=owner).json())
    done = client.post("/api/reconciliation/auto", headers=owner).json()["reconciled"]
    after = client.get("/api/reconciliation", headers=owner).json()
    assert done >= 2
    assert len(after) == before - done
    # il pagamento con carta senza fattura resta da sistemare a mano
    assert any("CARTA" in t["description"] for t in after)


def test_exclude_without_invoice(client, admin):
    queue = client.get("/api/reconciliation", headers=admin).json()
    tx = next(t for t in queue if "CARTA" in t["description"])
    r = client.post(f"/api/transactions/{tx['id']}/exclude", headers=admin,
                    json={"reason": "Scontrino ferramenta", "category": "Altre uscite"})
    assert r.status_code == 200
    assert all(t["id"] != tx["id"] for t in client.get("/api/reconciliation", headers=admin).json())


# ---------- Note e chiarimenti ----------

def test_accountant_question_flow(client, owner, accountant):
    tx = client.get("/api/reconciliation", headers=accountant).json()[0]
    r = client.post("/api/notes", headers=accountant, json={
        "target_type": "transaction", "target_id": tx["id"], "text": "A cosa si riferisce?", "is_question": True})
    assert r.status_code == 200
    questions = client.get("/api/questions", headers=owner).json()
    assert questions[0]["text"] == "A cosa si riferisce?"
    client.post("/api/notes", headers=owner, json={"target_type": "transaction", "target_id": tx["id"],
                                                    "text": "Acconto fornitore"})
    assert client.post(f"/api/notes/{questions[0]['id']}/resolve", headers=owner).status_code == 200
    assert client.get("/api/questions", headers=owner).json() == []


# ---------- Fatture ----------

def test_fatturapa_parser():
    xml = build_fatturapa_xml(number="12/2026", issue_date="2026-10-01", total_cents=122000, due_date="2026-10-31",
                              seller_name="Fornitore Srl", seller_vat="12345678901", buyer_name="Cliente Srl",
                              buyer_vat="98765432109", iban="IT60X0542811101000000123456")
    doc = parse_fatturapa(xml.encode())[0]
    assert doc["number"] == "12/2026" and doc["total_cents"] == 122000
    assert doc["installments"][0]["due_date"] == "2026-10-31"
    assert doc["seller"]["vat"] == "12345678901" and doc["iban"].startswith("IT60")


def test_import_xml_invoice(client, admin):
    cs = companies(client, admin)
    alfa = cs["Azienda Alfa Srl"]
    xml = build_fatturapa_xml(number="999", issue_date=date.today().isoformat(), total_cents=50000,
                              due_date=(date.today() + timedelta(days=30)).isoformat(), seller_name="Nuovo Fornitore",
                              seller_vat="10101010101", buyer_name="Azienda Alfa Srl", buyer_vat="11111111111")
    r = client.post(f"/api/companies/{alfa['id']}/invoices/import", headers=admin,
                    files=[("files", ("f.xml", xml.encode(), "application/xml")),
                           ("files", ("rotto.xml", b"non sono xml", "application/xml"))])
    body = r.json()
    assert body["imported"] == 1
    assert body["results"][0]["direction"] == "passiva"
    assert body["results"][1]["ok"] is False
    # reimportare la stessa fattura non la duplica
    r = client.post(f"/api/companies/{alfa['id']}/invoices/import", headers=admin,
                    files=[("files", ("f.xml", xml.encode(), "application/xml"))])
    assert r.json()["imported"] == 0
    # fattura di un'altra azienda: rifiutata
    r = client.post(f"/api/companies/{cs['Azienda Beta Srl']['id']}/invoices/import", headers=admin,
                    files=[("files", ("f.xml", xml.encode(), "application/xml"))])
    assert r.json()["results"][0]["ok"] is False


# ---------- Scadenze e pagamenti ----------

def test_payment_request_and_authorization(client, owner, admin):
    deadlines = client.get("/api/deadlines", headers=admin).json()
    d = next(x for x in deadlines if "352" in x["description"])
    accounts = client.get(f"/api/companies/{d['company_id']}/bank-accounts", headers=admin).json()
    r = client.post(f"/api/deadlines/{d['id']}/request-payment", headers=admin, json={"account_id": accounts[0]["id"]})
    assert r.status_code == 200
    assert client.post(f"/api/deadlines/{d['id']}/authorize", headers=admin,
                       json={"account_id": accounts[0]["id"]}).status_code == 403
    r = client.post(f"/api/deadlines/{d['id']}/authorize", headers=owner, json={"account_id": accounts[0]["id"]})
    assert r.status_code == 200 and r.json()["payment_ref"].startswith("DEMO-")
    audit = client.get("/api/audit", headers=owner).json()
    assert any(a["action"] == "pagamento_autorizzato" for a in audit)


def test_recurring_in_forecast(client, owner):
    beta = companies(client, owner)["Azienda Beta Srl"]["id"]
    before = client.get(f"/api/forecast?company_id={beta}&weeks=8", headers=owner).json()
    client.post(f"/api/companies/{beta}/recurring", headers=owner,
                json={"kind": "uscita", "description": "Rata leasing", "amount": "1.000,00", "day_of_month": 15})
    after = client.get(f"/api/forecast?company_id={beta}&weeks=8", headers=owner).json()
    assert after["weeks"][-1]["balance_end_cents"] < before["weeks"][-1]["balance_end_cents"]


# ---------- Banche, documenti, export ----------

def test_connect_and_sync_bank(client, owner):
    gamma = companies(client, owner)["Azienda Gamma Srl"]["id"]
    r = client.post(f"/api/companies/{gamma}/bank-accounts/connect", headers=owner, json={"bank_name": "Banca Nuova"})
    acc = r.json()["accounts"][0]
    assert acc["consent_days_left"] == 180 and "iban" not in acc
    assert client.post(f"/api/bank-accounts/{acc['id']}/sync", headers=owner).status_code == 200


def test_documents_and_export(client, accountant):
    alfa = companies(client, accountant)["Azienda Alfa Srl"]["id"]
    r = client.post(f"/api/companies/{alfa}/documents", headers=accountant,
                    files={"file": ("F24 ottobre.pdf", b"%PDF-1.4 test", "application/pdf")},
                    data={"category": "F24", "period": "2026-10"})
    assert r.status_code == 200
    doc_id = r.json()["id"]
    assert client.get(f"/api/documents/{doc_id}/download", headers=accountant).content == b"%PDF-1.4 test"
    frm = (date.today() - timedelta(days=60)).isoformat()
    to = date.today().isoformat()
    for fmt in ("xlsx", "csv", "xml"):
        r = client.get(f"/api/companies/{alfa}/export?format={fmt}&date_from={frm}&date_to={to}", headers=accountant)
        assert r.status_code == 200, (fmt, r.text)
        assert len(r.content) > 100
