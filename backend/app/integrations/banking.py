"""Open banking (lettura saldi e movimenti).

Interfaccia da implementare per un provider reale autorizzato PSD2
(es. un aggregatore open banking). Il flusso reale tipico è:
  1. start_connection -> restituisce un link alla pagina di consenso della banca
  2. l'utente autorizza, il provider richiama il nostro callback
  3. complete_connection -> restituisce i conti autorizzati
  4. fetch_transactions / fetch_balance a ogni sincronizzazione
Il consenso PSD2 di norma dura 180 giorni e va rinnovato.
"""
import hashlib
import random
from abc import ABC, abstractmethod
from datetime import date, timedelta

from ..config import settings
from ..utils import today

CONSENT_DAYS = 180


class BankingProvider(ABC):
    name = "base"

    @abstractmethod
    async def start_connection(self, company: dict, bank_name: str) -> dict:
        """Avvia il collegamento. Restituisce {'redirect_url': ...} oppure {'accounts': [...]}."""

    @abstractmethod
    async def fetch_transactions(self, account: dict, since: date) -> list[dict]:
        """Movimenti dal giorno 'since' a oggi.
        Ogni movimento: external_id, date (YYYY-MM-DD), description, amount_cents (+ entrata, - uscita), counterparty."""

    @abstractmethod
    async def fetch_balance(self, account: dict) -> int:
        """Saldo attuale in centesimi."""


DEMO_PATTERNS = [
    ("Bonifico da {cliente} saldo fattura", (1500, 18000), +1),
    ("Incassi POS", (300, 3500), +1),
    ("Bonifico a {fornitore}", (400, 9500), -1),
    ("Addebito SDD fornitura energia", (600, 2200), -1),
    ("Pagamento carta - carburante", (40, 180), -1),
    ("Commissioni bancarie", (5, 35), -1),
    ("Canone software gestionale", (60, 240), -1),
]
DEMO_CLIENTI = ["Delta Spa", "Kappa Srl", "Studio Lambda", "Omicron Srl", "Rho Trasporti"]
DEMO_FORNITORI = ["Omega Srl", "Sigma Forniture", "Tau Logistica", "Ypsilon Servizi"]


class DemoBankingProvider(BankingProvider):
    """Simula una banca: genera movimenti plausibili e sempre uguali per lo stesso conto e giorno."""
    name = "demo"

    async def start_connection(self, company: dict, bank_name: str) -> dict:
        seed = int(hashlib.sha256(f"{company['id']}{bank_name}{random.random()}".encode()).hexdigest(), 16)
        rng = random.Random(seed)
        iban = "IT" + "".join(str(rng.randint(0, 9)) for _ in range(2)) + "X" + \
               "".join(str(rng.randint(0, 9)) for _ in range(22))
        return {"accounts": [{
            "external_id": f"demo-{seed % 10**12}",
            "bank_name": bank_name,
            "label": "Conto corrente",
            "iban": iban,
            "balance_cents": rng.randint(15_000, 90_000) * 100,
            "consent_expires_at": (today() + timedelta(days=CONSENT_DAYS)).isoformat(),
        }]}

    async def fetch_transactions(self, account: dict, since: date) -> list[dict]:
        out = []
        day = since
        end = today()
        while day <= end:
            rng = random.Random(f"{account['external_id']}-{day.isoformat()}")
            if day.weekday() < 5:
                for i in range(rng.choice([0, 0, 1, 1, 2])):
                    pattern, (lo, hi), sign = rng.choice(DEMO_PATTERNS)
                    desc = pattern.format(cliente=rng.choice(DEMO_CLIENTI), fornitore=rng.choice(DEMO_FORNITORI))
                    out.append({
                        "external_id": f"{account['external_id']}-{day.isoformat()}-{i}",
                        "date": day.isoformat(),
                        "description": desc,
                        "amount_cents": sign * rng.randint(lo * 100, hi * 100),
                        "counterparty": "",
                    })
            day += timedelta(days=1)
        return out

    async def fetch_balance(self, account: dict) -> int:
        return account.get("balance_cents", 0)


def get_banking_provider() -> BankingProvider | None:
    if settings.banking_provider == "none":
        return None
    providers = {"demo": DemoBankingProvider}
    cls = providers.get(settings.banking_provider)
    if cls is None:
        raise RuntimeError(f"Provider bancario non configurato: {settings.banking_provider}")
    return cls()
