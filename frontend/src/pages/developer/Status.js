import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, ErrorBox, Loading, Notice, PageHeader, Stat } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";

function uptime(sec) {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return d ? `${d} g ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}

const when = (iso) => (iso ? new Date(iso).toLocaleString("it-IT") : "—");

export default function DevStatus() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api.get("/developer/status").then((r) => setData(r.data)).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  if (error) return <ErrorBox>{error}</ErrorBox>;
  if (!data) return <Loading />;
  return (
    <>
      <PageHeader title="Stato del sistema" subtitle="Solo informazioni tecniche: nessun dato delle aziende è visibile da questo account" />
      {!data.titolare_presente && (
        <Notice tone="orange">Non c'è ancora un titolare. <Link className="font-semibold underline" to="/sviluppatore/titolare">Crea il link di invito</Link>.</Notice>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="dev-status-stats">
        <Stat label="Database" value={data.database.ok ? "Raggiungibile" : "Non raggiungibile"} sub={`${data.database.ping_ms} ms`} tone={data.database.ok ? undefined : "warn"} />
        <Stat label="Server attivo da" value={uptime(data.uptime_seconds)} sub={`Python ${data.python}`} />
        <Stat label="Errori aperti" value={data.errori.aperti} sub={`${data.errori.ultime_24h} nelle ultime 24 ore`} tone={data.errori.aperti ? "warn" : undefined} />
        <Stat label="Titolare" value={data.titolare_presente ? "Presente" : "Da invitare"} tone={data.titolare_presente ? undefined : "warn"} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Servizi collegati" subtitle="«demo» = modalità prova, nessun invio reale">
          <ul className="divide-y divide-soft" data-testid="dev-providers">
            {Object.entries(data.providers).map(([k, v]) => (
              <li key={k} className="flex items-center justify-between py-2 text-sm">
                <span className="capitalize">{k}</span>
                <Badge tone={v === "demo" ? "orange" : "green"}>{v}</Badge>
              </li>
            ))}
            <li className="flex items-center justify-between py-2 text-sm">
              <span>Verifica in due passaggi per i pagamenti</span>
              <Badge tone={data.sicurezza["2fa_per_pagamenti"] ? "green" : "orange"}>{data.sicurezza["2fa_per_pagamenti"] ? "obbligatoria" : "non richiesta"}</Badge>
            </li>
          </ul>
        </Card>
        <Card title="Attività automatiche" subtitle={data.scheduler.attivo ? "Pianificatore attivo" : "Pianificatore spento"}>
          {data.scheduler.attivita.length === 0 ? (
            <p className="text-sm text-muted">Nessuna attività eseguita finora.</p>
          ) : (
            <ul className="divide-y divide-soft" data-testid="dev-jobs">
              {data.scheduler.attivita.map((j) => (
                <li key={j.nome} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <span className="font-medium">{j.nome}</span>
                  <span className="text-muted">{when(j.fine || j.inizio)}</span>
                  <Badge tone={j.esito === "ok" ? "green" : j.esito === "errore" ? "orange" : "gray"}>{j.esito}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
