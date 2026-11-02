import { useEffect, useState } from "react";
import { api, errorMessage } from "../lib/api";
import { Badge, Button, Card, ErrorBox, Field, Loading, Notice, useToast } from "./ui";

const ARUBA = { host: "smtps.aruba.it", port: 465, ssl: true };

export function EmailSettings({ onSaved }) {
  const toast = useToast();
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null);
  const [password, setPassword] = useState("");
  const [testTo, setTestTo] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const refresh = () => api.get("/settings/email").then((r) => setCfg(r.data)).catch(() => {});
  useEffect(() => {
    api.get("/settings/email").then((r) => {
      setCfg(r.data);
      setForm({ enabled: r.data.enabled || !r.data.has_password, host: r.data.host, port: r.data.port, ssl: r.data.ssl,
        user: r.data.user, from_addr: r.data.from_addr, from_name: r.data.from_name });
      setTestTo(r.data.from_addr || "");
    }).catch((e) => setError(errorMessage(e)));
  }, []);

  if (!form) return <Card title="Casella email per gli invii">{error ? <ErrorBox>{error}</ErrorBox> : <Loading />}</Card>;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const run = async (key, fn) => {
    setBusy(key);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const save = () => run("save", async () => {
    const r = await api.put("/settings/email", { ...form, port: Number(form.port), password: password || undefined });
    setCfg(r.data);
    setPassword("");
    toast("Casella email salvata");
    onSaved?.();
  });
  const test = () => run("test", async () => {
    try {
      await api.post("/settings/email/test", { to: testTo });
      toast(`Email di prova inviata a ${testTo}`);
    } finally {
      refresh();
    }
  });

  return (
    <Card title="Casella email per gli invii" subtitle="Solleciti, avvisi e inviti partono da questa casella (es. Aruba)"
      actions={<Badge tone={cfg.enabled && cfg.password_ok ? "green" : "orange"}>{cfg.enabled && cfg.password_ok ? "attiva" : "da configurare"}</Badge>}>
      <div className="flex flex-col gap-4" data-testid="email-settings">
        <ErrorBox>{error}</ErrorBox>
        {cfg.has_password && !cfg.password_ok && <Notice tone="orange">La password salvata non è più leggibile: inseriscila di nuovo.</Notice>}
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" className="min-h-[36px]" data-testid="email-aruba-preset"
            onClick={() => setForm({ ...form, ...ARUBA })}>Usa impostazioni Aruba</Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
          <Field label="Server di posta in uscita (SMTP)" htmlFor="smtp-host">
            <input id="smtp-host" className="input" value={form.host} onChange={set("host")} data-testid="email-host" />
          </Field>
          <Field label="Porta" htmlFor="smtp-port">
            <input id="smtp-port" type="number" className="input" value={form.port} onChange={set("port")} data-testid="email-port" />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.ssl} onChange={set("ssl")} data-testid="email-ssl" />
          Connessione protetta SSL (Aruba: porta 465 con SSL)
        </label>
        <Field label="Utente (di solito l'indirizzo email completo)" htmlFor="smtp-user">
          <input id="smtp-user" className="input" autoComplete="off" value={form.user} onChange={set("user")} data-testid="email-user" />
        </Field>
        <Field label="Password della casella" htmlFor="smtp-pass"
          hint={cfg.has_password ? "Già salvata e cifrata. Lascia vuoto per non cambiarla." : "Viene salvata cifrata e non si potrà più leggere."}>
          <input id="smtp-pass" type="password" className="input" autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} placeholder={cfg.has_password ? "••••••••" : ""} data-testid="email-password" />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Indirizzo mittente" htmlFor="smtp-from">
            <input id="smtp-from" type="email" className="input" value={form.from_addr} onChange={set("from_addr")} data-testid="email-from" />
          </Field>
          <Field label="Nome mittente" htmlFor="smtp-from-name">
            <input id="smtp-from-name" className="input" value={form.from_name} onChange={set("from_name")} data-testid="email-from-name" />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.enabled} onChange={set("enabled")} data-testid="email-enabled" />
          Invia davvero le email da questa casella
        </label>
        <div><Button loading={busy === "save"} onClick={save} data-testid="email-save">Salva</Button></div>
        <div className="flex flex-wrap items-end gap-2 border-t border-soft pt-4">
          <Field label="Manda un'email di prova a" htmlFor="smtp-test">
            <input id="smtp-test" type="email" className="input w-64" value={testTo} onChange={(e) => setTestTo(e.target.value)} data-testid="email-test-to" />
          </Field>
          <Button variant="secondary" loading={busy === "test"} disabled={!cfg.enabled || !cfg.password_ok || !testTo}
            onClick={test} data-testid="email-test-btn">Invia prova</Button>
        </div>
        {cfg.last_test && (
          <p className="text-xs text-muted" data-testid="email-last-test">
            Ultima prova: {new Date(cfg.last_test.at).toLocaleString("it-IT")} · {cfg.last_test.ok ? "riuscita" : "non riuscita"}
          </p>
        )}
      </div>
    </Card>
  );
}

export function SdiInfo() {
  return (
    <Card title="Fatture elettroniche (SDI)" subtitle="Come entrano ed escono le fatture">
      <div className="flex flex-col gap-3 text-sm" data-testid="sdi-info">
        <div className="flex items-center gap-2"><Badge tone="blue">manuale</Badge> Importi i file XML (anche .p7m o .zip) da Fatture → Importa XML.</div>
        <p className="text-muted">
          Puoi scaricarli dal Cassetto fiscale / Fatture e Corrispettivi dell'Agenzia delle Entrate o dal tuo gestionale.
          Quando avrai un intermediario SDI (Aruba, A-Cube, Openapi…), lo sviluppatore lo collega: comparirà il pulsante
          «Scarica da SDI» e le fatture arriveranno da sole.
        </p>
      </div>
    </Card>
  );
}
