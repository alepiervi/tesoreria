"""Connessione a MongoDB.

Il client si può sostituire nei test (vedi tests/conftest.py) chiamando set_database().
"""
from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        if settings.mongo_url.startswith("mock://"):
            # Database in memoria per provare il programma senza installare MongoDB.
            # I dati si perdono a ogni riavvio: non usarlo con dati veri.
            from mongomock_motor import AsyncMongoMockClient
            _client = AsyncMongoMockClient()
        else:
            _client = AsyncIOMotorClient(settings.mongo_url)
        _db = _client[settings.db_name]
    return _db


def set_database(db):
    global _db
    _db = db


async def create_indexes():
    db = get_db()
    await db.users.create_index("id", unique=True)
    await db.users.create_index("email", unique=True)
    await db.companies.create_index("id", unique=True)
    await db.memberships.create_index([("user_id", 1), ("company_id", 1)], unique=True)
    await db.bank_accounts.create_index("company_id")
    await db.transactions.create_index([("company_id", 1), ("date", -1)])
    await db.transactions.create_index("external_id")
    await db.invoices.create_index([("company_id", 1), ("date", -1)])
    await db.deadlines.create_index([("company_id", 1), ("due_date", 1)])
    await db.notes.create_index([("target_type", 1), ("target_id", 1)])
    await db.documents.create_index("company_id")
    await db.invites.create_index("token_hash", unique=True)
    await db.audit.create_index([("at", -1)])
    await db.recurring.create_index("company_id")
    await db.statement_imports.create_index([("account_id", 1), ("at", -1)])
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("user_id", 1), ("key", 1)])
    await db.contacts.create_index([("company_id", 1), ("vat_key", 1)])
    await db.budgets.create_index([("company_id", 1), ("year", 1)])
    await db.loans.create_index("company_id")
    await db.category_rules.create_index("company_id")
    await db.outbox.create_index([("created_at", -1)])
    await db.jobs.create_index("name", unique=True)
    await db.accounts.create_index([("company_id", 1), ("code", 1)], unique=True)
    await db.entries.create_index([("company_id", 1), ("date", 1)])
    await db.entries.create_index([("company_id", 1), ("source_key", 1)])
    await db.assets.create_index("company_id")
    await db.cost_centers.create_index("company_id")
    await db.payrolls.create_index([("company_id", 1), ("month", 1)], unique=True)
    await db.month_closes.create_index([("company_id", 1), ("month", 1)], unique=True)
    await db.central_risk.create_index([("company_id", 1), ("month", 1)])
    await db.inventories.create_index([("company_id", 1), ("year", 1)], unique=True)
    await db.business_plans.create_index("company_id", unique=True)
    await db.commission_activations.create_index([("company_id", 1), ("partner_id", 1), ("external_id", 1)], unique=True)
    await db.commission_activations.create_index([("company_id", 1), ("beneficiary_id", 1)])
    await db.commission_sales.create_index([("company_id", 1), ("customer_cf", 1), ("account", 1), ("seller_code", 1)], unique=True)
    await db.commission_statements.create_index([("company_id", 1), ("month", 1), ("beneficiary_id", 1)], unique=True)
    await db.commission_partners.create_index("company_id")
    await db.commission_offers.create_index([("company_id", 1), ("partner_id", 1)])
    await db.commission_beneficiaries.create_index("company_id")
