import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Card, Empty, Modal, PageHeader } from "../components/ui";
import data from "../guide/guides.json";
import media from "../guide/media.json";

const BASE = `${process.env.PUBLIC_URL || ""}/guida`;

function norm(text) {
  return (text || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

/** Guida collegata alla pagina aperta (per il pulsante «Guida» in alto). */
export function guideForPath(pathname) {
  let best = null;
  let bestLen = 0;
  data.guides.forEach((g) => {
    (g.pages || []).forEach((p) => {
      const match = p === "/" ? pathname === "/" : pathname === p || pathname.startsWith(`${p}/`);
      if (match && p.length > bestLen) {
        best = g;
        bestLen = p.length;
      }
    });
  });
  return best;
}

export default function Guide() {
  const { guideId } = useParams();
  if (guideId) return <GuideDetail id={guideId} />;
  return <GuideIndex />;
}

function GuideIndex() {
  const [q, setQ] = useState("");
  const found = useMemo(() => {
    const n = norm(q.trim());
    if (!n) return data.guides;
    return data.guides.filter((g) => norm([g.title, g.summary, ...g.steps.map((s) => `${s.title} ${s.text}`)].join(" ")).includes(n));
  }, [q]);
  const videos = data.guides.filter((g) => media.videos[g.id]);

  return (
    <>
      <PageHeader title="Guida" subtitle="Come funziona il programma, passo per passo, con immagini e video" />
      <div className="max-w-xl">
        <label htmlFor="g-q" className="sr-only">Cerca nella guida</label>
        <input id="g-q" className="input" placeholder="Cerca: estratto conto, carta, sollecito, chiusura…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {!q && videos.length > 0 && (
        <Card title="Video brevi" subtitle="Da 30 secondi a un minuto, per vedere subito come si fa">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {videos.map((g) => (
              <Link key={g.id} to={`/guida/${g.id}`} className="group flex flex-col gap-2 rounded-xl border border-line p-2 hover:border-accent">
                <div className="relative overflow-hidden rounded-lg bg-soft" style={{ aspectRatio: "16 / 9" }}>
                  {media.images[`${g.id}-1`] && <img src={`${BASE}/${media.images[`${g.id}-1`]}`} alt="" loading="lazy" className="h-full w-full object-cover object-top" />}
                  <span className="absolute inset-0 flex items-center justify-center bg-ink/20 group-hover:bg-ink/30">
                    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/95 text-accent shadow">
                      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                    </span>
                  </span>
                  <span className="absolute bottom-1.5 right-1.5 rounded bg-ink/80 px-1.5 py-0.5 text-[11px] font-semibold text-white">{media.videos[g.id].duration}</span>
                </div>
                <span className="px-1 text-sm font-semibold">{g.title}</span>
              </Link>
            ))}
          </div>
        </Card>
      )}
      {data.sections.map((s) => {
        const items = found.filter((g) => g.section === s.id);
        if (!items.length) return null;
        return (
          <Card key={s.id} title={s.title} padded={false}>
            <ul className="divide-y divide-soft">
              {items.map((g) => (
                <li key={g.id}>
                  <Link to={`/guida/${g.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-soft">
                    <span className="min-w-0">
                      <span className="block font-semibold">{g.title}</span>
                      <span className="block text-sm text-muted">{g.summary}</span>
                    </span>
                    <span className="flex flex-none items-center gap-2">
                      {media.videos[g.id] && <Badge tone="blue">Video</Badge>}
                      <Badge>{g.steps.length} passi</Badge>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        );
      })}
      {found.length === 0 && <Card><Empty title="Nessuna guida trovata" text="Prova con un'altra parola." /></Card>}
    </>
  );
}

function GuideDetail({ id }) {
  const g = data.guides.find((x) => x.id === id);
  const [zoom, setZoom] = useState(null);
  useEffect(() => { window.scrollTo(0, 0); }, [id]);
  if (!g) return <Empty title="Guida non trovata" action={<Link className="font-semibold text-accent" to="/guida">Torna alla guida</Link>} />;
  const section = data.sections.find((s) => s.id === g.section);
  const sameSection = data.guides.filter((x) => x.section === g.section && x.id !== g.id);
  const video = media.videos[g.id];

  return (
    <>
      <nav aria-label="Percorso" className="text-sm text-muted">
        <Link to="/guida" className="font-semibold text-accent hover:underline">Guida</Link> · {section?.title}
      </nav>
      <PageHeader title={g.title} subtitle={g.summary}
        actions={g.pages?.[0] && g.pages[0] !== "/aziende" && <Link to={g.pages[0]} className="inline-flex min-h-[44px] items-center rounded-lg border border-[#C9CDD4] bg-white px-4 text-sm font-semibold hover:bg-soft">Apri la pagina</Link>} />
      {video && (
        <Card padded={false}>
          <video controls preload="metadata" className="w-full rounded-xl bg-ink" style={{ aspectRatio: "16 / 9" }}
            poster={media.images[`${g.id}-1`] ? `${BASE}/${media.images[`${g.id}-1`]}` : undefined}>
            <source src={`${BASE}/${video.file}`} type="video/mp4" />
            Il tuo browser non riproduce i video.
          </video>
        </Card>
      )}
      <ol className="flex flex-col gap-4">
        {g.steps.map((s, i) => {
          const img = media.images[`${g.id}-${i + 1}`];
          return (
            <li key={i}>
              <Card>
                <div className={`grid gap-5 ${img ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]" : ""}`}>
                  <div className="flex flex-col gap-2">
                    <span className="flex items-center gap-3">
                      <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-accent text-sm font-bold text-white">{i + 1}</span>
                      <h2 className="text-base font-semibold">{s.title}</h2>
                    </span>
                    <p className="text-sm leading-relaxed text-[#2A2E37]">{s.text}</p>
                  </div>
                  {img && (
                    <button type="button" onClick={() => setZoom({ src: `${BASE}/${img}`, title: s.title })} className="overflow-hidden rounded-lg border border-line hover:border-accent"
                      aria-label={`Ingrandisci l'immagine: ${s.title}`}>
                      <img src={`${BASE}/${img}`} alt={s.title} loading="lazy" className="w-full" />
                    </button>
                  )}
                </div>
              </Card>
            </li>
          );
        })}
      </ol>
      {sameSection.length > 0 && (
        <Card title={`Altre guide · ${section?.title}`}>
          <ul className="flex flex-col gap-2 text-sm">
            {sameSection.map((x) => <li key={x.id}><Link className="font-semibold text-accent hover:underline" to={`/guida/${x.id}`}>{x.title}</Link></li>)}
          </ul>
        </Card>
      )}
      <Modal open={Boolean(zoom)} onClose={() => setZoom(null)} wide title={zoom?.title || ""}>
        {zoom && <img src={zoom.src} alt={zoom.title} className="w-full rounded-lg" />}
      </Modal>
    </>
  );
}
