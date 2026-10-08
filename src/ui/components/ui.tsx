import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { fmtNumber } from "../../core/format";

export function PageHeader(props: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{props.title}</h1>
        {props.subtitle && <p>{props.subtitle}</p>}
      </div>
      {props.actions && <div className="page-actions no-print">{props.actions}</div>}
    </div>
  );
}

export function Card(props: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${props.className ?? ""}`}>
      {(props.title || props.actions) && (
        <div className="card-header">
          <div>
            {props.title && <h3>{props.title}</h3>}
            {props.subtitle && <p>{props.subtitle}</p>}
          </div>
          {props.actions && <div className="row no-print">{props.actions}</div>}
        </div>
      )}
      {props.children}
    </section>
  );
}

export function Field(props: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`field ${props.className ?? ""}`}>
      <span className="field-label">{props.label}</span>
      {props.children}
      {props.hint && <span className="field-hint">{props.hint}</span>}
    </div>
  );
}

export function TextField(props: {
  label?: ReactNode;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: ReactNode;
  type?: string;
}) {
  const id = useId();
  const input = (
    <input
      id={id}
      className="input"
      type={props.type ?? "text"}
      value={props.value}
      placeholder={props.placeholder}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
  if (!props.label) return input;
  return (
    <div className="field">
      <label htmlFor={id}>{props.label}</label>
      {input}
      {props.hint && <span className="field-hint">{props.hint}</span>}
    </div>
  );
}

export function TextArea(props: {
  label?: ReactNode;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
  hint?: ReactNode;
}) {
  const id = useId();
  const area = (
    <textarea
      id={id}
      className="textarea"
      rows={props.rows ?? 3}
      value={props.value}
      placeholder={props.placeholder}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
  if (!props.label) return area;
  return (
    <div className="field">
      <label htmlFor={id}>{props.label}</label>
      {area}
      {props.hint && <span className="field-hint">{props.hint}</span>}
    </div>
  );
}

type NumberKind = "number" | "money" | "percent";

/**
 * Numeric input that shows a formatted value ("1 250 000") while idle and the raw value while editing.
 * Percent fields store fractions (0.25) but display/edit percents (25).
 */
export function NumberField(props: {
  label?: ReactNode;
  value: number;
  onChange: (v: number) => void;
  kind?: NumberKind;
  suffix?: string;
  min?: number;
  max?: number;
  digits?: number;
  hint?: ReactNode;
  ariaLabel?: string;
}) {
  const id = useId();
  const kind = props.kind ?? "number";
  const scale = kind === "percent" ? 100 : 1;
  const digits = props.digits ?? (kind === "percent" ? 1 : kind === "money" ? 0 : 2);
  const shown = Number.isFinite(props.value) ? props.value * scale : 0;
  const [focused, setFocused] = useState(false);
  const [draft, setDraft] = useState("");

  const commit = (text: string) => {
    const normalized = text.replace(/\s/g, "").replace(",", ".");
    if (normalized === "" || normalized === "-") return;
    let v = Number(normalized);
    if (!Number.isFinite(v)) return;
    v = v / scale;
    if (props.min != null) v = Math.max(props.min, v);
    if (props.max != null) v = Math.min(props.max, v);
    props.onChange(v);
  };

  const suffix = props.suffix ?? (kind === "percent" ? "%" : undefined);
  const input = (
    <div className="input-wrap">
      <input
        id={id}
        aria-label={props.ariaLabel}
        className="input num"
        inputMode="decimal"
        style={suffix ? undefined : { paddingRight: 10 }}
        value={focused ? draft : fmtNumber(shown, digits)}
        onFocus={(e) => {
          setDraft(String(Math.round(shown * 10 ** digits) / 10 ** digits));
          setFocused(true);
          requestAnimationFrame(() => e.target.select());
        }}
        onChange={(e) => {
          setDraft(e.target.value);
          commit(e.target.value);
        }}
        onBlur={() => setFocused(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
      />
      {suffix && <span className="input-suffix">{suffix}</span>}
    </div>
  );
  if (!props.label) return input;
  return (
    <div className="field">
      <label htmlFor={id}>{props.label}</label>
      {input}
      {props.hint && <span className="field-hint">{props.hint}</span>}
    </div>
  );
}

export function Select<T extends string>(props: {
  label?: ReactNode;
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  hint?: ReactNode;
  compact?: boolean;
  ariaLabel?: string;
}) {
  const id = useId();
  const select = (
    <select
      id={id}
      className={`select ${props.compact ? "compact" : ""}`}
      aria-label={props.ariaLabel}
      value={props.value}
      onChange={(e) => props.onChange(e.target.value as T)}
    >
      {props.options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
  if (!props.label) return select;
  return (
    <div className="field">
      <label htmlFor={id}>{props.label}</label>
      {select}
      {props.hint && <span className="field-hint">{props.hint}</span>}
    </div>
  );
}

export function Checkbox(props: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={props.checked} onChange={(e) => props.onChange(e.target.checked)} />
      {props.children}
    </label>
  );
}

export function Chips<T extends string>(props: {
  options: { value: T; label: ReactNode }[];
  selected: T[];
  onChange: (v: T[]) => void;
  single?: boolean;
}) {
  return (
    <div className="chips" role="group">
      {props.options.map((o) => {
        const on = props.selected.includes(o.value);
        return (
          <button
            type="button"
            key={o.value}
            className={`chip ${on ? "on" : ""}`}
            aria-pressed={on}
            onClick={() => {
              if (props.single) props.onChange(on ? [] : [o.value]);
              else props.onChange(on ? props.selected.filter((v) => v !== o.value) : [...props.selected, o.value]);
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function ScoreSelector(props: { value?: number; onChange: (v: number) => void; label?: string }) {
  return (
    <div className="scores" role="radiogroup" aria-label={props.label}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={props.value === n}
          className={`score-btn ${props.value === n ? "on" : ""}`}
          onClick={() => props.onChange(n)}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>(props: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="tabs no-print" role="tablist">
      {props.tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={props.value === t.id}
          className={`tab ${props.value === t.id ? "active" : ""}`}
          onClick={() => props.onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export type Tone = "good" | "ok" | "warn" | "bad" | "muted";

export function Badge(props: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge ${props.tone ?? ""}`} title={props.title}>
      {props.children}
    </span>
  );
}

export function Stat(props: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: Tone }) {
  return (
    <div className="stat">
      <span className="stat-label">
        {props.tone && props.tone !== "muted" && <span className={`dot ${props.tone}`} aria-hidden />}
        {props.label}
      </span>
      <span className="stat-value">{props.value}</span>
      {props.sub && <span className="stat-sub">{props.sub}</span>}
    </div>
  );
}

export function Progress(props: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, props.value * 100));
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={props.label}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Empty(props: { icon?: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon">{props.icon ?? "✨"}</div>
      <h3>{props.title}</h3>
      {props.children && <div className="mt-8">{props.children}</div>}
    </div>
  );
}

export function Modal(props: { title: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const onClose = useRef(props.onClose);
  onClose.current = props.onClose;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose.current();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className="modal" role="dialog" aria-modal="true" tabIndex={-1} ref={ref} style={props.wide ? { width: "min(980px, 100%)" } : undefined}>
        <div className="modal-header">
          <h2>{props.title}</h2>
          <button className="btn ghost icon" onClick={props.onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        {props.children}
      </div>
    </div>
  );
}

/* ---------- Toasts ---------- */

type ToastItem = { id: number; text: string; kind: "info" | "error" };
let toastListener: ((t: ToastItem[]) => void) | null = null;
let toastItems: ToastItem[] = [];

export function toast(text: string, kind: ToastItem["kind"] = "info") {
  const item = { id: Date.now() + Math.random(), text, kind };
  toastItems = [...toastItems, item];
  toastListener?.(toastItems);
  setTimeout(() => {
    toastItems = toastItems.filter((t) => t.id !== item.id);
    toastListener?.(toastItems);
  }, kind === "error" ? 6000 : 3200);
}

export function Toasts() {
  const [items, setItems] = useState<ToastItem[]>([]);
  useEffect(() => {
    toastListener = setItems;
    return () => {
      toastListener = null;
    };
  }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind === "error" ? "error" : ""}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

export function downloadFile(name: string, content: string, type = "text/plain") {
  const blob = new Blob([content], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Скопировано в буфер обмена");
  } catch {
    toast("Не удалось скопировать — браузер запретил доступ к буферу", "error");
  }
}

export function toneOf(health: "good" | "ok" | "bad"): Tone {
  return health === "good" ? "good" : health === "ok" ? "warn" : "bad";
}
