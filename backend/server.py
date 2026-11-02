"""Nureal-Amministrazione — backend FastAPI.

Avvio in locale:  uvicorn server:app --reload --port 8001
Tutte le rotte sono sotto il prefisso /api (convenzione usata anche da Emergent).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import create_indexes
from app.routers import (
    accounting, assistant, audit_log, auth, banks, commissions, companies, control, dashboard, deadlines, documents, exports, intercompany, invoices,
    members, notes, notifications, operations, planning, receivables, transactions,
)
from app.seed import ensure_owner, seed_if_empty

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tesoreria")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.jwt_secret in {"dev-secret-change-me", "cambia-questa-chiave"} or len(settings.jwt_secret) < 32:
        logger.warning("JWT_SECRET è quello di esempio o troppo corto: impostane uno lungo e casuale nel file .env")
    await create_indexes()
    if settings.seed_demo and await seed_if_empty():
        logger.info("Caricati i dati di esempio (utente: titolare@demo.it).")
    if not settings.seed_demo and await ensure_owner(settings.owner_email, settings.owner_password, settings.owner_name):
        logger.info("Creato il titolare %s", settings.owner_email)
    if not settings.seed_demo and not settings.require_2fa_for_payments:
        logger.warning("REQUIRE_2FA_FOR_PAYMENTS=false con dati veri: i pagamenti si autorizzano con la sola password")
    task = None
    if settings.scheduler_enabled:
        import asyncio
        from app.services.scheduler import run_forever
        task = asyncio.create_task(run_forever())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Nureal-Amministrazione", version="0.1.0", lifespan=lifespan)

api = APIRouter(prefix="/api")


@api.get("/health")
async def health():
    return {"status": "ok"}


for module in (auth, companies, members, audit_log, banks, transactions, notes, invoices, deadlines,
               documents, dashboard, exports, intercompany, receivables, notifications, planning, assistant, accounting, control, operations, commissions):
    api.include_router(module.router)

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Serve al browser per leggere il nome dei file scaricati (export, XML, documenti)
    expose_headers=["Content-Disposition"],
)
