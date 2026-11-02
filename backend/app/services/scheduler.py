"""Attività automatiche: girano dentro il backend, controllando ogni 10 minuti se c'è qualcosa da fare.

- ogni giorno dall'ora ALERTS_HOUR: avvisi, aggiornamento IVA stimata, backup
- il lunedì: riepilogo settimanale via email
- il primo del mese: report PDF del mese precedente

Ogni attività registra l'ultimo giorno in cui è stata eseguita (collezione `jobs`), così non si ripete
anche se il server si riavvia. Se il backend gira su più copie, attivare lo scheduler su una sola
(SCHEDULER_ENABLED=false sulle altre) oppure usare un cron esterno che chiama gli stessi job.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import settings
from ..db import get_db
from ..utils import now_iso

logger = logging.getLogger("tesoreria.scheduler")
CHECK_EVERY_SECONDS = 600


async def _once(db, name: str, period: str, fn) -> bool:
    """Esegue fn una sola volta per 'period' (es. il giorno o la settimana)."""
    job = await db.jobs.find_one({"name": name})
    if job and job.get("period") == period:
        return False
    await db.jobs.update_one({"name": name}, {"$set": {"name": name, "period": period, "started_at": now_iso()}}, upsert=True)
    try:
        result = await fn(db)
        await db.jobs.update_one({"name": name}, {"$set": {"finished_at": now_iso(), "result": str(result)[:200], "error": None}})
        logger.info("Attività %s completata: %s", name, result)
    except Exception as e:  # noqa: BLE001 - un errore non deve fermare le altre attività
        logger.exception("Attività %s non riuscita", name)
        await db.jobs.update_one({"name": name}, {"$set": {"error": str(e)[:500], "finished_at": now_iso()}})
    return True


async def _sync_accounting(db):
    """Ricostruisce le registrazioni automatiche e le scadenze F24 delle ritenute di tutte le aziende."""
    from .accounting import sync_company
    done = 0
    async for c in db.companies.find({}, {"id": 1}):
        await sync_company(db, c["id"])
        done += 1
    return {"aziende": done}


async def _month_close_reminders(db):
    """Dal giorno 10: avvisa chi gestisce la contabilità se il mese precedente non è ancora chiuso."""
    from .month_close import checklist, previous_month
    from .notifications import notify, users_with
    month = previous_month()
    sent = 0
    async for c in db.companies.find({}, {"_id": 0}):
        status = await checklist(db, c, month)
        if status["closed"]:
            continue
        users = await users_with(db, c["id"], "manage_accounting")
        sent += await notify(db, users, kind="contabilita", company_id=c["id"], link="/chiusura-mese",
                             key=f"chiusura-mese:{c['id']}:{month}",
                             title=f"Chiusura di {month[5:]}/{month[:4]} · {c['name']}",
                             body=f"Mancano {status['missing']} controlli per chiudere il mese." if status["missing"]
                             else "Tutti i controlli sono a posto: il mese si può chiudere.")
    return {"avvisi": sent}


async def tick(db, now: datetime | None = None):
    from . import notifications
    from .backup import run_backup
    from .vat import sync_all_vat

    now = now or datetime.now(ZoneInfo(settings.timezone))
    if now.hour < settings.alerts_hour:
        return
    day = now.date().isoformat()
    await _once(db, "iva_stimata", day, sync_all_vat)
    await _once(db, "avvisi_giornalieri", day, notifications.run_daily_alerts)
    await _once(db, "contabilita", day, _sync_accounting)
    if settings.backup_dir:
        await _once(db, "backup", day, run_backup)
    if now.day >= 10:
        await _once(db, "promemoria_chiusura_mese", now.strftime("%Y-%m"), _month_close_reminders)
    if now.weekday() == 0:
        await _once(db, "riepilogo_settimanale", day, notifications.send_weekly_digests)
    if now.day == 1:
        await _once(db, "report_mensile", now.strftime("%Y-%m"), notifications.send_monthly_reports)


async def run_forever():
    while True:
        try:
            await tick(get_db())
        except Exception:  # noqa: BLE001
            logger.exception("Errore nello scheduler")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
