# Smoke test: all main GET endpoints for all companies/roles must not return 5xx; commercialista isolation
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"
PWD = "Demo2026demo"

COMPANY_GETS = [
    "", "accounting-checks", "accounting-export", "accounting-settings", "accounts", "accruals", "assets",
    "bank-accounts", "budget", "budget/suggest", "central-risk", "commission-activations",
    "commission-beneficiaries", "commission-contests", "commission-offers", "commission-partners",
    "commission-settings", "commission-statements", "commissions/overview", "cost-center-report",
    "cost-centers", "dashboard", "documents", "entries", "entry-templates", "export-settings",
    "fiscal-years", "health", "inventories", "invoices", "invoices-to-classify", "journal-export", "ledger",
    "month-close", "open-items", "parties", "parties-export", "payrolls", "plan", "projects", "receipts",
    "recurring", "statements", "transactions", "trial-balance", "vat", "vat-registers",
]
GLOBAL_GETS = [
    "me", "me/notification-settings", "roles", "categories", "category-rules", "document-categories",
    "dashboard/group", "deadlines", "forecast", "forecast/open-items", "group/compare", "group/consolidated",
    "group/liquidity", "intercompany", "invites", "members", "notifications", "notifications/unread-count",
    "outbox", "questions", "receivables", "reconciliation", "loans", "assistant/status",
    "reports/monthly?month=2026-01",
]
COMPANY_QUERY_GETS = ["deadlines", "forecast", "receivables", "reconciliation", "loans", "questions",
                      "reports/monthly?month=2026-01"]


def login(email):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PWD}, timeout=30)
    assert r.status_code == 200, r.text
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return s


@pytest.fixture(scope="module")
def owner():
    return login("titolare@demo.it")


@pytest.fixture(scope="module")
def companies(owner):
    r = owner.get(f"{API}/companies", timeout=30)
    assert r.status_code == 200
    return r.json()


@pytest.mark.parametrize("email", ["titolare@demo.it", "amministrazione@demo.it", "commercialista@demo.it"])
def test_all_gets_no_5xx(email):
    s = login(email)
    comps = s.get(f"{API}/companies", timeout=30).json()
    failures = []
    for p in GLOBAL_GETS:
        r = s.get(f"{API}/{p}", timeout=60)
        if r.status_code >= 500:
            failures.append((p, r.status_code, r.text[:200]))
    for c in comps:
        for p in COMPANY_GETS:
            url = f"{API}/companies/{c['id']}" + (f"/{p}" if p else "")
            r = s.get(url, timeout=60)
            if r.status_code >= 500:
                failures.append((url, r.status_code, r.text[:200]))
            elif r.status_code >= 400:
                print("4xx", email, url, r.status_code, r.text[:150])
        for p in COMPANY_QUERY_GETS:
            sep = "&" if "?" in p else "?"
            r = s.get(f"{API}/{p}{sep}company_id={c['id']}", timeout=60)
            if r.status_code >= 500:
                failures.append((p, c["name"], r.status_code, r.text[:200]))
    assert not failures, failures


def test_commercialista_isolation(companies):
    s = login("commercialista@demo.it")
    names = [c["name"] for c in s.get(f"{API}/companies", timeout=30).json()]
    print("commercialista sees", names)
    assert not any("Gamma" in n for n in names)
    gamma = [c for c in companies if "Gamma" in c["name"]]
    assert gamma
    gid = gamma[0]["id"]
    for p in ["", "transactions", "invoices", "dashboard", "bank-accounts", "vat"]:
        r = s.get(f"{API}/companies/{gid}" + (f"/{p}" if p else ""), timeout=30)
        assert r.status_code == 404, (p, r.status_code)
    for p in ["deadlines", "reconciliation", "receivables", "loans"]:
        r = s.get(f"{API}/{p}?company_id={gid}", timeout=30)
        assert r.status_code == 404, (p, r.status_code, r.text[:100])
    # group views must not leak Gamma
    r = s.get(f"{API}/dashboard/group", timeout=30)
    # Gamma may appear as counterparty name on Alfa/Beta docs; check its company_id is never exposed
    assert gid not in r.text
    for p in ["deadlines", "forecast", "intercompany", "reconciliation", "receivables"]:
        assert gid not in s.get(f"{API}/{p}", timeout=30).text, p


def test_assistant_answers():
    s = login("titolare@demo.it")
    import json
    from pathlib import Path
    src = Path("/app/backend/app/routers/assistant.py").read_text()
    print([l for l in src.splitlines() if "@router.post" in l])
