import asyncio

from mongomock_motor import AsyncMongoMockClient

from app import db as db_module
from app.seed import ensure_developer


def _db(name):
    db_module.set_database(AsyncMongoMockClient()[name])
    return db_module.get_db()


def test_creates_developer_without_company_access():
    db = _db("dev_test")
    assert asyncio.run(ensure_developer("Dev@Nureal.it", "Password2026", "Dev")) == "created"
    assert asyncio.run(ensure_developer("Dev@Nureal.it", "Password2026", "Dev")) is None
    u = asyncio.run(db.users.find_one({"email": "dev@nureal.it"}))
    assert u["is_developer"] and not u["is_owner"]


def test_converts_existing_owner_and_drops_memberships():
    db = _db("dev_test2")
    asyncio.run(db.users.insert_one({"id": "u1", "email": "a@b.it", "is_owner": True, "token_version": 0}))
    asyncio.run(db.memberships.insert_one({"id": "m1", "user_id": "u1", "company_id": "c1", "role": "titolare"}))
    assert asyncio.run(ensure_developer("a@b.it", "Password2026", "x")) == "converted"
    u = asyncio.run(db.users.find_one({"id": "u1"}))
    assert u["is_developer"] and not u["is_owner"] and u["token_version"] == 1
    assert asyncio.run(db.memberships.count_documents({"user_id": "u1"})) == 0


def test_skips_without_credentials():
    _db("dev_test3")
    assert asyncio.run(ensure_developer("", "", "x")) is None


def test_error_text_hides_numbers_emails_and_ids():
    from app.services.errors import clean_path, clean_text
    assert clean_text("cliente mario@rossi.it importo 12500", 100) == "cliente <email> importo :n"
    assert clean_path("/api/companies/0b6f3c1e-1111-2222-3333-444455556666/invoices") == "/api/companies/:id/invoices"


def test_client_messages_keep_only_code_level_text():
    from app.services.errors import HIDDEN, safe_client_message
    assert safe_client_message("TypeError: Cannot read properties of undefined (reading 'amount')").endswith("'amount')")
    assert safe_client_message("x.map is not a function") == "x.map is not a function"
    assert safe_client_message("TypeError: Cannot read property of 'Rossi Srl'") == f"TypeError: {HIDDEN}"
    assert safe_client_message("Fattura Rossi non trovata") == HIDDEN
