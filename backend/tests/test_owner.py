import asyncio

from mongomock_motor import AsyncMongoMockClient

from app import db as db_module
from app.seed import ensure_owner


def test_ensure_owner_creates_only_on_empty_db():
    db_module.set_database(AsyncMongoMockClient()["owner_test"])
    assert asyncio.run(ensure_owner("Capo@Nureal.it", "Password2026", "Capo")) is True
    assert asyncio.run(ensure_owner("altro@nureal.it", "Password2026", "Altro")) is False
    users = asyncio.run(db_module.get_db().users.find({}, {"_id": 0}).to_list(10))
    assert len(users) == 1 and users[0]["email"] == "capo@nureal.it" and users[0]["is_owner"]


def test_ensure_owner_skips_without_credentials():
    db_module.set_database(AsyncMongoMockClient()["owner_test2"])
    assert asyncio.run(ensure_owner("", "", "x")) is False
