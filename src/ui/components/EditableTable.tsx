import type { ReactNode } from "react";
import { NumberField } from "./ui";

export interface Column<T> {
  key: keyof T & string;
  label: string;
  kind: "text" | "number" | "money" | "percent" | "select" | "textarea";
  options?: { value: string; label: string }[];
  width?: number | string;
  min?: number;
  max?: number;
  placeholder?: string;
}

/** Inline-editable table for lists of records (team, costs, competitors, risks…). */
export function EditableTable<T extends { id: string }>(props: {
  rows: T[];
  columns: Column<T>[];
  onChange: (rows: T[]) => void;
  newRow: () => T;
  addLabel?: string;
  empty?: ReactNode;
  extra?: (row: T) => ReactNode;
}) {
  const set = (id: string, key: keyof T, value: unknown) =>
    props.onChange(props.rows.map((r) => (r.id === id ? { ...r, [key]: value } : r)));
  return (
    <div className="stack" style={{ gap: 8 }}>
      {props.rows.length > 0 ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                {props.columns.map((c) => (
                  <th key={c.key} style={{ width: c.width }}>
                    {c.label}
                  </th>
                ))}
                {props.extra && <th />}
                <th style={{ width: 40 }} />
              </tr>
            </thead>
            <tbody>
              {props.rows.map((row) => (
                <tr key={row.id}>
                  {props.columns.map((c) => {
                    const value = row[c.key] as unknown;
                    return (
                      <td key={c.key} style={{ minWidth: typeof c.width === "number" ? c.width : 110 }}>
                        {c.kind === "text" && (
                          <input
                            className="input"
                            aria-label={c.label}
                            value={String(value ?? "")}
                            placeholder={c.placeholder}
                            onChange={(e) => set(row.id, c.key, e.target.value)}
                          />
                        )}
                        {c.kind === "textarea" && (
                          <textarea
                            className="textarea"
                            aria-label={c.label}
                            rows={2}
                            style={{ minHeight: 40 }}
                            value={String(value ?? "")}
                            placeholder={c.placeholder}
                            onChange={(e) => set(row.id, c.key, e.target.value)}
                          />
                        )}
                        {(c.kind === "number" || c.kind === "money" || c.kind === "percent") && (
                          <NumberField
                            ariaLabel={c.label}
                            kind={c.kind}
                            value={Number(value) || 0}
                            min={c.min}
                            max={c.max}
                            digits={c.kind === "number" ? 0 : undefined}
                            onChange={(v) => set(row.id, c.key, v)}
                          />
                        )}
                        {c.kind === "select" && (
                          <select
                            className="select"
                            aria-label={c.label}
                            value={String(value)}
                            onChange={(e) => set(row.id, c.key, e.target.value)}
                          >
                            {c.options!.map((o) => (
                              <option key={o.value} value={o.value}>
                                {o.label}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                    );
                  })}
                  {props.extra && <td>{props.extra(row)}</td>}
                  <td>
                    <button
                      className="btn ghost icon"
                      aria-label="Удалить строку"
                      title="Удалить"
                      onClick={() => props.onChange(props.rows.filter((r) => r.id !== row.id))}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        props.empty && <div className="muted small">{props.empty}</div>
      )}
      <div>
        <button className="btn sm" onClick={() => props.onChange([...props.rows, props.newRow()])}>
          ＋ {props.addLabel ?? "Добавить"}
        </button>
      </div>
    </div>
  );
}
