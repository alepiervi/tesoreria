import { useCallback, useEffect, useState } from "react";
import CompanyPicker, { usePageCompany } from "../components/CompanyPicker";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, PageHeader, useToast } from "../components/ui";
import { api, downloadFile, errorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDate } from "../lib/format";

function size(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function Documents() {
  const [company, setCompany] = usePageCompany("view");
  const { can, user } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState(null);
  const [categories, setCategories] = useState([]);
  const [filter, setFilter] = useState("");
  const [file, setFile] = useState(null);
  const [category, setCategory] = useState("F24");
  const [period, setPeriod] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [inputKey, setInputKey] = useState(0);

  const load = useCallback(async () => {
    if (!company) return;
    try {
      const res = await api.get(`/companies/${company.id}/documents`);
      setItems(res.data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [company]);

  useEffect(() => {
    api.get("/document-categories").then((r) => setCategories(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!company) return <Empty title="Nessuna azienda disponibile" />;
  const canUpload = can(company.id, "upload_documents");
  const canManage = can(company.id, "manage_members");

  const upload = async (e) => {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("category", category);
    form.append("period", period);
    form.append("note", note);
    setBusy(true);
    setError("");
    try {
      await api.post(`/companies/${company.id}/documents`, form);
      toast("Documento caricato");
      setFile(null);
      setNote("");
      setPeriod("");
      setInputKey((k) => k + 1);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (d) => {
    if (!window.confirm(`Eliminare "${d.name}"?`)) return;
    try {
      await api.delete(`/documents/${d.id}`);
      toast("Documento eliminato");
      load();
    } catch (e) {
      toast(errorMessage(e), "orange");
    }
  };

  const visible = (items || []).filter((d) => !filter || d.category === filter);

  return (
    <>
      <PageHeader title="Documenti" subtitle="F24, bilanci, dichiarazioni e altri documenti condivisi con il commercialista"
        actions={<CompanyPicker value={company.id} onChange={setCompany} />} />

      {canUpload && (
        <Card title="Carica un documento">
          <form onSubmit={upload} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {error && <div className="sm:col-span-2 lg:col-span-4"><ErrorBox>{error}</ErrorBox></div>}
            <Field label="File" htmlFor="doc-file" hint="PDF, immagini, Excel, XML · massimo 10 MB">
              <input key={inputKey} id="doc-file" type="file" className="input py-2" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </Field>
            <Field label="Categoria" htmlFor="doc-cat">
              <select id="doc-cat" className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Periodo" htmlFor="doc-period" hint="Es. ottobre 2026">
              <input id="doc-period" className="input" value={period} onChange={(e) => setPeriod(e.target.value)} />
            </Field>
            <Field label="Nota" htmlFor="doc-note">
              <input id="doc-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <div><Button type="submit" loading={busy} disabled={!file}>Carica</Button></div>
          </form>
        </Card>
      )}

      <div className="flex flex-wrap gap-2">
        {["", ...categories].map((c) => (
          <button key={c || "all"} type="button" onClick={() => setFilter(c)} aria-pressed={filter === c}
            className={`min-h-[40px] rounded-full border px-4 text-[13px] font-semibold ${filter === c ? "border-accent bg-accent text-white" : "border-[#C9CDD4] bg-white"}`}>
            {c || "Tutti"}
          </button>
        ))}
      </div>

      {!items ? <Loading /> : (
        <Card padded={false}>
          {visible.length === 0 ? <Empty title="Nessun documento" /> : (
            <ul className="divide-y divide-soft">
              {visible.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  <Badge>{d.category}</Badge>
                  <span className="min-w-[200px] flex-1">
                    <span className="block font-semibold">{d.name}</span>
                    <span className="block text-xs text-muted">
                      {[d.period, d.note, `${size(d.size)}`, `caricato da ${d.uploaded_by_name || "—"} il ${fmtDate(d.created_at.slice(0, 10), { year: true })}`].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <Button variant="ghost" className="min-h-[40px] px-2" onClick={() => downloadFile(`/documents/${d.id}/download`, null, d.name).catch((e) => toast(errorMessage(e), "orange"))}>Scarica</Button>
                  {(d.uploaded_by === user.id || canManage) && (
                    <Button variant="ghost" className="min-h-[40px] px-2 text-warn-text" onClick={() => remove(d)}>Elimina</Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </>
  );
}
