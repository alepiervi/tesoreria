import { useCallback, useEffect, useState } from "react";
import CompanyPicker from "../components/CompanyPicker";
import NotesDrawer from "../components/NotesDrawer";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { fmtDateTime } from "../lib/format";

const TARGET_LABEL = { transaction: "Movimento", invoice: "Fattura", deadline: "Scadenza" };

export default function Questions() {
  const [companyId, setCompanyId] = useState("");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get("/questions", { params: { company_id: companyId || undefined } });
      setItems(res.data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <PageHeader title="Chiarimenti" subtitle="Domande aperte tra te, l'amministrazione e il commercialista"
        actions={<CompanyPicker value={companyId} onChange={setCompanyId} allowAll />} />
      <ErrorBox>{error}</ErrorBox>
      {!items ? <Loading /> : (
        <Card padded={false}>
          {items.length === 0 ? (
            <Empty title="Nessuna domanda aperta" text="Le richieste di chiarimento su movimenti, fatture e scadenze compaiono qui finché qualcuno non le segna come risolte." />
          ) : (
            <ul className="divide-y divide-line">
              {items.map((n) => (
                <li key={n.id} className="flex flex-wrap items-start gap-4 px-5 py-4">
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="flex flex-wrap items-center gap-2 text-xs text-muted">
                      <Badge>{n.company_name}</Badge>
                      <span>{TARGET_LABEL[n.target_type]}: {n.target_label}</span>
                    </span>
                    <p className="whitespace-pre-wrap text-sm">{n.text}</p>
                    <span className="text-xs text-muted">{n.author_name} · {fmtDateTime(n.created_at)}</span>
                  </div>
                  <Button variant="secondary" onClick={() => setOpen({ type: n.target_type, id: n.target_id, companyId: n.company_id, title: "Chiarimento", subtitle: `${TARGET_LABEL[n.target_type]}: ${n.target_label}` })}>
                    Rispondi
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
      <NotesDrawer target={open} onClose={() => setOpen(null)} onChanged={load} />
    </>
  );
}
