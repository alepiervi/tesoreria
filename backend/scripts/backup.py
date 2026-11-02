"""Crea subito un backup del database.

Uso:  python scripts/backup.py [cartella]
Senza cartella usa BACKUP_DIR del file .env.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.services.backup import run_backup  # noqa: E402


async def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else settings.backup_dir
    if not folder:
        print("Indica una cartella: python scripts/backup.py /percorso/backup (oppure imposta BACKUP_DIR nel .env)")
        return
    print("Backup creato:", await run_backup(get_db(), folder))


if __name__ == "__main__":
    asyncio.run(main())
