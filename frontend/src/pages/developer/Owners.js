import { useCallback, useEffect, useState } from "react";
import { TempPasswordBox } from "../../components/PasswordTools";
import { Badge, Button, Card, ErrorBox, Field } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";

export function DevOwners() {
  const [owners, setOwners] = useState([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [temp, setTemp] = useState(null);

  const load = useCallback(() => {
    api.get("/developer/owners").then((r) => setOwners(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (key, fn) => {
    setBusy(key);
    setError("");
    try {
      await fn();
      load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const create = (e) => {
    e.preventDefault();
    run("create", async () => {
      const r = await api.post("/developer/owners", { email, name });
      setTemp(r.data);
      setEmail("");
      setName("");
    });
  };

  const reset = (o) => {
    if (!window.confirm(`Azzerare la password di ${o.email}? La verifica in due passaggi non cambia.`)) return;
    run(o.id, async () => setTemp((await api.post(`/developer/owners/${o.id}/reset-password`)).data));
  };

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title="Crea titolare con password provvisoria" subtitle="In alternativa al link: ricevi una password da comunicare, da cambiare al primo accesso">
        <form onSubmit={create} className="flex flex-col gap-4" data-testid="owner-create-form">
          <ErrorBox>{error}</ErrorBox>
          <Field label="Email del titolare" htmlFor="oc-email">
            <input id="oc-email" type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="owner-create-email" />
          </Field>
          <Field label="Nome" htmlFor="oc-name">
            <input id="oc-name" className="input" value={name} onChange={(e) => setName(e.target.value)} data-testid="owner-create-name" />
          </Field>
          <div><Button type="submit" loading={busy === "create"} data-testid="owner-create-submit">Crea titolare</Button></div>
        </form>
        {temp && <div className="mt-4"><TempPasswordBox email={temp.email} password={temp.temporary_password} onClose={() => setTemp(null)} /></div>}
      </Card>
      <Card title="Titolari" subtitle="Solo nome ed email: puoi azzerare la password, la verifica in due passaggi resta invariata">
        {owners.length === 0 ? <p className="text-sm text-muted">Nessun titolare ancora.</p> : (
          <ul className="divide-y divide-soft" data-testid="owners-list">
            {owners.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="flex-1">
                  <span className="font-semibold">{o.name || o.email}</span> <span className="text-muted">· {o.email}</span>
                </span>
                {o.must_change_password && <Badge tone="orange">password provvisoria</Badge>}
                {!o.active && <Badge tone="gray">disattivato</Badge>}
                {o.active && (
                  <Button variant="secondary" className="min-h-[36px]" loading={busy === o.id} onClick={() => reset(o)} data-testid={`owner-reset-password-${o.id}`}>
                    Azzera password
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
