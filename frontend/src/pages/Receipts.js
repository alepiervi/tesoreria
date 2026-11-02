import { useCallback, useEffect, useRef, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Amount, Badge, Button, Card, Empty, ErrorBox, Field, Loading, Modal, Notice, PageHeader, useToast } from "../components/ui";
import { api, downloadFile, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { eur, fmtDate } from "../lib/format";

export default function Receipts() {
  const [company, setCompany] = usePageCompany("view");
  const { can, refreshCounts } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(null);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const res = await api.get(`/companies/${company.id}/receipts`);
      setItems(res.data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);

  useEffect(() => {
    load();
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canUpload = can(company.id, "upload_documents");

  const upload = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    setError("");
    try {
      const res = await api.post(`/companies/${company.id}/receipts`, fd);
      setActive({ doc: res.data.document, candidates: res.data.candidates });
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <>
      <PageHeader title="Scontrini" subtitle="Fotografa uno scontrino: viene abbinato al pagamento con carta e archiviato per il commercialista"
        actions={<>
          <CompanyPicker value={company.id} onChange={setCompany} />
          {canUpload && (
            <>
              <input ref={fileRef} id="rc-file" type="file" accept="image/*,application/pdf" capture="environment" className="sr-only"
                onChange={(e) => upload(e.target.files?.[0])} />
              <Button loading={busy} onClick={() => fileRef.current?.click()}>Carica o fotografa</Button>
            </>
          )}
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : (
        <Card padded={false}>
          {items.length === 0 ? (
            <Empty title="Nessuno scontrino" text="Dal telefono puoi scattare la foto direttamente: data, totale ed esercente si compilano da soli se l'assistente è collegato a Claude." />
          ) : (
            <ul className="divide-y divide-soft">
              {items.map((d) => {
                const r = d.receipt || {};
                return (
                  <li key={d.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                    <span className="min-w-[200px] flex-1">
                      <span className="block font-semibold">{r.merchant || d.name}</span>
                      <span className="block text-xs text-muted">{r.date ? fmtDate(r.date, { year: true }) : "data da inserire"} · caricato da {d.uploaded_by_name}</span>
                    </span>
                    {r.total_cents ? <span className="num font-semibold">{eur(r.total_cents)}</span> : <Badge tone="orange">Importo da inserire</Badge>}
                    {r.transaction_id ? <Badge tone="blue">Abbinato</Badge> : <Badge tone="orange">Da abbinare</Badge>}
                    <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => downloadFile(`/documents/${d.id}/download`, null, d.name)}>Apri</Button>
                    {!r.transaction_id && canUpload && <Button variant="secondary" className="min-h-[40px]" onClick={() => setActive({ doc: d, candidates: null })}>Abbina</Button>}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      )}
      {active && <ReceiptModal state={active} onClose={() => setActive(null)} onDone={() => { setActive(null); toast("Scontrino abbinato al movimento"); load(); refreshCounts(); }} />}
    </>
  );
}

function ReceiptModal({ state, onClose, onDone }) {
  const r = state.doc.receipt || {};
  const [form, setForm] = useState({ date: r.date || "", total: r.total_cents ? (r.total_cents / 100).toFixed(2).replace(".", ",") : "", merchant: r.merchant || "" });
  const [candidates, setCandidates] = useState(state.candidates);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const search = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.put(`/receipts/${state.doc.id}`, form);
      setCandidates(res.data.candidates);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (state.candidates === null && r.total_cents && r.date) search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const link = async (txId) => {
    try {
      await api.post(`/receipts/${state.doc.id}/link`, { transaction_id: txId });
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <Modal open onClose={onClose} title="Abbina lo scontrino">
      <div className="flex flex-col gap-4">
        {r.read_automatically ? <Notice>Dati letti dallo scontrino: controllali prima di abbinare.</Notice>
          : <Notice>Inserisci data e totale: il programma cerca il pagamento con carta corrispondente.</Notice>}
        <ErrorBox>{error}</ErrorBox>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Data" htmlFor="rc-date"><input id="rc-date" type="date" className="input" value={form.date} onChange={set("date")} /></Field>
          <Field label="Totale (€)" htmlFor="rc-total"><input id="rc-total" inputMode="decimal" className="input" value={form.total} onChange={set("total")} /></Field>
          <div className="sm:col-span-2"><Field label="Esercente" htmlFor="rc-merchant"><input id="rc-merchant" className="input" value={form.merchant} onChange={set("merchant")} /></Field></div>
        </div>
        <div><Button variant="secondary" onClick={search} loading={busy} disabled={!form.date || !form.total}>Cerca il pagamento</Button></div>
        {candidates && (candidates.length === 0 ? (
          <p className="text-sm text-muted">Nessun pagamento da riconciliare con questo importo nei giorni vicini. Lo scontrino resta archiviato: potrai abbinarlo dopo il prossimo aggiornamento dei movimenti.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-soft rounded-lg border border-line">
            {candidates.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
                <span className="min-w-[160px] flex-1 text-sm">{t.description}<span className="block text-xs text-muted">{fmtDate(t.date, { year: true })}</span></span>
                <Amount cents={t.amount_cents} />
                <Button className="min-h-[40px]" onClick={() => link(t.id)}>Abbina</Button>
              </li>
            ))}
          </ul>
        ))}
      </div>
    </Modal>
  );
}
