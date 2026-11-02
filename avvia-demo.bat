@echo off
REM Avvia il programma in prova sul computer (Windows), con i dati di esempio in memoria.
REM Servono Python 3.11+ e Node.js 18+ installati. La prima volta ci vogliono alcuni minuti.
cd /d "%~dp0"
where python >nul 2>nul || (echo Manca Python: scaricalo da https://www.python.org/downloads/ e spunta "Add python.exe to PATH". & pause & exit /b 1)
where npm >nul 2>nul || (echo Manca Node.js: scaricalo da https://nodejs.org/ ^(versione LTS^). & pause & exit /b 1)

cd backend
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
echo Installo i componenti del backend...
pip install -q -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  powershell -Command "(Get-Content .env) -replace '^MONGO_URL=.*','MONGO_URL=mock://' -replace '^JWT_SECRET=.*','JWT_SECRET=prova-locale-%RANDOM%%RANDOM%%RANDOM%' | Set-Content .env"
)
start "Tesoreria - backend (non chiudere)" cmd /k ".venv\Scripts\activate && uvicorn server:app --port 8001"
cd ..\frontend
if not exist .env copy .env.example .env >nul
echo Installo i componenti del frontend (la prima volta ci vuole un po')...
if not exist node_modules call npm install --no-audit --no-fund
start "Tesoreria - frontend (non chiudere)" cmd /k "npm start"
echo.
echo Tra poco si apre il browser su http://localhost:3000
echo Accedi con titolare@demo.it  -  la password compare nella finestra del backend
echo Per chiudere il programma chiudi le due finestre nere.
pause
