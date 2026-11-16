"""Fatture dal cassetto fiscale: ZIP dello scarico massivo e collegamento A-Cube (simulato)."""
import io
import zipfile

import httpx

from app.config import settings
from app.integrations import acube
from app.integrations.sdi import build_fatturapa_xml


def _company(client, h, name="Azienda Gamma Srl"):
    return next(c for c in client.get("/api/companies", headers=h).json() if c["name"] == name)


def _xml(company, number, seller="Fornitore Zip Srl", vat="05555555555"):
    return build_fatturapa_xml(number=number, issue_date="2026-05-10", total_cents=12200, due_date="2026-06-10",
                               seller_name=seller, seller_vat=vat, buyer_name=company["name"],
                               buyer_vat=company.get("vat_number", ""))


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_zip_from_cassetto_with_nested_zip_and_metadata(client, owner):
    c = _company(client, owner)
    inner = _zip({"IT05555555555_00002.xml": _xml(c, "Z-2/2026")})
    data = _zip({"fatture/IT05555555555_00001.xml": _xml(c, "Z-1/2026"),
                 "fatture/IT05555555555_00001_metaDato.xml": "<metadato/>",
                 "altro.zip": inner, "leggimi.txt": "x"})
    r = client.post(f"/api/companies/{c['id']}/invoices/import", headers=owner,
                    files=[("files", ("cassetto.zip", data, "application/zip"))])
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["imported"] == 2 and {x["number"] for x in res["results"]} == {"Z-1/2026", "Z-2/2026"}
    again = client.post(f"/api/companies/{c['id']}/invoices/import", headers=owner,
                        files=[("files", ("cassetto.zip", data, "application/zip"))]).json()
    assert again["imported"] == 0
    empty = client.post(f"/api/companies/{c['id']}/invoices/import", headers=owner,
                        files=[("files", ("vuoto.zip", _zip({"a.txt": "x"}), "application/zip"))]).json()
    assert empty["results"][0]["ok"] is False


def test_acube_sync_and_activation(client, owner, monkeypatch):
    c = _company(client, owner)
    xml = _xml(c, "AC-7/2026", seller="Fornitore Cassetto Spa", vat="06666666666")
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, dict(req.url.params)))
        if req.url.path == "/login":
            return httpx.Response(200, json={"token": "t"})
        if req.url.path == "/invoices":
            if "recipient.business_vat_number_code" in req.url.params:
                return httpx.Response(200, json={"hydra:member": [{"uuid": "u1"}], "hydra:view": {}})
            return httpx.Response(200, json={"hydra:member": []})
        if req.url.path == "/invoices/u1":
            return httpx.Response(200, text=xml, headers={"content-type": "application/xml"})
        if req.url.path.startswith("/business-registry-configurations/"):
            return httpx.Response(404, json={})
        if req.url.path == "/business-registry-configurations":
            return httpx.Response(201, json={"fiscal_id": "x"})
        if req.url.path.startswith("/schedule/invoice-download/"):
            return httpx.Response(200 if req.method == "GET" else 201, json={"enabled": True})
        return httpx.Response(500)

    real = httpx.AsyncClient
    monkeypatch.setattr(acube.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "acube_email", "api@example.com")
    monkeypatch.setattr(settings, "acube_password", "pw")
    acube.AcubeClient._token = None

    assert client.get("/api/auth/me", headers=owner).json().get("features", {}).get("cassetto") in ("acube", None)
    r = client.post(f"/api/companies/{c['id']}/cassetto/activate", headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["scheduled"] is True
    assert any(m == "POST" and p == "/business-registry-configurations" for m, p, _ in calls)
    r = client.post(f"/api/companies/{c['id']}/invoices/sync-sdi", headers=owner)
    assert r.status_code == 200 and r.json()["imported"] == 1
    inv = client.get(f"/api/companies/{c['id']}/invoices", headers=owner, params={"q": "AC-7"}).json()
    assert inv and inv[0]["source"] == "sdi"
    # seconda sincronizzazione: parte dall'ultima e non duplica
    r = client.post(f"/api/companies/{c['id']}/invoices/sync-sdi", headers=owner)
    assert r.json()["imported"] == 0
    assert any("created_at[after]" in params for _, p, params in calls if p == "/invoices")

    def denied(req):
        return httpx.Response(401, json={})
    monkeypatch.setattr(acube.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(denied), **kw))
    acube.AcubeClient._token = None
    r = client.post(f"/api/companies/{c['id']}/invoices/sync-sdi", headers=owner)
    assert r.status_code == 502 and "A-Cube" in r.json()["detail"]
