import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { Button, Field, Notice } from "./ui";

export function TotpSetup({ setup, onConfirm, busy, onCancel }) {
  const [code, setCode] = useState("");
  return (
    <form className="flex flex-col gap-4" data-testid="totp-setup"
      onSubmit={(e) => { e.preventDefault(); onConfirm(code); }}>
      <p className="text-sm">1. Inquadra il codice con un'app di autenticazione (Google Authenticator, Microsoft Authenticator, 1Password…).</p>
      <div className="w-fit rounded-xl border border-line bg-white p-3"><QRCodeSVG value={setup.otpauth_uri} size={164} /></div>
      <p className="text-xs text-muted">Oppure inserisci a mano questa chiave: <span className="break-all font-mono font-semibold text-ink" data-testid="totp-secret">{setup.secret}</span></p>
      <p className="text-sm">2. Scrivi il codice a 6 cifre che compare nell'app.</p>
      <Field label="Codice a 6 cifre" htmlFor="totp-setup-code">
        <input id="totp-setup-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required className="input w-40 text-lg tracking-[0.3em]"
          value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} data-testid="totp-setup-code" />
      </Field>
      <div className="flex gap-2">
        <Button type="submit" loading={busy} disabled={code.length !== 6} data-testid="totp-setup-confirm">Conferma</Button>
        {onCancel && <Button variant="secondary" onClick={onCancel}>Annulla</Button>}
      </div>
    </form>
  );
}

export function RecoveryCodes({ codes, onDone, doneLabel = "Ho salvato i codici" }) {
  const [saved, setSaved] = useState(false);
  const text = codes.join("\n");
  return (
    <div className="flex flex-col gap-4" data-testid="recovery-codes">
      <Notice tone="orange">
        Salva questi codici di recupero in un posto sicuro (non sul telefono). Ognuno funziona una sola volta,
        al posto del codice dell'app, se perdi il telefono. Non li mostreremo più.
      </Notice>
      <ul className="grid grid-cols-2 gap-2 rounded-xl border border-line bg-white p-4 font-mono text-sm" data-testid="recovery-codes-list">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => navigator.clipboard.writeText(text).catch(() => {})} data-testid="recovery-codes-copy">Copia</Button>
        <Button variant="secondary" data-testid="recovery-codes-download" onClick={() => {
          const a = document.createElement("a");
          a.href = URL.createObjectURL(new Blob([`Nureal-Amministrazione - codici di recupero\n\n${text}\n`], { type: "text/plain" }));
          a.download = "nureal-codici-recupero.txt";
          a.click();
        }}>Scarica</Button>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} data-testid="recovery-codes-saved" />
        Ho salvato i codici in un posto sicuro
      </label>
      <div><Button disabled={!saved} onClick={onDone} data-testid="recovery-codes-done">{doneLabel}</Button></div>
    </div>
  );
}
