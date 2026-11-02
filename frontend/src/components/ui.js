import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

const BUTTON = {
  primary: "bg-accent text-white hover:bg-accent-dark border border-accent",
  secondary: "bg-white text-ink border border-[#C9CDD4] hover:bg-soft",
  danger: "bg-white text-warn-text border border-[#C9CDD4] hover:bg-warn-soft",
  ghost: "bg-transparent text-accent border border-transparent hover:bg-accent-soft",
};

export function Button({ variant = "primary", className = "", loading = false, children, ...props }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || loading}
      className={`inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON[variant]} ${className}`}
    >
      {loading && <Spinner small />}
      {children}
    </button>
  );
}

export function Card({ title, subtitle, actions, children, className = "", padded = true }) {
  return (
    <section className={`min-w-0 rounded-xl border border-line bg-white ${padded ? "p-5" : ""} ${className}`}>
      {(title || actions || subtitle) && (
        <div className={`mb-4 flex flex-wrap items-start justify-between gap-3 ${padded ? "" : "px-5 pt-5"}`}>
          <div className="flex flex-col gap-1">
            {title && <h2 className="text-base font-semibold">{title}</h2>}
            {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

const TONES = {
  blue: "bg-accent-soft text-accent-dark",
  orange: "bg-warn-soft text-warn-text",
  gray: "bg-[#F1F3F5] text-[#3D4250]",
  green: "bg-accent-soft text-accent-dark",
  dark: "bg-ink text-white",
};

export function Badge({ tone = "gray", children, className = "" }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${TONES[tone] || TONES.gray} ${className}`}>
      {children}
    </span>
  );
}

export function Stat({ label, value, sub, tone }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-line bg-white px-5 py-4">
      <span className="text-[13px] text-muted">{label}</span>
      <span className={`num text-2xl font-bold tracking-tight ${tone === "warn" ? "text-warn-amount" : ""}`}>{value}</span>
      {sub && <span className="text-xs text-muted">{sub}</span>}
    </div>
  );
}

export function Amount({ cents, signed = true, className = "" }) {
  const neg = cents < 0;
  return (
    <span className={`num font-semibold ${neg ? "text-warn-amount" : "text-ink"} ${className}`}>
      {formatAmount(cents, signed)}
    </span>
  );
}

function formatAmount(cents, signed) {
  const value = Math.abs(cents || 0) / 100;
  const text = new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR", useGrouping: "always" }).format(value);
  if (cents < 0) return `− ${text}`;
  if (signed && cents > 0) return `+ ${text}`;
  return text;
}

export function Spinner({ small = false }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${small ? "h-4 w-4" : "h-6 w-6"}`}
    />
  );
}

export function Loading({ text = "Caricamento…" }) {
  return (
    <div role="status" className="flex items-center justify-center gap-3 py-16 text-muted">
      <Spinner /> {text}
    </div>
  );
}

export function Empty({ title, text, action }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <p className="text-base font-semibold">{title}</p>
      {text && <p className="max-w-md text-sm text-muted">{text}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorBox({ children }) {
  if (!children) return null;
  return <div role="alert" className="rounded-lg bg-warn-soft px-4 py-3 text-sm font-medium text-warn-dark">{children}</div>;
}

export function Notice({ tone = "blue", children }) {
  const cls = tone === "orange" ? "bg-warn-soft text-warn-dark" : "bg-accent-soft text-accent-dark";
  return <div className={`rounded-lg px-4 py-3 text-sm leading-relaxed ${cls}`}>{children}</div>;
}

export function Field({ label, htmlFor, hint, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label htmlFor={htmlFor} className="label">{label}</label>}
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, wide = false }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const first = ref.current?.querySelector("input, select, textarea, button");
    first?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-6" onMouseDown={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className={`flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-white shadow-xl sm:rounded-2xl ${wide ? "sm:max-w-3xl" : "sm:max-w-lg"}`}
      >
        <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Chiudi" className="flex h-11 w-11 items-center justify-center rounded-lg text-muted hover:bg-soft">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
          </button>
        </div>
        <div className="overflow-y-auto px-5 py-5">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-4">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 rounded-xl bg-[#E9EBEE] p-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`min-h-[40px] rounded-lg px-4 text-[13px] font-semibold ${value === t.id ? "bg-white text-ink shadow-sm" : "text-[#3D4250]"}`}
        >
          {t.label}
          {t.count ? <span className="ml-2 rounded-full bg-warn px-2 py-0.5 text-[11px] text-ink">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-[26px] font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="text-[13px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

// ---------- Avvisi temporanei ----------

const ToastContext = createContext(() => {});

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((text, tone = "blue") => {
    const id = Math.random().toString(36).slice(2);
    setItems((list) => [...list, { id, text, tone }]);
    setTimeout(() => setItems((list) => list.filter((i) => i.id !== id)), 4500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex max-w-sm flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className={`pointer-events-auto rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${t.tone === "orange" ? "bg-warn-soft text-warn-dark" : "bg-ink text-white"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

// ---------- Semaforo ----------

const LIGHTS = {
  verde: ["bg-[#E5F4EA] text-[#1D6A35]", "bg-[#2E9E55]", "Bene"],
  giallo: ["bg-[#FFF3D1] text-[#755300]", "bg-[#E2A800]", "Attenzione"],
  rosso: ["bg-[#FCE8E6] text-[#A3201A]", "bg-[#D93A2F]", "Allarme"],
  grigio: ["bg-[#F1F3F5] text-[#3D4250]", "bg-[#9AA0AC]", "Dato non disponibile"],
};

export function Light({ status, label, className = "" }) {
  const [cls, dot, text] = LIGHTS[status] || LIGHTS.grigio;
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${cls} ${className}`}>
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dot}`} />
      {label ?? text}
    </span>
  );
}
