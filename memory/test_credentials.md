# Credenziali di test
Le password NON si scrivono in questo file (il repository può essere pubblico).
Vengono fornite di volta in volta dall'agente principale nel messaggio di test.

- Sviluppatore: alessandro.piervincenzi@gmail.com (is_developer=true, nessun accesso ai dati delle aziende)
  Creato all'avvio da DEVELOPER_EMAIL / DEVELOPER_PASSWORD_HASH (solo hash bcrypt) in backend/.env
- Titolare: nessuno finché non viene accettato un invito creato da /sviluppatore/titolare
- Verifica in due passaggi OBBLIGATORIA (REQUIRE_2FA_LOGIN=true): al primo accesso si attiva (QR + segreto, poi codice),
  poi a ogni accesso serve il codice a 6 cifre (o un codice di recupero, uso singolo). Nei test calcolare i codici con pyotp dal segreto mostrato.

API: POST /api/auth/login {email,password,totp_code?} -> {setup_required, setup_token} | 401 "2fa_required" | {access_token}
     POST /api/auth/2fa/enroll/start {setup_token} -> {secret, otpauth_uri}
     POST /api/auth/2fa/enroll/finish {setup_token, code} -> {access_token, recovery_codes[10]}
