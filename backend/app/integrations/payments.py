"""Disposizione di pagamenti (bonifici).

Un provider reale richiede un servizio autorizzato PISP o un partner bancario.
Di solito il pagamento va confermato dall'utente con la SCA della banca
(il provider restituisce un link di conferma).
"""
import secrets
from abc import ABC, abstractmethod

from ..config import settings


class PaymentsProvider(ABC):
    name = "base"

    @abstractmethod
    async def send_transfer(self, account: dict, beneficiary: str, iban: str,
                            amount_cents: int, reference: str) -> dict:
        """Restituisce {'status': 'inviato'|'da_confermare', 'payment_ref': ..., 'confirm_url': ...}."""


class DemoPaymentsProvider(PaymentsProvider):
    name = "demo"

    async def send_transfer(self, account, beneficiary, iban, amount_cents, reference):
        return {"status": "inviato", "payment_ref": "DEMO-" + secrets.token_hex(5).upper(), "confirm_url": None}


def get_payments_provider() -> PaymentsProvider:
    providers = {"demo": DemoPaymentsProvider}
    cls = providers.get(settings.payments_provider)
    if cls is None:
        raise RuntimeError(f"Provider pagamenti non configurato: {settings.payments_provider}")
    return cls()
