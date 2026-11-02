"""Nureal-Amministrazione — backend FastAPI.

Avvio in locale:  uvicorn server:app --reload --port 8001
Tutte le rotte sono sotto il prefisso /api (convenzione usata anche da Emergent).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import create_indexes
from app.routers import (
    accounting, assistant, audit_log, auth, banks, commissions, companies, control, dashboard, deadlines, documents, exports, intercompany, invoices,
    members, notes, notifications, operations, planning, receivables, transactions,
)
from app.seed import DEMO_PASSWORD, DEMO_PASSWORD_GENERATED, ensure_developer, seed_if_empty
from app.routers import app_settings, developer
from app.services.errors import record_server_error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tesoreria")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.jwt_secret in {"dev-secret-change-me", "cambia-questa-chiave"} or len(settings.jwt_secret) < 32:
        logger.warning("JWT_SECRET è quello di esempio o troppo corto: impostane uno lungo e casuale nel file .env")
    await create_indexes()
    if settings.seed_demo and await seed_if_empty():
        logger.info("Caricati i dati di esempio (utente: titolare@demo.it).")
        if DEMO_PASSWORD_GENERATED:
            print(f"Password degli utenti demo (solo per questa prova in locale): {DEMO_PASSWORD}", flush=True)
    if not settings.seed_demo:
        dev = await ensure_developer(settings.developer_email, settings.developer_password_hash, settings.developer_name)
        if dev:
            logger.info("Account sviluppatore %s: %s", settings.developer_email, dev)
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
               documents, dashboard, exports, intercompany, receivables, notifications, planning, assistant, accounting, control, operations, commissions,
               developer, app_settings):
    api.include_router(module.router)

app.include_router(api)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("Errore non gestito su %s", request.url.path)
    await record_server_error(request, exc)
    return JSONResponse(status_code=500, content={"detail": "Errore interno. Il problema è stato registrato per lo sviluppatore."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # Serve al browser per leggere il nome dei file scaricati (export, XML, documenti)
    expose_headers=["Content-Disposition"],
)
