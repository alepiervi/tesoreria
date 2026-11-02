import { QRCodeSVG } from "qrcode.react";
import { useCallback, useEffect, useState } from "react";
import CompanyPicker from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, Tabs, useToast } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { eur, fmtDate, fmtDateTime } from "../lib/format";

const BUCKET_TONE = { non_scaduto: "#8FA2EE", d0_30: "#F0B488", d31_60: "#E8772E", d61_90: "#C25A17", oltre_90: "#8A3A0B" };

export default function Receivables() {
  const [direction, setDirection] = useState("attiva");
  const [companyId, setCompanyId] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState({});
  const [remind, setRemind] = useState(null);
  const [contact, setContact] = useState(null);
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      const res = await api.get("/receivables", { params: { direction, company_id: companyId || undefined } });
      setData(res.data);
      setError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [direction, companyId]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  const isCredit = direction === "attiva";
  const total = data?.total_cents || 1;

  return (
    <>
      <PageHeader title="Crediti e debiti" subtitle="Chi deve soldi a chi, da quanto tempo, e chi paga in ritardo"
        actions={<CompanyPicker value={companyId} onChange={setCompanyId} allowAll />} />
      <Tabs value={direction} onChange={setDirection}
        tabs={[{ id: "attiva", label: "Crediti verso clienti" }, { id: "passiva", label: "Debiti verso fornitori" }]} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <>
          <Card title={isCredit ? "Da incassare, per anzianità" : "Da pagare, per anzianità"}
            subtitle={`Totale ${eur(data.total_cents)} · scaduto ${eur(data.overdue_cents)} · esclusi i rapporti tra aziende del gruppo`}>
            <div className="flex h-4 w-full overflow-hidden rounded-full bg-soft" role="img"
              aria-label={data.buckets.map((b) => `${b.label}: ${eur(b.amount_cents)}`).join("; ")}>
              {data.buckets.map((b) => b.amount_cents > 0 && (
                <div key={b.id} style={{ width: `${(b.amount_cents / total) * 100}%`, background: BUCKET_TONE[b.id] }} />
              ))}
            </div>
            <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
              {data.buckets.map((b) => (
                <div key={b.id} className="flex flex-col gap-1">
                  <span className="flex items-center gap-2 text-xs text-muted">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: BUCKET_TONE[b.id] }} aria-hidden="true" />{b.label}
                  </span>
                  <span className="num text-lg font-bold">{eur(b.amount_cents)}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card padded={false}>
            {data.parties.length === 0 ? <Empty title={isCredit ? "Nessun credito aperto" : "Nessun debito aperto"} /> : (
              <ul className="divide-y divide-line">
                {data.parties.map((p) => (
                  <li key={p.key} className="px-5 py-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <button type="button" onClick={() => setOpen((o) => ({ ...o, [p.key]: !o[p.key] }))} aria-expanded={Boolean(open[p.key])}
                        className="flex min-h-[44px] min-w-[220px] flex-1 flex-col items-start text-left">
                        <span className="font-semibold">{p.name}</span>
                        <span className="text-xs text-muted">{p.company_name}{p.vat ? ` · P.IVA ${p.vat}` : ""} · {p.invoices.length} {p.invoices.length === 1 ? "fattura aperta" : "fatture aperte"}</span>
                      </button>
                      {p.max_overdue_days > 0 && <Badge tone="orange">Scaduto da {p.max_overdue_days} giorni</Badge>}
                      {isCredit && p.avg_delay_days !== null && (
                        <Badge tone={p.late_payer ? "orange" : "blue"}>
                          {p.avg_delay_days > 0 ? `Paga in media ${p.avg_delay_days} gg in ritardo` : "Paga puntuale"}
                        </Badge>
                      )}
                      <span className={`num w-32 text-right font-bold ${isCredit ? "" : "text-warn-amount"}`}>{eur(p.open_cents)}</span>
                    </div>
                    {open[p.key] && (
                      <div className="mt-3 flex flex-col gap-3">
                        {isCredit && (
                          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
                            <span>Email per i solleciti: <strong className="text-ink">{p.email || "non indicata"}</strong></span>
                            {p.can_remind && <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => setContact(p)}>Modifica</Button>}
                          </div>
                        )}
                        <div className="overflow-x-auto">
                          <table className="w-full min-w-[640px] text-sm">
                            <thead><tr className="table-head text-left">
                              <th className="py-2 pr-3">Fattura</th><th className="py-2 pr-3">Scadenza</th>
                              <th className="py-2 pr-3 text-right">Da {isCredit ? "incassare" : "pagare"}</th>
                              {isCredit && <th className="py-2 pr-3">Solleciti</th>}<th />
                            </tr></thead>
                            <tbody>
                              {p.invoices.map((i) => (
                                <tr key={i.id} className="border-b border-soft">
                                  <td className="py-2 pr-3 font-semibold">{i.number}<span className="block text-xs font-normal text-muted">del {fmtDate(i.date, { year: true })}</span></td>
                                  <td className="py-2 pr-3">{fmtDate(i.due_date, { year: true })}{i.days_overdue > 0 && <span className="block text-xs text-warn-text">scaduta da {i.days_overdue} gg</span>}</td>
                                  <td className="num py-2 pr-3 text-right font-semibold">{eur(i.residual_cents)}</td>
                                  {isCredit && <td className="py-2 pr-3 text-xs text-muted">{i.reminders_count ? `${i.reminders_count} · ultimo ${fmtDateTime(i.last_reminder_at)}` : "Nessuno"}</td>}
                                  <td className="py-2 text-right">
                                    {isCredit && p.can_remind && i.days_overdue > 0 && (
                                      <Button variant="secondary" className="min-h-[40px]" onClick={() => setRemind({ invoice: i, party: p })}>
                                        {i.reminders_count ? "Nuovo sollecito" : "Sollecita"}
                                      </Button>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
      <ReminderModal target={remind} onClose={() => setRemind(null)} onDone={(s) => { setRemind(null); toast(s === "demo" ? "Sollecito pronto (modalità prova: visibile in Impostazioni → Casella di prova)" : "Sollecito inviato"); load(); }} />
      <ContactModal party={contact} onClose={() => setContact(null)} onDone={() => { setContact(null); toast("Contatto salvato"); load(); }} />
    </>
  );
}

function ReminderModal({ target, onClose, onDone }) {
  const [draft, setDraft] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadDraft = useCallback(async (level) => {
    if (!target) return;
    try {
      const res = await api.get(`/invoices/${target.invoice.id}/reminder-draft`, { params: { level } });
      setDraft(res.data);
      setForm((f) => ({ to: f?.to || res.data.to, subject: res.data.subject, body: res.data.body, level: res.data.level, attach_xml: res.data.has_xml,
        attach_qr: f ? f.attach_qr : Boolean(res.data.qr_payload) }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [target]);

  useEffect(() => {
    setDraft(null);
    setForm(null);
    setError("");
    loadDraft();
  }, [loadDraft]);

  if (!target) return null;
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const send = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/invoices/${target.invoice.id}/reminder`, { ...form, level: Number(form.level), save_email: true });
      onDone(res.data.status);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open wide onClose={onClose} title={`Sollecito a ${target.party.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={send} loading={busy} disabled={!form?.to}>Invia sollecito</Button></>}>
      {!form ? <Loading /> : (
        <div className="flex flex-col gap-4">
          <ErrorBox>{error}</ErrorBox>
          {draft.previous.length > 0 && (
            <Notice>Solleciti già inviati: {draft.previous.map((r) => `${fmtDateTime(r.at)} (livello ${r.level})`).join(", ")}</Notice>
          )}
          <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
            <Field label="Destinatario" htmlFor="rm-to"><input id="rm-to" type="email" className="input" value={form.to} onChange={set("to")} placeholder="amministrazione@cliente.it" /></Field>
            <Field label="Tono" htmlFor="rm-level">
              <select id="rm-level" className="input" value={form.level} onChange={(e) => loadDraft(Number(e.target.value))}>
                <option value={1}>1 · Promemoria cortese</option>
                <option value={2}>2 · Sollecito</option>
                <option value={3}>3 · Ultimo avviso</option>
              </select>
            </Field>
          </div>
          <Field label="Oggetto" htmlFor="rm-subj"><input id="rm-subj" className="input" value={form.subject} onChange={set("subject")} /></Field>
          <Field label="Testo" htmlFor="rm-body"><textarea id="rm-body" rows={12} className="input py-2 leading-relaxed" value={form.body} onChange={set("body")} /></Field>
          {draft.has_xml && (
            <label className="flex min-h-[44px] items-center gap-2 text-sm">
              <input type="checkbox" className="h-[18px] w-[18px]" checked={form.attach_xml} onChange={set("attach_xml")} /> Allega la fattura elettronica (XML)
            </label>
          )}
          {draft.qr_payload ? (
            <div className="flex flex-wrap items-center gap-4 rounded-lg border border-line p-3">
              <div className="rounded bg-white p-1.5"><QRCodeSVG value={draft.qr_payload} size={96} level="M" /></div>
              <div className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
                <label className="flex items-center gap-2 font-semibold">
                  <input type="checkbox" className="h-[18px] w-[18px]" checked={form.attach_qr} onChange={set("attach_qr")} /> Allega l'avviso di pagamento con QR code
                </label>
                <span className="text-xs text-muted">Il cliente lo inquadra con l'app della banca e trova il bonifico già compilato: {eur(draft.amount_cents)} su {draft.iban}.</span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted">Per allegare il QR code di pagamento serve un conto con IBAN attivo.</p>
          )}
        </div>
      )}
    </Modal>
  );
}

function ContactModal({ party, onClose, onDone }) {
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (party) { setEmail(party.email || ""); setPhone(party.phone || ""); setError(""); }
  }, [party]);
  if (!party) return null;
  const save = async () => {
    try {
      await api.put(`/companies/${party.company_id}/contacts`, { vat: party.vat, name: party.name, email, phone });
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <Modal open onClose={onClose} title={`Contatti di ${party.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></>}>
      <div className="flex flex-col gap-4">
        <ErrorBox>{error}</ErrorBox>
        <Field label="Email amministrazione" htmlFor="ct-email"><input id="ct-email" type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Telefono" htmlFor="ct-phone"><input id="ct-phone" className="input" value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
