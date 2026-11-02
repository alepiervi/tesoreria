"""Backup e ripristino del database in un file .json.gz (funziona con qualsiasi MongoDB, senza mongodump).

Uso manuale:
    python scripts/backup.py              crea un backup in BACKUP_DIR (o nella cartella indicata)
    python scripts/restore.py FILE        ripristina un backup (sovrascrive i dati attuali!)
"""
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import json_util

from ..config import settings

COLLECTIONS = [
    "users", "companies", "memberships", "invites", "bank_accounts", "transactions", "invoices", "invoice_xml",
    "deadlines", "recurring", "notes", "documents", "audit", "statement_imports", "category_rules", "contacts",
    "notifications", "outbox", "budgets", "loans", "receipts", "assistant_log", "jobs",
    "accounts", "entries", "assets", "accruals", "cost_centers", "supplier_accounts",
    "payrolls", "month_closes", "central_risk", "inventories", "business_plans",
    "commission_partners", "commission_offers", "commission_beneficiaries", "commission_contests", "commission_sales",
    "commission_activations", "commission_statements", "commission_imports", "commission_settings",
]


async def dump(db) -> bytes:
    data = {"created_at": datetime.now(timezone.utc).isoformat(), "collections": {}}
    for name in COLLECTIONS:
        data["collections"][name] = [doc async for doc in db[name].find({})]
    return gzip.compress(json_util.dumps(data).encode("utf-8"))


async def restore(db, raw: bytes) -> dict:
    data = json_util.loads(gzip.decompress(raw).decode("utf-8"))
    counts = {}
    for name, docs in data["collections"].items():
        await db[name].delete_many({})
        if docs:
            await db[name].insert_many(docs)
        counts[name] = len(docs)
    return counts


async def run_backup(db, folder: str | None = None) -> str:
    folder = Path(folder or settings.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"tesoreria_{datetime.now().strftime('%Y-%m-%d_%H%M')}.json.gz"
    path.write_bytes(await dump(db))
    os.chmod(path, 0o600)
    limit = datetime.now() - timedelta(days=settings.backup_keep_days)
    for old in folder.glob("tesoreria_*.json.gz"):
        if datetime.fromtimestamp(old.stat().st_mtime) < limit:
            old.unlink()
    return str(path)


def describe(raw: bytes) -> dict:
    data = json.loads(gzip.decompress(raw).decode("utf-8"))
    return {"created_at": data["created_at"], "collections": {k: len(v) for k, v in data["collections"].items()}}
