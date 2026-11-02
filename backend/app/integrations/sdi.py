"""Fatturazione elettronica (Sistema di Interscambio).

Un provider reale è un intermediario accreditato che riceve le fatture passive
(tramite il codice destinatario dell'azienda) e invia quelle attive.
"""
import random
from abc import ABC, abstractmethod
from datetime import timedelta
from xml.sax.saxutils import escape

from ..config import settings
from ..utils import today


class SdiProvider(ABC):
    name = "base"

    @abstractmethod
    async def fetch_new_invoices(self, company: dict) -> list[str]:
        """Restituisce l'XML (FatturaPA) delle fatture ricevute non ancora scaricate."""


def build_fatturapa_xml(*, number: str, issue_date: str, total_cents: int, due_date: str,
                        seller_name: str, seller_vat: str, buyer_name: str, buyer_vat: str,
                        description: str = "Servizi", iban: str = "", withholding_cents: int = 0,
                        split_payment: bool = False) -> str:
    """Crea un XML FatturaPA semplificato ma valido nella struttura (usato da demo e test)."""
    taxable = round(total_cents / 1.22)
    vat = total_cents - taxable
    def eur(c):
        return f"{c / 100:.2f}"
    iban_xml = f"<IBAN>{escape(iban)}</IBAN>" if iban else ""
    ritenuta_xml = (f"<DatiRitenuta><TipoRitenuta>RT01</TipoRitenuta><ImportoRitenuta>{eur(withholding_cents)}</ImportoRitenuta>"
                    f"<AliquotaRitenuta>20.00</AliquotaRitenuta><CausalePagamento>A</CausalePagamento></DatiRitenuta>"
                    if withholding_cents else "")
    esig = "<EsigibilitaIVA>S</EsigibilitaIVA>" if split_payment else ""
    to_pay = total_cents - withholding_cents - (vat if split_payment else 0)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica versione="FPR12" xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
  <FatturaElettronicaHeader>
    <CedentePrestatore><DatiAnagrafici>
      <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>{escape(seller_vat)}</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>{escape(seller_name)}</Denominazione></Anagrafica>
    </DatiAnagrafici></CedentePrestatore>
    <CessionarioCommittente><DatiAnagrafici>
      <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>{escape(buyer_vat)}</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>{escape(buyer_name)}</Denominazione></Anagrafica>
    </DatiAnagrafici></CessionarioCommittente>
  </FatturaElettronicaHeader>
  <FatturaElettronicaBody>
    <DatiGenerali><DatiGeneraliDocumento>
      <TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa>
      <Data>{issue_date}</Data><Numero>{escape(number)}</Numero>
      {ritenuta_xml}<ImportoTotaleDocumento>{eur(total_cents)}</ImportoTotaleDocumento>
    </DatiGeneraliDocumento></DatiGenerali>
    <DatiBeniServizi>
      <DettaglioLinee><NumeroLinea>1</NumeroLinea><Descrizione>{escape(description)}</Descrizione>
        <PrezzoUnitario>{eur(taxable)}</PrezzoUnitario><PrezzoTotale>{eur(taxable)}</PrezzoTotale><AliquotaIVA>22.00</AliquotaIVA></DettaglioLinee>
      <DatiRiepilogo><AliquotaIVA>22.00</AliquotaIVA><ImponibileImporto>{eur(taxable)}</ImponibileImporto><Imposta>{eur(vat)}</Imposta>{esig}</DatiRiepilogo>
    </DatiBeniServizi>
    <DatiPagamento><CondizioniPagamento>TP02</CondizioniPagamento>
      <DettaglioPagamento><ModalitaPagamento>MP05</ModalitaPagamento>
        <DataScadenzaPagamento>{due_date}</DataScadenzaPagamento><ImportoPagamento>{eur(to_pay)}</ImportoPagamento>{iban_xml}
      </DettaglioPagamento>
    </DatiPagamento>
  </FatturaElettronicaBody>
</p:FatturaElettronica>"""


class DemoSdiProvider(SdiProvider):
    name = "demo"
    SUPPLIERS = [("Omega Srl", "01234567890"), ("Sigma Forniture Srl", "09876543210"),
                 ("Tau Logistica Spa", "11223344556")]

    async def fetch_new_invoices(self, company: dict) -> list[str]:
        rng = random.Random()
        name, vat = rng.choice(self.SUPPLIERS)
        issue = today() - timedelta(days=rng.randint(0, 5))
        return [build_fatturapa_xml(
            number=f"{rng.randint(100, 999)}/{issue.year}", issue_date=issue.isoformat(),
            total_cents=rng.randint(300, 6000) * 100, due_date=(issue + timedelta(days=30)).isoformat(),
            seller_name=name, seller_vat=vat, buyer_name=company["name"],
            buyer_vat=company.get("vat_number", ""), description="Fornitura materiali",
            iban="IT60X0542811101000000123456",
        )]


def get_sdi_provider() -> SdiProvider:
    providers = {"demo": DemoSdiProvider}
    cls = providers.get(settings.sdi_provider)
    if cls is None:
        raise RuntimeError(f"Provider SDI non configurato: {settings.sdi_provider}")
    return cls()
