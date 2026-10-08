import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/* ---------- helpers ---------- */

export function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0];
  if (min === max) {
    const pad = Math.abs(min) || 1;
    min -= pad;
    max += pad;
  }
  const span = max - min;
  const raw = span / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Math.abs(v) < step / 1e6 ? 0 : v);
  return ticks;
}

/** Short axis number: 1 200 000 → "1,2 млн". */
export function shortNum(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  const f = (x: number) => (Math.round(x * 10) / 10).toLocaleString("ru-RU");
  if (abs >= 1e9) return `${sign}${f(abs / 1e9)} млрд`;
  if (abs >= 1e6) return `${sign}${f(abs / 1e6)} млн`;
  if (abs >= 1e3) return `${sign}${f(abs / 1e3)} тыс`;
  return `${sign}${f(abs)}`;
}

export const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];

export function Legend(props: { items: { name: string; color: string; kind?: "line" | "box" | "dashed" }[] }) {
  return (
    <div className="legend">
      {props.items.map((i) => (
        <span className="legend-item" key={i.name}>
          <span
            className={`legend-key ${i.kind === "box" ? "box" : ""}`}
            style={
              i.kind === "dashed"
                ? { background: `repeating-linear-gradient(90deg, ${i.color} 0 4px, transparent 4px 7px)` }
                : { background: i.color }
            }
          />
          {i.name}
        </span>
      ))}
    </div>
  );
}

function Tooltip(props: { x: number; y: number; width: number; children: ReactNode }) {
  const left = props.x > props.width / 2 ? props.x - 12 : props.x + 12;
  return (
    <div
      className="chart-tooltip"
      style={{ left, top: props.y, transform: props.x > props.width / 2 ? "translateX(-100%)" : undefined }}
    >
      {props.children}
    </div>
  );
}

const PAD = { top: 10, right: 16, bottom: 26, left: 58 };

/* ---------- Line chart ---------- */

export interface LineSeries {
  name: string;
  values: number[];
  color: string;
  dashed?: boolean;
  area?: boolean;
}

export interface Band {
  name: string;
  lower: number[];
  upper: number[];
  color: string;
}

export function LineChart(props: {
  labels: (string | number)[];
  series: LineSeries[];
  bands?: Band[];
  height?: number;
  format: (v: number) => string;
  xTitle?: (label: string | number) => string;
  markers?: { index: number; label: string }[];
  ariaLabel: string;
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = props.height ?? 260;
  const n = props.labels.length;
  const all = [
    ...props.series.flatMap((s) => s.values),
    ...(props.bands ?? []).flatMap((b) => [...b.lower, ...b.upper]),
  ].filter(Number.isFinite);
  const ticks = niceTicks(Math.min(0, ...all), Math.max(0, ...all), 5);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const innerW = Math.max(10, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - ((v - yMin) / (yMax - yMin || 1)) * innerH;
  const path = (values: number[]) => values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const xStep = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 56))));
  const legendItems = [
    ...props.series.map((s) => ({ name: s.name, color: s.color, kind: s.dashed ? ("dashed" as const) : ("line" as const) })),
    ...(props.bands ?? []).map((b) => ({ name: b.name, color: `color-mix(in srgb, ${b.color} 30%, transparent)`, kind: "box" as const })),
  ];

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = (e.target as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round((px / rect.width) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div>
      {legendItems.length >= 2 && <Legend items={legendItems} />}
      <div className="chart" ref={ref} role="img" aria-label={props.ariaLabel}>
        {width > 0 && (
          <svg width={width} height={height}>
            {ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? "axis-line" : "grid-line"} x1={PAD.left} x2={PAD.left + innerW} y1={y(t)} y2={y(t)} />
                <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end">
                  {shortNum(t)}
                </text>
              </g>
            ))}
            {props.labels.map((l, i) =>
              i % xStep === 0 || i === n - 1 ? (
                <text key={i} x={x(i)} y={height - 8} textAnchor="middle">
                  {l}
                </text>
              ) : null,
            )}
            {(props.bands ?? []).map((b) => (
              <path
                key={b.name}
                d={`${path(b.upper)}${b.lower
                  .map((v, i) => [i, v] as const)
                  .reverse()
                  .map(([i, v]) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`)
                  .join("")}Z`}
                fill={b.color}
                opacity={0.16}
              />
            ))}
            {props.series.map((s) =>
              s.area ? (
                <path
                  key={`${s.name}-area`}
                  d={`${path(s.values)}L${x(n - 1)},${y(Math.max(yMin, 0))}L${x(0)},${y(Math.max(yMin, 0))}Z`}
                  fill={s.color}
                  opacity={0.1}
                />
              ) : null,
            )}
            {(props.markers ?? []).map((m) => (
              <g key={m.label}>
                <line x1={x(m.index)} x2={x(m.index)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--axis)" strokeWidth={1} />
                <text x={x(m.index) + 4} y={PAD.top + 10} style={{ fill: "var(--text-2)" }}>
                  {m.label}
                </text>
              </g>
            ))}
            {props.series.map((s) => (
              <path
                key={s.name}
                d={path(s.values)}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s.dashed ? "5 4" : undefined}
              />
            ))}
            {hover !== null && (
              <g>
                <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--axis)" strokeWidth={1} />
                {props.series.map((s) =>
                  Number.isFinite(s.values[hover]) ? (
                    <circle key={s.name} cx={x(hover)} cy={y(s.values[hover])} r={4.5} fill={s.color} stroke="var(--chart-surface)" strokeWidth={2} />
                  ) : null,
                )}
              </g>
            )}
            <rect
              x={PAD.left}
              y={PAD.top}
              width={innerW}
              height={innerH}
              fill="transparent"
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
            />
          </svg>
        )}
        {hover !== null && width > 0 && (
          <Tooltip x={x(hover)} y={PAD.top} width={width}>
            <div className="tt-title">{props.xTitle ? props.xTitle(props.labels[hover]) : props.labels[hover]}</div>
            {props.series.map((s) => (
              <div className="tt-row" key={s.name}>
                <span>
                  <span className="dot" style={{ background: s.color }} />
                  {s.name}
                </span>
                <b className="num">{props.format(s.values[hover])}</b>
              </div>
            ))}
            {(props.bands ?? []).map((b) => (
              <div className="tt-row" key={b.name}>
                <span>{b.name}</span>
                <b className="num">
                  {props.format(b.lower[hover])} … {props.format(b.upper[hover])}
                </b>
              </div>
            ))}
          </Tooltip>
        )}
      </div>
    </div>
  );
}

/* ---------- Bar chart (grouped columns) ---------- */

export function BarChart(props: {
  categories: string[];
  series: { name: string; values: number[]; color: string }[];
  height?: number;
  format: (v: number) => string;
  ariaLabel: string;
  gap?: number;
  vLines?: { value: number; label: string }[];
  xNumeric?: { min: number; max: number };
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = props.height ?? 240;
  const all = props.series.flatMap((s) => s.values).filter(Number.isFinite);
  const ticks = niceTicks(Math.min(0, ...all), Math.max(0, ...all), 4);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const innerW = Math.max(10, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;
  const y = (v: number) => PAD.top + innerH - ((v - yMin) / (yMax - yMin || 1)) * innerH;
  const nCat = props.categories.length;
  const band = innerW / Math.max(1, nCat);
  const contiguous = props.gap === 0;
  const barW = contiguous
    ? Math.max(1, band - 2)
    : Math.min(24, (band * 0.7) / Math.max(1, props.series.length));
  const groupW = contiguous ? barW : barW * props.series.length + 2 * (props.series.length - 1);
  const labelStep = Math.max(1, Math.ceil(nCat / Math.max(2, Math.floor(innerW / 64))));

  const barPath = (x0: number, w: number, v: number) => {
    const top = y(Math.max(v, 0));
    const bottom = y(Math.min(v, 0));
    const h = Math.max(0, bottom - top);
    const r = Math.min(4, w / 2, h);
    if (h <= 0) return "";
    if (v >= 0)
      return `M${x0},${bottom}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + w - r}Q${x0 + w},${top} ${x0 + w},${top + r}V${bottom}Z`;
    return `M${x0},${top}V${bottom - r}Q${x0},${bottom} ${x0 + r},${bottom}H${x0 + w - r}Q${x0 + w},${bottom} ${x0 + w},${bottom - r}V${top}Z`;
  };
  const vx = (value: number) =>
    props.xNumeric ? PAD.left + ((value - props.xNumeric.min) / (props.xNumeric.max - props.xNumeric.min || 1)) * innerW : 0;

  return (
    <div>
      {props.series.length >= 2 && <Legend items={props.series.map((s) => ({ name: s.name, color: s.color, kind: "box" }))} />}
      <div className="chart" ref={ref} role="img" aria-label={props.ariaLabel}>
        {width > 0 && (
          <svg width={width} height={height}>
            {ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? "axis-line" : "grid-line"} x1={PAD.left} x2={PAD.left + innerW} y1={y(t)} y2={y(t)} />
                <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end">
                  {shortNum(t)}
                </text>
              </g>
            ))}
            {props.categories.map((c, ci) => {
              const gx = PAD.left + ci * band + (band - groupW) / 2;
              return (
                <g key={ci} opacity={hover === null || hover === ci ? 1 : 0.55}>
                  {props.series.map((s, si) => (
                    <path key={s.name} d={barPath(gx + si * (barW + 2), barW, s.values[ci])} fill={s.color} />
                  ))}
                  {!props.xNumeric && ci % labelStep === 0 && (
                    <text x={PAD.left + ci * band + band / 2} y={height - 8} textAnchor="middle">
                      {c}
                    </text>
                  )}
                  <rect
                    x={PAD.left + ci * band}
                    y={PAD.top}
                    width={band}
                    height={innerH}
                    fill="transparent"
                    onPointerEnter={() => setHover(ci)}
                    onPointerLeave={() => setHover(null)}
                  />
                </g>
              );
            })}
            {props.xNumeric &&
              niceTicks(props.xNumeric.min, props.xNumeric.max, Math.max(2, Math.floor(innerW / 90)))
                .filter((t) => t >= props.xNumeric!.min && t <= props.xNumeric!.max)
                .map((t) => (
                  <text key={t} x={vx(t)} y={height - 8} textAnchor="middle">
                    {shortNum(t)}
                  </text>
                ))}
            {(props.vLines ?? []).map((l, i) => (
              <g key={l.label} pointerEvents="none">
                <line x1={vx(l.value)} x2={vx(l.value)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--text-2)" strokeWidth={1} strokeDasharray="3 3" />
                <text x={vx(l.value) + 4} y={PAD.top + 10 + i * 13} style={{ fill: "var(--text-2)" }}>
                  {l.label}
                </text>
              </g>
            ))}
          </svg>
        )}
        {hover !== null && width > 0 && (
          <Tooltip x={PAD.left + hover * band + band / 2} y={PAD.top} width={width}>
            <div className="tt-title">{props.categories[hover]}</div>
            {props.series.map((s) => (
              <div className="tt-row" key={s.name}>
                <span>
                  <span className="dot" style={{ background: s.color }} />
                  {s.name}
                </span>
                <b className="num">{props.format(s.values[hover])}</b>
              </div>
            ))}
          </Tooltip>
        )}
      </div>
    </div>
  );
}

/* ---------- Radar ---------- */

export function RadarChart(props: { axes: { label: string; value: number }[]; max?: number; size?: number; ariaLabel: string }) {
  const [ref, width] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const size = Math.min(props.size ?? 320, width || 320);
  const max = props.max ?? 100;
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 74;
  const n = props.axes.length;
  const pt = (i: number, v: number) => {
    const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
    const rr = (Math.max(0, v) / max) * r;
    return [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr] as const;
  };
  const poly = props.axes.map((a, i) => pt(i, a.value).join(",")).join(" ");
  return (
    <div className="chart" ref={ref} role="img" aria-label={props.ariaLabel} style={{ display: "flex", justifyContent: "center" }}>
      {width > 0 && (
        <svg width={size} height={size}>
          {[0.25, 0.5, 0.75, 1].map((k) => (
            <polygon
              key={k}
              points={props.axes.map((_, i) => pt(i, max * k).join(",")).join(" ")}
              fill="none"
              className="grid-line"
            />
          ))}
          {props.axes.map((a, i) => {
            const [ex, ey] = pt(i, max);
            const [lx, ly] = pt(i, max * 1.14);
            return (
              <g key={a.label}>
                <line x1={cx} y1={cy} x2={ex} y2={ey} className="grid-line" />
                <text
                  x={lx}
                  y={ly + 4}
                  textAnchor={Math.abs(lx - cx) < 8 ? "middle" : lx > cx ? "start" : "end"}
                  style={{ fill: "var(--text-2)", fontSize: 12 }}
                >
                  {a.label}
                </text>
              </g>
            );
          })}
          <polygon points={poly} fill="var(--s1)" fillOpacity={0.12} stroke="var(--s1)" strokeWidth={2} strokeLinejoin="round" />
          {props.axes.map((a, i) => {
            const [px, py] = pt(i, a.value);
            return (
              <g key={a.label} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
                <circle cx={px} cy={py} r={12} fill="transparent" />
                <circle cx={px} cy={py} r={4.5} fill="var(--s1)" stroke="var(--chart-surface)" strokeWidth={2} />
                {hover === i && (
                  <text x={px} y={py - 12} textAnchor="middle" style={{ fill: "var(--text)", fontWeight: 650, fontSize: 12 }}>
                    {Math.round(a.value)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

/* ---------- Tornado ---------- */

export function TornadoChart(props: {
  rows: { label: string; low: number; high: number }[];
  base: number;
  format: (v: number) => string;
  ariaLabel: string;
  lowLabel: string;
  highLabel: string;
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const rowH = 34;
  const labelW = Math.min(170, width * 0.36);
  const height = props.rows.length * rowH + 8;
  const values = props.rows.flatMap((r) => [r.low, r.high]).concat(props.base);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.18 || 1;
  const innerW = Math.max(10, width - labelW - 12);
  const x = (v: number) => labelW + ((v - (min - pad)) / (max - min + 2 * pad)) * innerW;
  return (
    <div>
      <Legend
        items={[
          { name: props.lowLabel, color: "var(--s2)", kind: "box" },
          { name: props.highLabel, color: "var(--s1)", kind: "box" },
        ]}
      />
      <div className="chart" ref={ref} role="img" aria-label={props.ariaLabel}>
        {width > 0 && (
          <svg width={width} height={height}>
            {props.rows.map((r, i) => {
              const yy = i * rowH + 6;
              const h = 18;
              const lowW = Math.max(1, x(props.base) - x(r.low));
              const highW = Math.max(1, x(r.high) - x(props.base));
              return (
                <g key={r.label}>
                  <text x={0} y={yy + 13} style={{ fill: "var(--text-2)", fontSize: 12 }}>
                    {r.label}
                  </text>
                  <rect x={x(r.low)} y={yy} width={lowW} height={h} rx={4} fill="var(--s2)" />
                  <rect x={x(props.base)} y={yy} width={highW} height={h} rx={4} fill="var(--s1)" />
                  <text x={x(r.low) - 4} y={yy + 13} textAnchor="end">
                    {props.format(r.low)}
                  </text>
                  <text x={x(r.high) + 4} y={yy + 13}>
                    {props.format(r.high)}
                  </text>
                </g>
              );
            })}
            <line x1={x(props.base)} x2={x(props.base)} y1={0} y2={height} stroke="var(--text-2)" strokeWidth={1} />
          </svg>
        )}
      </div>
    </div>
  );
}

/* ---------- Positioning map ---------- */

export function PositioningMap(props: {
  points: { id: string; label: string; x: number; y: number; self?: boolean }[];
  xLabel: string;
  yLabel: string;
  ariaLabel: string;
}) {
  const [ref, width] = useSize<HTMLDivElement>();
  const size = Math.min(width, 520);
  const pad = 30;
  const inner = Math.max(10, size - pad * 2);
  const sx = (v: number) => pad + (v / 10) * inner;
  const sy = (v: number) => pad + inner - (v / 10) * inner;
  return (
    <div className="chart" ref={ref} role="img" aria-label={props.ariaLabel}>
      {width > 0 && (
        <svg width={size} height={size} style={{ margin: "0 auto" }}>
          <rect x={pad} y={pad} width={inner} height={inner} fill="var(--surface-2)" rx={8} />
          <line x1={sx(5)} x2={sx(5)} y1={pad} y2={pad + inner} className="grid-line" />
          <line x1={pad} x2={pad + inner} y1={sy(5)} y2={sy(5)} className="grid-line" />
          <text x={pad + inner} y={pad + inner + 18} textAnchor="end" style={{ fill: "var(--text-2)", fontSize: 12 }}>
            {props.xLabel}
          </text>
          <text x={pad - 10} y={pad - 10} style={{ fill: "var(--text-2)", fontSize: 12 }}>
            {props.yLabel}
          </text>
          {props.points.map((p) => (
            <g key={p.id}>
              <circle
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={p.self ? 9 : 6}
                fill={p.self ? "var(--s1)" : "var(--s2)"}
                stroke="var(--chart-surface)"
                strokeWidth={2}
              />
              <text
                x={sx(p.x) + (p.x > 7 ? -12 : 12)}
                y={sy(p.y) + 4}
                textAnchor={p.x > 7 ? "end" : "start"}
                style={{ fill: "var(--text)", fontSize: 12, fontWeight: p.self ? 700 : 500 }}
              >
                {p.label}
              </text>
            </g>
          ))}
        </svg>
      )}
    </div>
  );
}

/* ---------- Gauge ---------- */

export function Gauge(props: { value: number; label: string; size?: number; color?: string }) {
  const size = props.size ?? 180;
  const stroke = 14;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const v = Math.max(0, Math.min(100, props.value));
  const arc = (from: number, to: number) => {
    const a0 = Math.PI * (1 - from / 100);
    const a1 = Math.PI * (1 - to / 100);
    const x0 = cx + r * Math.cos(a0);
    const y0 = cy - r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1);
    const y1 = cy - r * Math.sin(a1);
    return `M${x0},${y0}A${r},${r} 0 0 1 ${x1},${y1}`;
  };
  const color = props.color ?? (v >= 70 ? "var(--good)" : v >= 50 ? "var(--accent)" : v >= 35 ? "var(--warn)" : "var(--bad)");
  return (
    <svg width={size} height={size / 2 + 12} role="img" aria-label={`${props.label}: ${Math.round(v)} из 100`}>
      <path d={arc(0, 100)} stroke="var(--surface-3)" strokeWidth={stroke} fill="none" strokeLinecap="round" />
      {v > 0 && <path d={arc(0, v)} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round" />}
      <text x={cx} y={cy - 6} textAnchor="middle" style={{ fontSize: size * 0.22, fontWeight: 700, fill: "var(--text)" }}>
        {Math.round(v)}
      </text>
      <text x={cx} y={cy + 10} textAnchor="middle" style={{ fontSize: 11, fill: "var(--muted)" }}>
        из 100
      </text>
    </svg>
  );
}
