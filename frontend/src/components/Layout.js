import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ROLE_LABELS } from "../lib/format";
import { guideForPath } from "../pages/Guide";

const ICONS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  bank: "M3 9 12 4l9 5M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18",
  spark: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  doc: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 13h6M9 17h6",
  link: "M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  receipt: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6",
  hand: "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
  swap: "M7 7h13l-4-4M17 17H4l4 4",
  percent: "M19 5 5 19M6.5 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM17.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01",
  loan: "M3 10h18M5 10V20M19 10V20M9 10v10M15 10v10M2 20h20M12 3l9 5H3z",
  chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
  folder: "M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
  download: "M12 3v12M7 10l5 5 5-5M4 20h16",
  users: "M16 20v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 20v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  shield: "M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6z",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  book: "M4 4.5A1.5 1.5 0 0 1 5.5 3H20v16H5.5A1.5 1.5 0 0 0 4 20.5zM4 20.5A1.5 1.5 0 0 0 5.5 22H20M8 7h8M8 11h6",
  tree: "M4 4h6v4H4zM14 10h6v4h-6zM14 18h6v4h-6zM7 8v12h7M7 12h7",
  scale: "M12 3v18M5 7h14M5 7l-3 7a3.5 3.5 0 0 0 6 0zM19 7l-3 7a3.5 3.5 0 0 0 6 0zM8 21h8",
  box: "M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  register: "M5 3h14v18H5zM9 7h6M9 11h6M9 15h3",
  pulse: "M3 12h4l3-8 4 16 3-8h4",
  plan: "M3 3v18h18M7 15l4-4 3 3 5-6",
  shieldcheck: "M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6zM9 12l2 2 4-4",
  layers: "M12 3 2 8l10 5 10-5zM2 13l10 5 10-5M2 17l10 5 10-5",
  coins: "M12 6c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 3v6c0 1.7 3.6 3 8 3s8-1.3 8-3V3M4 9v6c0 1.7 3.6 3 8 3s8-1.3 8-3V9",
  columns: "M4 4h4v16H4zM10 8h4v12h-4zM16 12h4v8h-4z",
  briefcase: "M3 7h18v13H3zM8 7V4h8v3M3 12h18",
  wallet: "M3 7a2 2 0 0 1 2-2h13v4M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2zM16 14h.01",
  check: "M4 12l5 5L20 6",
  tag: "M3 12V4h8l10 10-8 8zM7.5 7.5h.01",
  antenna: "M12 12v9M8 21h8M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M12 12h.01",
  receiptcheck: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 11l2 2 4-4",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",
  bell: "M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0",
};

export function Icon({ name, size = 18 }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={ICONS[name]} />
    </svg>
  );
}

export default function Layout() {
  const { user, companies, anyCan, roles, logout, counts, selected } = useAuth();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const location = useLocation();
  const navigate = useNavigate();

  const loadUnread = useCallback(() => {
    api.get("/notifications/unread-count").then((r) => setUnread(r.data.unread)).catch(() => {});
  }, []);

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    loadUnread();
    const t = setInterval(loadUnread, 60000);
    window.addEventListener("notifications-changed", loadUnread);
    return () => { clearInterval(t); window.removeEventListener("notifications-changed", loadUnread); };
  }, [loadUnread]);
  useEffect(() => { loadUnread(); }, [location.pathname, loadUnread]);

  const multi = companies.length > 1;
  const sections = [
    {
      title: "Panoramica",
      items: [
        { to: "/", label: "Vista di gruppo", icon: "home", end: true },
        { to: selected ? `/aziende/${selected.id}` : "/", label: "Azienda", icon: "bank", match: "/aziende" },
        anyCan("use_assistant") && { to: "/assistente", label: "Assistente", icon: "spark" },
      ],
    },
    {
      title: "Operatività",
      items: [
        { to: "/movimenti", label: "Movimenti", icon: "list" },
        { to: "/fatture", label: "Fatture", icon: "doc" },
        { to: "/riconciliazione", label: "Riconciliazione", icon: "link", badge: counts.to_reconcile },
        { to: "/scadenze", label: "Scadenzario", icon: "calendar" },
        anyCan("view_accounting") && { to: "/paghe", label: "Paghe", icon: "wallet" },
        { to: "/scontrini", label: "Scontrini", icon: "receipt" },
        anyCan("view_accounting") && { to: "/chiusura-mese", label: "Chiusura del mese", icon: "check" },
      ],
    },
    anyCan("view_commissions") && {
      title: "Provvigioni",
      items: [
        { to: "/provvigioni", label: "Attivazioni", icon: "antenna", end: true },
        { to: "/provvigioni/rendiconti", label: "Rendiconti", icon: "receiptcheck" },
        { to: "/provvigioni/impostazioni", label: "Listino e venditori", icon: "sliders" },
      ],
    },
    {
      title: "Analisi",
      items: [
        { to: "/crediti", label: "Crediti e debiti", icon: "hand" },
        { to: "/iva", label: "IVA stimata", icon: "percent" },
        { to: "/budget", label: "Budget", icon: "target" },
        anyCan("view_accounting") && { to: "/commesse", label: "Commesse", icon: "briefcase" },
        { to: "/finanziamenti", label: "Finanziamenti", icon: "loan" },
      ],
    },
    {
      title: "Controllo e strategia",
      items: [
        anyCan("view_accounting") && { to: "/salute", label: "Salute dell'azienda", icon: "pulse" },
        anyCan("view_accounting") && { to: "/piano", label: "Piano a 3 anni", icon: "plan" },
        { to: "/centrale-rischi", label: "Centrale Rischi", icon: "shieldcheck" },
      ],
    },
    multi && {
      title: "Gruppo",
      items: [
        anyCan("view_accounting") && { to: "/gruppo/consolidato", label: "Bilancio consolidato", icon: "layers" },
        { to: "/gruppo/liquidita", label: "Liquidità di gruppo", icon: "coins" },
        anyCan("view_accounting") && { to: "/gruppo/confronto", label: "Confronto aziende", icon: "columns" },
        { to: "/intercompany", label: "Tra le aziende", icon: "swap" },
      ],
    },
    anyCan("view_accounting") && {
      title: "Contabilità",
      items: [
        { to: "/contabilita/prima-nota", label: "Prima nota", icon: "book" },
        { to: "/contabilita/da-classificare", label: "Da classificare", icon: "tag" },
        { to: "/contabilita/piano-conti", label: "Piano dei conti", icon: "tree" },
        { to: "/contabilita/registri-iva", label: "Registri IVA", icon: "register" },
        { to: "/contabilita/bilancio", label: "Bilancio", icon: "scale" },
        { to: "/contabilita/cespiti", label: "Cespiti", icon: "box" },
        { to: "/contabilita/chiusure", label: "Chiusure e rettifiche", icon: "lock" },
      ],
    },
    {
      title: "Con il commercialista",
      items: [
        { to: "/chiarimenti", label: "Chiarimenti", icon: "chat", badge: counts.open_questions },
        { to: "/documenti", label: "Documenti", icon: "folder" },
        anyCan("export") && { to: "/export", label: "Export e report", icon: "download" },
      ],
    },
    {
      title: "Aiuto",
      items: [{ to: "/guida", label: "Guida e video", icon: "help" }],
    },
    {
      title: "Amministrazione",
      items: [
        anyCan("manage_members") && { to: "/utenti", label: "Utenti e accessi", icon: "users" },
        anyCan("view_audit") && { to: "/registro", label: "Registro attività", icon: "shield" },
        { to: "/impostazioni", label: "Impostazioni", icon: "gear" },
      ],
    },
  ].filter(Boolean).map((s) => ({ ...s, items: s.items.filter(Boolean) })).filter((s) => s.items.length);

  const roleText = !companies.length
    ? "Nessuna azienda"
    : roles.length === 1
    ? `${ROLE_LABELS[roles[0]]} · ${companies.length} ${companies.length === 1 ? "azienda" : "aziende"}`
    : `${companies.length} aziende · ruoli diversi`;

  const bell = (
    <Link to="/notifiche" aria-label={unread ? `Notifiche, ${unread} da leggere` : "Notifiche"}
      className="relative flex h-11 w-11 flex-none items-center justify-center rounded-lg text-[#E8EAEE] hover:bg-side-hover">
      <Icon name="bell" size={20} />
      {unread > 0 && (
        <span className="absolute right-1 top-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-warn px-1 text-[11px] font-bold text-ink">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );

  const sidebar = (
    <nav aria-label="Menu principale" className="flex h-full flex-col gap-5 overflow-y-auto bg-side px-4 py-6 text-[#E8EAEE]">
      <div className="flex items-start justify-between gap-2 px-2">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-lg font-bold tracking-tight text-white">Nureal-Amministrazione</span>
          <span className="text-xs text-[#A9AFBC]">{roleText}</span>
        </div>
        {bell}
      </div>
      {sections.map((section) => (
        <div key={section.title} className="flex flex-col gap-1">
          <span className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-[#8A90A0]">{section.title}</span>
          <ul className="flex flex-col gap-0.5">
            {section.items.map((item) => {
              const forceActive = item.match && location.pathname.startsWith(item.match);
              return (
                <li key={item.label}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `flex min-h-[42px] items-center justify-between gap-3 rounded-lg px-3 text-sm ${
                        isActive || forceActive ? "bg-side-active font-semibold text-white" : "font-medium text-side-text hover:bg-side-hover"
                      }`
                    }
                  >
                    <span className="flex items-center gap-3"><Icon name={item.icon} />{item.label}</span>
                    {item.badge ? (
                      <span className="inline-flex h-6 min-w-[24px] items-center justify-center rounded-full bg-warn px-2 text-xs font-bold text-ink">{item.badge}</span>
                    ) : null}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      <div className="mt-auto flex flex-col gap-2 rounded-xl bg-side-hover p-3">
        <span className="truncate text-sm font-semibold text-white">{user?.name || user?.email}</span>
        <span className="truncate text-xs text-[#A9AFBC]">{user?.email}</span>
        <button
          type="button"
          onClick={() => { logout(); navigate("/login"); }}
          className="mt-1 min-h-[40px] rounded-lg border border-[#3A3F4B] text-sm font-semibold text-[#E8EAEE] hover:bg-side-active"
        >
          Esci
        </button>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden lg:sticky lg:top-0 lg:block lg:h-screen lg:w-[256px] lg:flex-none">{sidebar}</aside>

      <div className="flex items-center justify-between gap-2 bg-side px-4 py-2 lg:hidden">
        <span className="font-bold text-white">Nureal-Amministrazione</span>
        <div className="flex items-center gap-1">
          {bell}
          <button type="button" onClick={() => setOpen(true)} aria-label="Apri menu" className="flex h-11 w-11 items-center justify-center rounded-lg text-white hover:bg-side-hover">
            <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
          </button>
        </div>
      </div>
      {open && (
        <div className="fixed inset-0 z-40 bg-ink/50 lg:hidden" onClick={() => setOpen(false)}>
          <div className="h-full w-[290px] max-w-[85vw]" onClick={(e) => e.stopPropagation()}>{sidebar}</div>
        </div>
      )}

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto flex max-w-[1240px] flex-col gap-6">
          {(() => {
            const g = !location.pathname.startsWith("/guida") && guideForPath(location.pathname);
            return g ? (
              <div className="-mb-3 flex justify-end">
                <Link to={`/guida/${g.id}`} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-full border border-line bg-white px-3 text-xs font-semibold text-accent hover:bg-accent-soft">
                  <Icon name="help" size={16} /> Guida: {g.title.split(":")[0]}
                </Link>
              </div>
            ) : null;
          })()}
          <Outlet />
        </div>
      </main>
    </div>
  );
}
