"""Crea il primo utente titolare (da usare con dati veri e SEED_DEMO=false).

Uso:  python scripts/create_owner.py
"""
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import create_indexes, get_db  # noqa: E402
from app.security import hash_password, validate_password_strength  # noqa: E402
from app.utils import new_id, now_iso  # noqa: E402


async def main():
    email = input("Email: ").strip().lower()
    name = input("Nome e cognome: ").strip()
    password = getpass.getpass("Password: ")
    problem = validate_password_strength(password)
    if problem:
        print(problem)
        return
    if password != getpass.getpass("Ripeti la password: "):
        print("Le password non coincidono.")
        return
    db = get_db()
    await create_indexes()
    if await db.users.find_one({"email": email}):
        await db.users.update_one({"email": email}, {"$set": {"is_owner": True}})
        print("Utente già esistente: ora è titolare del gruppo.")
        return
    await db.users.insert_one({
        "id": new_id(), "email": email, "name": name, "password_hash": hash_password(password),
        "is_owner": True, "active": True, "totp_enabled": False, "token_version": 0, "created_at": now_iso(),
    })
    print(f"Titolare creato: {email}. Accedi e crea le tue aziende da Impostazioni.")


if __name__ == "__main__":
    asyncio.run(main())
