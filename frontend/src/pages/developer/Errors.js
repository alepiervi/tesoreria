import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, useToast } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";

const when = (iso) => (iso ? new Date(iso).toLocaleString("it-IT") : "—");

function ErrorRow({ err, onResolve }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="py-3" data-testid={`dev-error-${err.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={err.source === "server" ? "blue" : "gray"}>{err.source === "server" ? "Server" : "Browser"}</Badge>
        <span className="font-semibold">{err.kind}</span>
        <span className="font-mono text-xs text-muted">{err.method} {err.where}</span>
        <span className="ml-auto text-xs text-muted">{err.count}× · ultima {when(err.last_at)}</span>
        {err.resolved ? <Badge tone="green">risolto</Badge> : (
          <Button variant="secondary" className="min-h-[36px]" data-testid={`dev-error-resolve-${err.id}`} onClick={() => onResolve(err.id)}>Segna risolto</Button>
        )}
      </div>
      <p className="mt-1 text-sm">{err.message}</p>
      {err.frames?.length > 0 && (
        <button type="button" className="mt-1 text-xs font-semibold text-accent underline" onClick={() => setOpen(!open)}>
          {open ? "Nascondi posizione nel codice" : "Mostra posizione nel codice"}
        </button>
      )}
      {open && <pre className="mt-2 overflow-x-auto rounded-lg bg-soft p-3 text-xs">{err.frames.join("\n")}</pre>}
    </li>
  );
}

export default function DevErrors() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const toast = useToast();
  const load = useCallback(() => {
    api.get("/developer/errors").then((r) => setItems(r.data)).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  const resolve = async (id) => {
    try {
      await api.post(`/developer/errors/${id}/resolve`);
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };
  const clear = async () => {
    await api.delete("/developer/errors");
    load();
  };

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!items) return <Loading />;
  return (
    <>
      <PageHeader title="Errori tecnici"
        subtitle="Tipo di errore e posizione nel codice. Messaggi che potrebbero contenere dati vengono nascosti; numeri, codici ed email sono oscurati."
        actions={items.some((e) => e.resolved) && <Button variant="secondary" data-testid="dev-errors-clear" onClick={clear}>Elimina i risolti</Button>} />
      <Card>
        {items.length === 0 ? (
          <Empty title="Nessun errore registrato" text="Quando qualcosa va storto nel server o nelle pagine, comparirà qui." />
        ) : (
          <ul className="divide-y divide-soft" data-testid="dev-errors-list">
            {items.map((e) => <ErrorRow key={e.id} err={e} onResolve={resolve} />)}
          </ul>
        )}
      </Card>
    </>
  );
}
