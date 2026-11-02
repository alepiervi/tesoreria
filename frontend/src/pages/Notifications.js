import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import { fmtDateTime } from "../lib/format";

const KIND = {
  scadenza: "Scadenza", crediti: "Crediti", previsione: "Previsione", consenso: "Banca", estratto_conto: "Estratto conto",
  budget: "Budget", chiarimento: "Chiarimento", pagamento: "Pagamento",
};

export default function Notifications() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await api.get("/notifications", { params: { limit: 100 } });
      setData(res.data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const changed = () => window.dispatchEvent(new Event("notifications-changed"));
  const readAll = async () => {
    await api.post("/notifications/read-all");
    await load();
    changed();
  };
  const open = async (n) => {
    if (!n.read_at) {
      await api.post(`/notifications/${n.id}/read`).catch(() => {});
      changed();
    }
  };

  return (
    <>
      <PageHeader title="Notifiche" subtitle="Avvisi su scadenze, crediti, liquidità, banche e chiarimenti"
        actions={<>
          {data?.unread > 0 && <Button variant="secondary" onClick={readAll}>Segna tutte come lette</Button>}
          <Link to="/impostazioni#notifiche" className="text-sm font-semibold text-accent">Scegli come riceverle →</Link>
        </>} />
      <ErrorBox>{error}</ErrorBox>
      {!data ? <Loading /> : (
        <Card padded={false}>
          {data.items.length === 0 ? (
            <Empty title="Nessuna notifica" text="Ogni mattina il programma controlla scadenze, crediti, previsione di cassa, budget e conti bancari, e ti avvisa qui." />
          ) : (
            <ul className="divide-y divide-line">
              {data.items.map((n) => (
                <li key={n.id} className={n.read_at ? "" : "bg-accent-soft/40"}>
                  <Link to={n.link || "/"} onClick={() => open(n)} className="flex flex-wrap items-start gap-3 px-5 py-4 hover:bg-page">
                    <span className={`mt-1.5 h-2.5 w-2.5 flex-none rounded-full ${n.read_at ? "bg-transparent" : "bg-accent"}`} aria-hidden="true" />
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{n.title}</span>
                        <Badge tone={n.important ? "orange" : "gray"}>{KIND[n.kind] || n.kind}</Badge>
                        {!n.read_at && <span className="sr-only">(da leggere)</span>}
                      </span>
                      <span className="text-sm text-muted">{n.body}</span>
                    </span>
                    <span className="text-xs text-muted">{fmtDateTime(n.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </>
  );
}
