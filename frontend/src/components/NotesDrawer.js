import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime } from "../lib/format";
import { Badge, Button, ErrorBox, Loading, Modal } from "./ui";

/** Conversazione (note e richieste di chiarimento) su un movimento, una fattura o una scadenza. */
export default function NotesDrawer({ target, onClose, onChanged }) {
  const { can, refreshCounts } = useAuth();
  const [notes, setNotes] = useState(null);
  const [text, setText] = useState("");
  const [isQuestion, setIsQuestion] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!target) return;
    try {
      const res = await api.get("/notes", { params: { target_type: target.type, target_id: target.id } });
      setNotes(res.data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [target]);

  useEffect(() => {
    setNotes(null);
    setText("");
    setIsQuestion(false);
    setError("");
    load();
  }, [load]);

  if (!target) return null;
  const canWrite = can(target.companyId, "note");

  const send = async () => {
    if (!text.trim()) return;
    setSaving(true);
    setError("");
    try {
      await api.post("/notes", { target_type: target.type, target_id: target.id, text, is_question: isQuestion });
      setText("");
      setIsQuestion(false);
      await load();
      refreshCounts();
      onChanged?.();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const resolve = async (id) => {
    try {
      await api.post(`/notes/${id}/resolve`);
      await load();
      refreshCounts();
      onChanged?.();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <Modal open onClose={onClose} title={target.title || "Note"}>
      <div className="flex flex-col gap-4">
        {target.subtitle && <p className="text-sm text-muted">{target.subtitle}</p>}
        <ErrorBox>{error}</ErrorBox>
        {notes === null ? (
          <Loading />
        ) : notes.length === 0 ? (
          <p className="text-sm text-muted">Nessuna nota. Scrivi la prima qui sotto.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {notes.map((n) => (
              <li key={n.id} className="rounded-lg border border-line p-3">
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{n.author_name}</span>
                  <span className="text-xs text-muted">{fmtDateTime(n.created_at)}</span>
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{n.text}</p>
                {n.is_question && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Badge tone={n.resolved ? "blue" : "orange"}>{n.resolved ? "Chiarimento risolto" : "Domanda aperta"}</Badge>
                    {!n.resolved && canWrite && (
                      <Button variant="ghost" className="min-h-[36px] px-2" onClick={() => resolve(n.id)}>Segna come risolta</Button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {canWrite ? (
          <div className="flex flex-col gap-3 border-t border-line pt-4">
            <label htmlFor="note-text" className="label">Nuova nota</label>
            <textarea id="note-text" rows={3} className="input py-2" value={text} onChange={(e) => setText(e.target.value)}
              placeholder="Es. a cosa si riferisce questo bonifico?" />
            <label className="flex min-h-[44px] items-center gap-2 text-sm">
              <input type="checkbox" className="h-[18px] w-[18px]" checked={isQuestion} onChange={(e) => setIsQuestion(e.target.checked)} />
              È una domanda che richiede risposta
            </label>
            <div><Button onClick={send} loading={saving} disabled={!text.trim()}>Invia</Button></div>
          </div>
        ) : (
          <p className="text-xs text-muted">Il tuo ruolo permette solo di leggere le note.</p>
        )}
      </div>
    </Modal>
  );
}
