import { useCallback, useEffect, useState } from "react";
import { Amount, Badge, Button, Card, Empty, ErrorBox, Loading, Notice, PageHeader, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur, fmtDate } from "../lib/format";

export default function Intercompany() {
  const { refreshCounts, anyCan } = useAuth();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await api.get("/intercompany");
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const confirm = async (c) => {
    setBusy(c.out?.id || c.in?.id);
    try {
      await api.post("/intercompany/confirm", {
        tx_ids: [c.out?.id, c.in?.id].filter(Boolean),
        other_company_id: c.other_company_id || null,
      });
      toast(c.kind === "giroconto" ? "Giroconto registrato" : "Trasferimento tra aziende registrato");
      load();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  const auto = async () => {
    setBusy("auto");
    try {
      const res = await api.post("/intercompany/auto");
      toast(res.data.confirmed ? `${res.data.confirmed} trasferimenti registrati` : "Nessuna coppia abbastanza sicura");
      load();
      refreshCounts();
    } catch (e) {
      toast(errorMessage(e), "orange");
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <PageHeader title="Tra le aziende del gruppo" subtitle="Trasferimenti, giroconti e fatture interne: esclusi dai totali consolidati"
        actions={anyCan("reconcile") && <Button loading={busy === "auto"} onClick={auto}>Registra le coppie sicure</Button>} />
      <Notice>
        Un bonifico da un'azienda all'altra del gruppo non è né un costo né un ricavo: qui il programma li riconosce
        (stesso importo, date vicine, nome dell'altra azienda nella causale) e li tiene fuori dai totali della vista di gruppo.
      </Notice>
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <Card title="Da confermare" subtitle="Movimenti che sembrano trasferimenti interni">
            {data.candidates.length === 0 ? <p className="text-sm text-muted">Nessun movimento da confermare.</p> : (
              <ul className="divide-y divide-line">
                {data.candidates.map((c, n) => (
                  <li key={n} className="flex flex-col gap-3 py-4 lg:flex-row lg:items-center">
                    <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
                      {[["Esce da", c.out], ["Entra in", c.in]].map(([label, t]) => (
                        <div key={label} className="flex flex-col gap-0.5 rounded-lg bg-page p-3">
                          <span className="text-xs text-muted">{label}</span>
                          {t ? (
                            <>
                              <span className="text-sm font-semibold">{t.company_name}</span>
                              <span className="font-mono text-xs">{t.description}</span>
                              <span className="flex items-center gap-2 text-xs text-muted">{fmtDate(t.date, { year: true })} · <Amount cents={t.amount_cents} /></span>
                            </>
                          ) : (
                            <span className="text-sm">{c.other_company_name} <span className="text-xs text-muted">(movimento non presente: conto non collegato?)</span></span>
                          )}
                        </div>
                      ))}
                    </div>
                    <div className="flex flex-col gap-2 lg:w-[260px]">
                      <span className="flex flex-wrap gap-2">
                        <Badge tone={c.kind === "giroconto" ? "gray" : "blue"}>{c.kind === "giroconto" ? "Giroconto" : "Intercompany"}</Badge>
                        <Badge tone={c.score >= 85 ? "blue" : "orange"}>{c.score >= 85 ? "Molto probabile" : "Da verificare"}</Badge>
                      </span>
                      <span className="text-xs text-muted">{c.reasons.join(" · ")}</span>
                      {c.can_confirm && <Button loading={busy === (c.out?.id || c.in?.id)} onClick={() => confirm(c)}>Conferma</Button>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Trasferimenti netti" subtitle="Somma dei trasferimenti confermati, per coppia di aziende">
              {data.transfers.length === 0 ? <p className="text-sm text-muted">Nessun trasferimento registrato.</p> : (
                <ul className="divide-y divide-soft">
                  {data.transfers.map((t, n) => (
                    <li key={n} className="flex flex-col gap-1 py-3">
                      <span className="text-sm"><strong>{t.from_company}</strong> → <strong>{t.to_company}</strong></span>
                      <span className="flex flex-wrap justify-between gap-2 text-xs text-muted">
                        <span>Inviati {eur(t.sent_cents)}{t.returned_cents ? ` · restituiti ${eur(t.returned_cents)}` : ""}</span>
                        <span className="num text-sm font-bold text-ink">Netto {eur(t.net_cents)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Fatture aperte tra aziende" subtitle="Chi deve pagare chi dentro il gruppo">
              {data.open_invoices.length === 0 ? <p className="text-sm text-muted">Nessuna fattura interna da saldare.</p> : (
                <ul className="divide-y divide-soft">
                  {data.open_invoices.map((i) => (
                    <li key={i.invoice_id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                      <span className="text-sm"><strong>{i.debtor}</strong> deve a <strong>{i.creditor}</strong>
                        <span className="block text-xs text-muted">Fattura {i.number} · scadenza {fmtDate(i.due_date, { year: true })}</span></span>
                      <span className="num font-bold">{eur(i.residual_cents)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card title="Movimenti interni registrati" padded={false}>
            {data.movements.length === 0 ? <Empty title="Nessun movimento interno registrato" /> : (
              <div className="overflow-x-auto px-5 pb-4">
                <table className="w-full min-w-[640px] text-sm">
                  <thead><tr className="table-head text-left"><th className="py-2 pr-3">Data</th><th className="py-2 pr-3">Azienda</th><th className="py-2 pr-3">Descrizione</th><th className="py-2 pr-3">Con</th><th className="py-2 text-right">Importo</th></tr></thead>
                  <tbody>
                    {data.movements.map((m) => (
                      <tr key={m.id} className="border-b border-soft">
                        <td className="py-2 pr-3 text-muted">{fmtDate(m.date, { year: true })}</td>
                        <td className="py-2 pr-3">{m.company_name}</td>
                        <td className="py-2 pr-3">{m.description}</td>
                        <td className="py-2 pr-3 text-muted">{m.other_company_name}</td>
                        <td className="py-2 text-right"><Amount cents={m.amount_cents} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
