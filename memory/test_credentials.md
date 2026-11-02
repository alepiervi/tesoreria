# Credenziali (dati veri, SEED_DEMO=false)
- Sviluppatore: alessandro.piervincenzi@gmail.com / Matteo20!!
  (is_developer=true, nessun accesso ai dati delle aziende; creato/convertito all'avvio da DEVELOPER_EMAIL/DEVELOPER_PASSWORD in backend/.env)
- Titolare: nessuno finché non viene accettato un invito creato da /sviluppatore/titolare
Login: POST /api/auth/login {email,password} -> access_token
Area sviluppatore API: GET /api/developer/status, GET /api/developer/errors, POST/GET/DELETE /api/developer/owner-invites
