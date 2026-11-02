"""Ripristina un backup. ATTENZIONE: sostituisce tutti i dati attuali con quelli del backup.

Uso:  python scripts/restore.py /percorso/tesoreria_AAAA-MM-GG_HHMM.json.gz
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_db  # noqa: E402
from app.services.backup import describe, restore  # noqa: E402


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    raw = Path(sys.argv[1]).read_bytes()
    info = describe(raw)
    print(f"Backup del {info['created_at']}: {info['collections'].get('transactions', 0)} movimenti, "
          f"{info['collections'].get('invoices', 0)} fatture.")
    if input("Sostituire TUTTI i dati attuali con questo backup? Scrivi SI per confermare: ").strip() != "SI":
        print("Annullato.")
        return
    counts = await restore(get_db(), raw)
    print("Ripristino completato:", sum(counts.values()), "documenti.")


if __name__ == "__main__":
    asyncio.run(main())
