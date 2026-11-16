import { useEffect, useState } from "react";
import { Badge, Button, ErrorBox, Loading, Modal, Notice } from "./ui";
import { api, errorMessage } from "../lib/api";
import { fmtDate } from "../lib/format";

const ZIP_STEPS = [
  "Entra in «Fatture e Corrispettivi» sul sito dell'Agenzia delle Entrate (con SPID, CIE o CNS).",
  "Vai su «Consultazione» → «Fatture elettroniche e altri dati IVA» → «Fatture ricevute» (o «emesse»).",
  "Scegli il periodo (massimo 3 mesi alla volta), seleziona tutte le fatture e premi «Download massivo» o «Scarica file».",
  "Qui premi «Importa XML o ZIP» e scegli il file ZIP scaricato: le fatture già presenti non vengono duplicate.",
];

const DELEGA_STEPS = [
  "Il legale rappresentante entra in «Fatture e Corrispettivi» e conferisce la delega ad A-Cube per il servizio di consultazione e download delle fatture elettroniche.",
  "Premi qui sotto «Attiva scarico automatico»: l'azienda viene registrata su A-Cube con la sua partita IVA.",
  "Ogni notte A-Cube scarica le fatture nuove; con «Scarica dal cassetto» le trovi qui (le fatture arrivano nel cassetto fino a 72 ore dopo l'invio).",
];

function Steps({ items, testid }) {
  return (
    <ol className="flex flex-col gap-2 text-sm" data-testid={testid}>
      {items.map((t, i) => (
        <li key={t} className="flex gap-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-page text-xs font-bold">{i + 1}</span>
          <span>{t}</span>
        </li>
      ))}
    </ol>
  );
}

/** Come far arrivare le fatture dal cassetto fiscale: ZIP subito, scarico automatico con A-Cube. */
export function CassettoModal({ open, company, onClose, onActivated }) {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !company) return;
    setInfo(null);
    setError("");
    api.get(`/companies/${company.id}/cassetto`).then((r) => setInfo(r.data)).catch((e) => setError(errorMessage(e)));
  }, [open, company]);

  if (!open) return null;

  const activate = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/companies/${company.id}/cassetto/activate`);
      setInfo((i) => ({ ...i, ...res.data }));
      onActivated?.();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const acube = info?.provider === "acube";
  return (
    <Modal open wide onClose={onClose} title={`Cassetto fiscale · ${company?.name || ""}`}
      footer={<Button variant="secondary" onClick={onClose}>Chiudi</Button>}>
      <div className="flex flex-col gap-5" data-testid="cassetto-modal">
        <ErrorBox>{error}</ErrorBox>
        {!info && !error ? <Loading /> : (
          <>
            <section className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold">Scarico automatico</h3>
                {acube
                  ? (info.scheduled ? <Badge tone="green">Attivo</Badge> : <Badge tone="orange">Da attivare</Badge>)
                  : <Badge>Non ancora collegato</Badge>}
              </div>
              {acube ? (
                <>
                  <Steps items={DELEGA_STEPS} testid="cassetto-delega-steps" />
                  {info.error && <Notice tone="orange">{info.error}</Notice>}
                  {info.last_sync && <p className="text-xs text-muted">Ultimo scarico: {fmtDate(info.last_sync.slice(0, 10), { year: true })}</p>}
                  <div>
                    <Button loading={busy} onClick={activate} data-testid="cassetto-activate">
                      {info.scheduled ? "Riattiva scarico automatico" : "Attiva scarico automatico"}
                    </Button>
                  </div>
                </>
              ) : (
                <Notice>
                  Per lo scarico automatico serve un intermediario accreditato: usiamo A-Cube. Sottoscrivete il servizio «Download cassetto fiscale» su acubeapi.com poi avvisatemi: vi chiederò email e password dell'account A-Cube in un riquadro sicuro e qui comparirà il tasto per attivarlo.
                </Notice>
              )}
            </section>
            <section className="flex flex-col gap-3">
              <h3 className="text-base font-semibold">Caricamento del file ZIP (sempre disponibile)</h3>
              <Steps items={ZIP_STEPS} testid="cassetto-zip-steps" />
            </section>
          </>
        )}
      </div>
    </Modal>
  );
}
