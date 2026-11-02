import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-abbastanza-lungo-per-hs256-0123456789")
os.environ["SEED_DEMO"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["REQUIRE_2FA_FOR_PAYMENTS"] = "false"
os.environ["AI_PROVIDER"] = "demo"
os.environ["EMAIL_PROVIDER"] = "demo"

from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from app import db as db_module  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402


@pytest.fixture()
def client():
    db_module.set_database(AsyncMongoMockClient()["test"])
    from server import app
    with TestClient(app) as c:
        yield c


def login(client, email, password=DEMO_PASSWORD):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def owner(client):
    return login(client, "titolare@demo.it")


@pytest.fixture()
def admin(client):
    return login(client, "amministrazione@demo.it")


@pytest.fixture()
def accountant(client):
    return login(client, "commercialista@demo.it")
