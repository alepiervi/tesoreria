import asyncio

from app.db import get_db
from app.services import ai_usage
from app.utils import today
from tests.conftest import login


def test_usage_summary_owner_only(client):
    h = login(client, "titolare@demo.it")
    month = today().strftime("%Y-%m")
    rows = [{"id": "a", "at": "x", "month": month, "kind": "domanda", "user_id": "u1", "user_name": "Mario",
             "input_tokens": 1_000_000, "output_tokens": 100_000, "model": "m"},
            {"id": "b", "at": "x", "month": month, "kind": "documento", "user_id": "u2", "user_name": "Anna",
             "input_tokens": 0, "output_tokens": 200_000, "model": "m"}]
    asyncio.run(get_db().ai_usage.insert_many(rows))
    data = client.get("/api/settings/ai-usage", headers=h).json()
    assert data["month"] == month and len(data["history"]) == 6
    assert data["total"]["requests"] >= 2 and data["total"]["cost_usd"] >= 7.5
    assert {k["kind"] for k in data["by_kind"]} >= {"domanda", "documento"}
    assert "Mario" in {u["name"] for u in data["by_user"]}
    assert client.get("/api/settings/ai-usage", headers=login(client, "commercialista@demo.it")).status_code == 403


def test_cost_estimate():
    assert ai_usage.cost_usd(1_000_000, 1_000_000) == 18.0
