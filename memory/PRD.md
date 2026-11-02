# Tesoreria di gruppo – PRD

## Problem statement
"importa app che ho caricato su questa Repo di GitHub https://github.com/alepiervi/tesoreria" — import, make it work, fix any errors.

## Architecture
FastAPI + MongoDB (motor) backend in /app/backend (routers in app/routers, services in app/services, integrations in app/integrations), React CRA + Tailwind frontend. Rules in /app/EMERGENT.md, docs in README.md.

## Done (2026-06)
- Created missing backend/.env (demo providers, SEED_DEMO=true, random JWT_SECRET) and frontend/.env (preview URL)
- Installed missing Python dependencies (et_xmlfile for openpyxl)
- 102 backend tests pass; smoke test of all GET endpoints for 3 roles (backend/tests/test_smoke_all_gets.py)
- Fix: Members page no longer calls /api/members for users who can't manage members

## Mocked (demo providers)
Open banking, SDI, payments, email, WhatsApp, AI assistant

## Backlog
- P1: real open banking, real SDI, real payments with SCA, invite emails, S3 documents
- P2: accounting extensions (inventory, IVA per cassa, reverse charge, consolidation)
