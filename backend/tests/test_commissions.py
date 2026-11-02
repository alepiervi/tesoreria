"""Provvigioni sulle attivazioni dei partner."""
from datetime import date, timedelta
from pathlib import Path

from app import db as db_module
from app.services import commissions as cm

ESEMPI = Path(__file__).resolve().parents[2] / "esempi"


def beta(client, h):
    return next(c["id"] for c in client.get("/api/companies", headers=h).json() if c["name"] == "Azienda Beta Srl")


def find(client, coll, q):
    async def go():
        return await db_module.get_db()[coll].find(q, {"_id": 0}).to_list(5000)
    return client.portal.call(go)


def partner(client, h, cid, name):
    return next(p for p in client.get(f"/api/companies/{cid}/commission-partners", headers=h).json() if p["name"] == name)


def prev_month(n=1):
    d = date.today().replace(day=1)
    for _ in range(n):
        d = (d - timedelta(days=1)).replace(day=1)
    return d.strftime("%Y-%m")


def test_guess_status_and_detect():
    assert cm.guess_status("ESPLETATO") == "attiva" and cm.guess_status("Attivo") == "attiva"
    assert cm.guess_status("KO CLIENTE") == "ko" and cm.guess_status("Annullato") == "ko"
    assert cm.guess_status("Cessata per morosità") == "cessata" and cm.guess_status("Inserito") == "in_lavorazione"
    assert cm.guess_status("Non attivabile") == "ko"
    assert cm.guess_status("xyz") is None
    rows = [["Report"], ["ID Pratica", "CF/PIVA", "Account", "Offerta", "Esito", "Data Esito"], ["1", "AAA", "2", "X", "Attivo", "01/10/2026"]]
    idx, headers, m = cm.detect(rows, cm.PARTNER_FIELDS)
    assert idx == 1 and m["pratica"] == "ID Pratica" and m["codice_fiscale"] == "CF/PIVA" and m["stato"] == "Esito"
    assert cm.norm_code(" 00123 ") == "123" and cm.norm_code(4191165.0) == "4191165"


def test_import_backoffice_and_partner_files_match(client, owner):
    cid = beta(client, owner)
    bo = (ESEMPI / "backoffice_vendite_esempio.csv").read_bytes()
    r = client.post(f"/api/companies/{cid}/commissions/backoffice", headers=owner, files={"file": ("bo.csv", bo, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == 10
    fw = partner(client, owner, cid, "Fastweb")
    r = client.post(f"/api/commission-partners/{fw['id']}/import", headers=owner,
                    files={"file": ("fw.csv", (ESEMPI / "avanzamenti_fastweb_esempio.csv").read_bytes(), "text/csv")})
    assert r.status_code == 200, r.text
    res = r.json()
    assert not res.get("needs_mapping") and res["new"] == 5 and not res["unknown_statuses"]
    acts = {a["external_id"]: a for a in find(client, "commission_activations", {"partner_id": fw["id"], "external_id": {"$regex": "^FW-"}})}
    assert len(acts) == 5
    # FW-780000 è del codice TP01 → Telco Point
    tp = next(b for b in find(client, "commission_beneficiaries", {"company_id": cid}) if b["name"] == "Telco Point Srl")
    assert acts["FW-780000"]["beneficiary_id"] == tp["id"] and "codice fiscale e account" in acts["FW-780000"]["match_note"]
    # un secondo import con lo stato cambiato aggiorna la pratica e ne tiene la storia
    text = (ESEMPI / "avanzamenti_fastweb_esempio.csv").read_text(encoding="utf-8").replace("IN LAVORAZIONE", "ESPLETATO")
    r = client.post(f"/api/commission-partners/{fw['id']}/import", headers=owner, files={"file": ("fw.csv", text.encode(), "text/csv")}).json()
    assert r["new"] == 0
    # Vodafone: colonne diverse, riconosciute da sole; il codice ZZ07 non è di nessuno
    vf = partner(client, owner, cid, "Vodafone")
    r = client.post(f"/api/commission-partners/{vf['id']}/import", headers=owner,
                    files={"file": ("vf.csv", (ESEMPI / "avanzamenti_vodafone_esempio.csv").read_bytes(), "text/csv")}).json()
    assert r["new"] == 5
    unassigned = find(client, "commission_activations", {"company_id": cid, "beneficiary_id": None})
    assert any("ZZ07" in (a["match_note"] or "") for a in unassigned)
    lst = client.get(f"/api/companies/{cid}/commission-beneficiaries", headers=owner).json()
    assert any(u["code"] == "ZZ07" for u in lst["unknown_codes"])


def test_mapping_requested_and_saved(client, owner):
    cid = beta(client, owner)
    sky = partner(client, owner, cid, "SKY")
    csv_text = "Riferimento;Cod. Fisc. Intestatario;Pacchetto;Situazione;Quando\nSKY1;RSSMRA80A01H501U;SKY TV;Attivato;10/10/2026\n"
    r = client.post(f"/api/commission-partners/{sky['id']}/import", headers=owner, files={"file": ("s.csv", csv_text.encode(), "text/csv")}).json()
    assert r["needs_mapping"] and "Codice pratica / contratto" in r["missing"]
    mapping = {"pratica": "Riferimento", "codice_fiscale": "Cod. Fisc. Intestatario", "offerta": "Pacchetto", "stato": "Situazione",
               "data_stato": "Quando"}
    import json
    r = client.post(f"/api/commission-partners/{sky['id']}/import", headers=owner,
                    files={"file": ("s.csv", csv_text.encode(), "text/csv")}, data={"mapping": json.dumps(mapping)}).json()
    assert r["new"] == 1
    # la volta dopo la mappatura è già salvata
    r = client.post(f"/api/commission-partners/{sky['id']}/import", headers=owner, files={"file": ("s.csv", csv_text.encode(), "text/csv")}).json()
    assert not r.get("needs_mapping") and r["unchanged"] == 1
    a = find(client, "commission_activations", {"external_id": "SKY1"})[0]
    assert a["status"] == "attiva" and a["activation_date"] == "2026-10-10" and a["offer_id"]


def test_unknown_status_mapping(client, owner):
    cid = beta(client, owner)
    fw = partner(client, owner, cid, "Fastweb")
    text = "Codice Ordine;Codice Fiscale;Prodotto;Stato Ordine;Data Stato\nFWX1;BBBCCC80A01H501Z;FASTWEB CASA LIGHT;FASE 7B;05/10/2026\n"
    r = client.post(f"/api/commission-partners/{fw['id']}/import", headers=owner, files={"file": ("f.csv", text.encode(), "text/csv")}).json()
    assert r["unknown_statuses"] == ["FASE 7B"]
    st = client.get(f"/api/commission-partners/{fw['id']}/statuses", headers=owner).json()
    assert st["rows"][0]["status"] is None
    r = client.put(f"/api/commission-partners/{fw['id']}/statuses", headers=owner, json={"status_map": {"FASE 7B": "attiva"}}).json()
    assert r["updated"] == 1
    assert find(client, "commission_activations", {"external_id": "FWX1"})[0]["status"] == "attiva"


def test_statement_approve_storno_recovery_and_payment(client, owner, admin, accountant):
    cid = beta(client, owner)
    m1 = prev_month(1)
    st = client.get(f"/api/companies/{cid}/commission-statements?month={m1}", headers=owner).json()
    tp = next(r for r in st["rows"] if r["beneficiary"]["name"] == "Telco Point Srl")
    storni = [l for l in tp["lines"] if l["type"] == "storno"]
    assert len(storni) == 2 and all(l["amount_cents"] < 0 for l in storni)  # recupero di provvigioni già pagate
    assert tp["status"] == "bozza"
    # il commercialista vede ma non approva
    assert client.post(f"/api/companies/{cid}/commission-statements/approve", headers=accountant, json={"month": m1}).status_code == 403
    # il mese in corso non si approva
    cur = date.today().strftime("%Y-%m")
    assert client.post(f"/api/companies/{cid}/commission-statements/approve", headers=admin, json={"month": cur}).status_code == 400
    r = client.post(f"/api/companies/{cid}/commission-statements/approve", headers=admin, json={"month": m1})
    assert r.status_code == 200, r.text
    st = client.get(f"/api/companies/{cid}/commission-statements?month={m1}", headers=owner).json()
    assert all(row["status"] in {"approvato", "chiuso"} for row in st["rows"])
    tp = next(r for r in st["rows"] if r["beneficiary"]["name"] == "Telco Point Srl")
    if tp["total_cents"] > 0:
        d = find(client, "deadlines", {"commission_statement_id": tp["statement_id"]})[0]
        assert d["amount_cents"] == tp["total_cents"] and d["iban"] and d["kind"] == "pagamento"
    # dipendenti: nessun pagamento in scadenzario (vanno in busta paga)
    dip = next(r for r in st["rows"] if r["beneficiary"]["kind"] == "dipendente")
    assert not find(client, "deadlines", {"commission_statement_id": dip["statement_id"]})
    # le attivazioni pagate non compaiono più nelle bozze dei mesi dopo
    nxt = client.get(f"/api/companies/{cid}/commission-statements?month={cur}", headers=owner).json()
    paid_ids = {l["activation_id"] for r in st["rows"] for l in r["lines"] if l["type"] == "attivazione"}
    assert not paid_ids & {l.get("activation_id") for r in nxt["rows"] for l in r["lines"]}
    # export Excel
    x = client.get(f"/api/companies/{cid}/commission-statements/export?month={m1}&kind=dipendente", headers=owner)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    # riapertura e pagamento
    assert client.post(f"/api/commission-statements/{tp['statement_id']}/reopen", headers=admin).status_code == 200
    assert not find(client, "commission_activations", {"paid_statement_id": tp["statement_id"]})
    client.post(f"/api/companies/{cid}/commission-statements/approve", headers=admin, json={"month": m1, "beneficiary_ids": [tp["beneficiary"]["id"]]})
    st = client.get(f"/api/companies/{cid}/commission-statements?month={m1}", headers=owner).json()
    tp = next(r for r in st["rows"] if r["beneficiary"]["name"] == "Telco Point Srl")
    if tp["status"] == "approvato":
        assert client.post(f"/api/commission-statements/{tp['statement_id']}/paid", headers=admin).status_code == 200


def test_negative_balance_is_carried_forward(client, owner):
    cid = beta(client, owner)

    async def setup():
        db = db_module.get_db()
        ben = await db.commission_beneficiaries.find_one({"company_id": cid, "name": "Giulia Bianchi"})
        # tutte le attivazioni già pagate di Giulia vengono stornate il mese scorso
        acts = await db.commission_activations.find({"beneficiary_id": ben["id"], "paid_statement_id": {"$ne": None}}).to_list(100)
        sd = f"{prev_month(1)}-05"
        for a in acts:
            await db.commission_activations.update_one({"id": a["id"]}, {"$set": {"status": "cessata", "storno_date": sd}})
        # e quelle non ancora pagate restano fuori dal mese scorso
        await db.commission_activations.update_many({"beneficiary_id": ben["id"], "paid_statement_id": None},
                                                    {"$set": {"activation_date": date.today().isoformat()}})
        return ben["id"], len(acts)
    bid, n = client.portal.call(setup)
    assert n > 0
    m1 = prev_month(1)
    st = client.get(f"/api/companies/{cid}/commission-statements?month={m1}", headers=owner).json()
    row = next(r for r in st["rows"] if r["beneficiary"]["id"] == bid)
    assert row["total_cents"] < 0
    client.post(f"/api/companies/{cid}/commission-statements/approve", headers=owner, json={"month": m1, "beneficiary_ids": [bid]})
    cur = client.get(f"/api/companies/{cid}/commission-statements?month={date.today().strftime('%Y-%m')}", headers=owner).json()
    row2 = next(r for r in cur["rows"] if r["beneficiary"]["id"] == bid)
    assert any(l["type"] == "riporto" and l["amount_cents"] == row["total_cents"] for l in row2["lines"])


def test_contest_tiers(client, owner):
    cid = beta(client, owner)
    m1 = prev_month(1)
    r = client.post(f"/api/companies/{cid}/commission-contests", headers=owner, json={
        "name": "Sprint", "kind": "dipendente", "valid_from": prev_month(2),
        "tiers": [{"min": 1, "bonus": "10", "per_activation": "2"}]})
    assert r.status_code == 200, r.text
    st = client.get(f"/api/companies/{cid}/commission-statements?month={m1}", headers=owner).json()
    gare = [l for row in st["rows"] if row["beneficiary"]["kind"] == "dipendente" for l in row["lines"] if "Sprint" in l["description"]]
    assert gare and all(l["amount_cents"] >= 1200 for l in gare)
    # le strutture non partecipano a questa gara
    assert not [l for row in st["rows"] if row["beneficiary"]["kind"] == "struttura" for l in row["lines"] if "Sprint" in l["description"]]
    assert client.post(f"/api/companies/{cid}/commission-contests", headers=owner, json={
        "name": "x", "valid_from": "2026-13", "tiers": [{"min": 1}]}).status_code == 400


def test_manual_assign_offers_and_beneficiaries(client, owner):
    cid = beta(client, owner)
    data = client.get(f"/api/companies/{cid}/commission-activations?assigned=no", headers=owner).json()
    assert data["total"] > 0
    a = data["items"][0]
    bens = client.get(f"/api/companies/{cid}/commission-beneficiaries", headers=owner).json()["items"]
    r = client.post(f"/api/commission-activations/{a['id']}/assign", headers=owner, json={"beneficiary_id": bens[0]["id"]})
    assert r.status_code == 200
    got = find(client, "commission_activations", {"id": a["id"]})[0]
    assert got["beneficiary_id"] == bens[0]["id"] and got["assignment"] == "manuale"
    # codice duplicato
    r = client.post(f"/api/companies/{cid}/commission-beneficiaries", headers=owner, json={"kind": "dipendente", "name": "X", "codes": ["MR01"]})
    assert r.status_code == 400
    # nuovo venditore con il codice sconosciuto XX99: le sue attivazioni si abbinano da sole
    r = client.post(f"/api/companies/{cid}/commission-beneficiaries", headers=owner, json={"kind": "dipendente", "name": "Nuovo", "codes": ["xx-99"]})
    assert r.status_code == 200 and r.json()["codes"] == ["XX99"]
    assert find(client, "commission_activations", {"beneficiary_id": r.json()["id"]})
    # listino: un'offerta nuova viene abbinata alle attivazioni esistenti
    fw = partner(client, owner, cid, "Fastweb")
    r = client.post(f"/api/companies/{cid}/commission-offers", headers=owner, json={
        "partner_id": fw["id"], "name": "Casa Light", "match": "fastweb casa light", "revenue": "200", "payout_struttura": "100", "payout_dipendente": "30"})
    assert r.status_code == 200
    assert find(client, "commission_activations", {"offer_id": r.json()["id"]})
    ov = client.get(f"/api/companies/{cid}/commissions/overview", headers=owner).json()
    assert ov["setup"]["partners"] == 3 and "margin_cents" in ov
