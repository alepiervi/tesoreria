"""Cassetto fiscale tramite A-Cube (intermediario accreditato presso l'Agenzia delle Entrate).

L'azienda dà la delega ad A-Cube sul portale Fatture e Corrispettivi; A-Cube scarica ogni notte
le fatture ricevute ed emesse e noi le leggiamo da qui.
"""
import asyncio
import re
from datetime import timedelta

import httpx

from ..config import settings
from ..utils import now_utc
from .sdi import SdiProvider

LOGIN_URL = "https://common.api.acubeapi.com/login"
BASE_URLS = {"sandbox": "https://api-sandbox.acubeapi.com", "production": "https://api.acubeapi.com"}
MAX_PER_SYNC = 600


class AcubeError(Exception):
    pass


class AcubeClient:
    _token: str | None = None
    _expires = None
    _lock = asyncio.Lock()

    @property
    def base(self) -> str:
        return BASE_URLS.get(settings.acube_environment, BASE_URLS["production"])

    async def token(self) -> str:
        async with self._lock:
            now = now_utc()
            if AcubeClient._token and now < AcubeClient._expires:
                return AcubeClient._token
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(LOGIN_URL, json={"email": settings.acube_email, "password": settings.acube_password})
            if r.status_code != 200:
                raise AcubeError("Accesso ad A-Cube non riuscito: controlla email e password del vostro account A-Cube.")
            AcubeClient._token = r.json()["token"]
            AcubeClient._expires = now + timedelta(hours=23)
            return AcubeClient._token

    async def request(self, method: str, path: str, accept: str = "application/json", **kw) -> httpx.Response:
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {await self.token()}", "Accept": accept}
            async with httpx.AsyncClient(base_url=self.base, timeout=60) as c:
                r = await c.request(method, path, headers=headers, **kw)
            if r.status_code == 401 and attempt == 0:
                AcubeClient._token = None
                continue
            return r
        return r


def fiscal_id(company: dict) -> str:
    vat = re.sub(r"[^0-9A-Za-z]", "", company.get("vat_number") or "")
    vat = re.sub(r"^IT", "", vat, flags=re.I)
    if not vat:
        raise AcubeError("Per scaricare dal cassetto fiscale serve la partita IVA dell'azienda (Impostazioni azienda).")
    return vat


def _check(r: httpx.Response, what: str):
    if r.status_code >= 400:
        detail = ""
        try:
            body = r.json()
            detail = body.get("hydra:description") or body.get("detail") or body.get("message") or ""
        except ValueError:
            pass
        raise AcubeError(f"A-Cube: {what} non riuscito ({r.status_code}){': ' + detail if detail else ''}.")


async def activate(company: dict, email: str) -> dict:
    """Configura l'azienda su A-Cube e attiva lo scarico giornaliero dal cassetto fiscale."""
    client, fid = AcubeClient(), fiscal_id(company)
    r = await client.request("GET", f"/business-registry-configurations/{fid}")
    if r.status_code == 404:
        r = await client.request("POST", "/business-registry-configurations", json={
            "fiscal_id": fid, "name": company.get("name", ""), "email": email, "supplier_invoice_enabled": True})
        _check(r, "registrazione dell'azienda")
    else:
        _check(r, "lettura dell'azienda")
    r = await client.request("POST", f"/schedule/invoice-download/{fid}", json={"download_archive": False})
    if r.status_code not in (200, 201, 202, 409, 422):
        _check(r, "attivazione dello scarico giornaliero")
    return await status(company)


async def status(company: dict) -> dict:
    client, fid = AcubeClient(), fiscal_id(company)
    r = await client.request("GET", f"/schedule/invoice-download/{fid}")
    if r.status_code == 404:
        return {"fiscal_id": fid, "scheduled": False}
    _check(r, "lettura dello stato")
    return {"fiscal_id": fid, "scheduled": True, "detail": r.json()}


class AcubeSdiProvider(SdiProvider):
    name = "acube"

    async def fetch_new_invoices(self, company: dict) -> list[str]:
        client, fid = AcubeClient(), fiscal_id(company)
        since = company.get("acube_last_sync") or (now_utc() - timedelta(days=90)).isoformat()
        since = (since[:19] if len(since) >= 19 else since)
        xmls, seen = [], set()
        for side in ("recipient.business_vat_number_code", "sender.business_vat_number_code"):
            page = 1
            while len(xmls) < MAX_PER_SYNC:
                r = await client.request("GET", "/invoices", accept="application/ld+json",
                                         params={side: fid, "created_at[after]": since, "page": page, "itemsPerPage": 30})
                _check(r, "elenco delle fatture")
                body = r.json()
                members = body.get("hydra:member", body if isinstance(body, list) else [])
                for inv in members:
                    uid = inv.get("uuid")
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    x = await client.request("GET", f"/invoices/{uid}", accept="application/xml")
                    _check(x, "scarico della fattura")
                    xmls.append(x.text)
                if not members or not (isinstance(body, dict) and body.get("hydra:view", {}).get("hydra:next")):
                    break
                page += 1
        return xmls
