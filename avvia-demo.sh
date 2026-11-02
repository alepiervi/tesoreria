#!/bin/bash
# Avvia il programma in prova sul computer (Mac o Linux), con i dati di esempio in memoria.
# Servono Python 3.11+ e Node.js 18+ installati. La prima volta ci vogliono alcuni minuti.
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Manca Python: scaricalo da https://www.python.org/downloads/"; exit 1; }
command -v npm >/dev/null || { echo "Manca Node.js: scaricalo da https://nodejs.org/ (versione LTS)"; exit 1; }

cd backend
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
echo "Installo i componenti del backend..."
pip install -q -r requirements.txt
if [ ! -f .env ]; then
  sed -e "s#^MONGO_URL=.*#MONGO_URL=mock://#" -e "s#^JWT_SECRET=.*#JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')#" .env.example > .env
fi
uvicorn server:app --port 8001 &
BACK=$!
cd ../frontend
[ -f .env ] || cp .env.example .env
echo "Installo i componenti del frontend (la prima volta ci vuole un po')..."
[ -d node_modules ] || npm install --no-audit --no-fund
trap "kill $BACK 2>/dev/null" EXIT
echo
echo "Tra poco si apre il browser su http://localhost:3000"
echo "Accedi con titolare@demo.it - la password compare nella finestra del backend"
echo "Per chiudere il programma premi Ctrl+C in questa finestra."
npm start
