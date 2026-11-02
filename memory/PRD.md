# Nureal-Amministrazione (ex Tesoreria di gruppo) – PRD

## Problem statement
"importa app che ho caricato su questa Repo di GitHub https://github.com/alepiervi/tesoreria" — import, make it work, fix any errors.

## Architecture
FastAPI + MongoDB (motor) backend in /app/backend (routers in app/routers, services in app/services, integrations in app/integrations), React CRA + Tailwind frontend. Rules in /app/EMERGENT.md, docs in README.md.

## Done (2026-06)
- Created missing backend/.env (demo providers, SEED_DEMO=true, random JWT_SECRET) and frontend/.env (preview URL)
- Installed missing Python dependencies (et_xmlfile for openpyxl)
- 102 backend tests pass; smoke test of all GET endpoints for 3 roles (backend/tests/test_smoke_all_gets.py)
- Fix: Members page no longer calls /api/members for users who can't manage members

- Real-data mode: demo data wiped, SEED_DEMO=false, demo login hidden; owner now created via developer invite
- Renamed to Nureal-Amministrazione (UI, title, manifest, PDF, email subjects, 2FA issuer); guide texts/videos untouched
- First-use UX: owner welcome + '+ Crea la prima azienda' opens New company modal (/impostazioni?nuova=1); singular/plural fixes; empty chart axis
- Full first-use flow tested (company, manual account, CSV/CAMT/PDF import, invoice, deadline, reconciliation, invite)

- 2026-06: owner always sees every menu section (Layout allow()); 0-company owner gets "Crea prima la tua azienda" on gated pages; new Nureal logo (logo.png, favicon.png/.ico, icons, apple-touch) in login, sidebar, mobile header

- 2026-06: auto-logout after 15 min inactivity (frontend/src/lib/idle.js): shared across tabs, warning 60s before, checks on reopen, login notice

- 2026-06: Developer role (is_developer): former owner converted at startup (DEVELOPER_* env), zero company access (get_memberships/require block), menu limited to Stato del sistema, Errori tecnici (sanitized server+browser errors, collection system_errors), Invito titolare (owner invite -> is_owner + titolare on all companies)

- 2026-06: Mandatory 2FA at every login for all roles (REQUIRE_2FA_LOGIN): forced enrollment with setup_token, 10 single-use recovery codes, TOTP replay protection, code failures count toward lockout, owner can reset collaborators 2FA; invites never give a session; security headers; JWT_SECRET required; developer password only as bcrypt hash (DEVELOPER_PASSWORD_HASH); no passwords in code, README, memory or bundle; owners cannot modify other owners; new companies go to all owners

## Mocked (demo providers)
Open banking, SDI, payments, email, WhatsApp, AI assistant

## Backlog
- Guide screenshots/videos still show old 'Tesoreria di gruppo' branding (regenerate with tools/guida/cattura.py)
- P1: real open banking, real SDI, real payments with SCA, invite emails, S3 documents
- P2: accounting extensions (inventory, IVA per cassa, reverse charge, consolidation)
