import { CURRENCIES, fmtMonths, fmtNumber, type CurrencyCode } from "../../core/format";
import { BUSINESS_MODELS } from "../../core/knowledge/businessModels";
import { INDUSTRIES } from "../../core/knowledge/industries";
import { SEGMENTS } from "../../core/knowledge/library";
import type { ProjectIdea, Segment } from "../../core/types";
import { VERDICTS } from "../../core/validation";
import { Gauge, LineChart } from "../components/charts";
import { Badge, Card, PageHeader, Progress, Select, Stat, TextArea, TextField, toneOf } from "../components/ui";
import { useProject } from "../hooks";
import { navigate } from "../router";

const SEVERITY_ICON = { error: "⛔", warning: "⚠️", info: "ℹ️", ok: "✅" } as const;

export function OverviewPage() {
  const { project: p, analysis: a, update, money } = useProject();
  const setIdea = (patch: Partial<ProjectIdea>) => update((d) => Object.assign(d.idea, patch));
  const verdict = VERDICTS[a.validation.verdict];
  const fin = a.finance;
  const months = fin.rows.map((r) => r.month);

  return (
    <>
      <PageHeader
        title={p.name}
        subtitle="Сводка проекта: насколько он готов к запуску и инвестициям, и что сделать дальше."
        actions={
          <>
            <button className="btn" onClick={() => navigate("validation")}>
              🎯 Оценить идею
            </button>
            <button className="btn primary" onClick={() => navigate("plan")}>
              📄 Бизнес-план
            </button>
          </>
        }
      />

      <div className="grid grid-side">
        <div className="stack">
          <Card>
            <div className="grid grid-4" style={{ alignItems: "center" }}>
              <div style={{ textAlign: "center" }}>
                <Gauge value={a.readiness.score} label="Готовность проекта" size={160} />
                <div className="small text-2">Готовность проекта</div>
              </div>
              <Stat
                label="Оценка идеи"
                value={a.validation.answered ? `${Math.round(a.validation.score)} / 100` : "—"}
                sub={<Badge tone={verdict.tone}>{verdict.label}</Badge>}
              />
              <Stat
                label="LTV / CAC"
                tone={toneOf(a.unit.health.ltvToCac)}
                value={Number.isFinite(a.unit.ltvToCac) ? fmtNumber(a.unit.ltvToCac, 1) : "∞"}
                sub={`окупаемость клиента ${fmtMonths(a.unit.paybackMonths, true)}`}
              />
              <Stat
                label="Безубыточность"
                tone={fin.breakEvenMonth ? "good" : "bad"}
                value={fin.breakEvenMonth ? `${fin.breakEvenMonth}-й мес.` : "не достигается"}
                sub={`нужно денег: ${money(fin.fundingNeed)}`}
              />
            </div>
          </Card>

          <Card title="Деньги и рост" subtitle={`Базовый сценарий финмодели на ${p.finance.horizonMonths} мес.`}>
            <LineChart
              ariaLabel="Выручка, расходы и остаток денег по месяцам"
              labels={months}
              xTitle={(m) => `Месяц ${m}`}
              format={(v) => money(v)}
              series={[
                { name: "Выручка", values: fin.rows.map((r) => r.revenue), color: "var(--s1)" },
                {
                  name: "Расходы",
                  values: fin.rows.map((r) => r.cogs + r.marketing + r.payroll + r.opex + r.tax),
                  color: "var(--s2)",
                },
                { name: "Остаток денег", values: fin.rows.map((r) => r.cash), color: "var(--s3)", dashed: true },
              ]}
              markers={fin.breakEvenMonth ? [{ index: fin.breakEvenMonth - 1, label: "безубыточность" }] : []}
            />
          </Card>

          <Card title="Описание идеи" subtitle="От этих полей зависят все разделы: шаблоны, гипотезы, ИИ-подсказки и бизнес-план.">
            <div className="stack" style={{ gap: 12 }}>
              <div className="grid grid-2">
                <TextField label="Название проекта" value={p.name} onChange={(name) => update((d) => void (d.name = name))} />
                <TextField label="Название идеи" value={p.idea.title} onChange={(title) => setIdea({ title })} />
              </div>
              <TextArea
                label="Суть в одном предложении"
                value={p.idea.oneLiner}
                onChange={(oneLiner) => setIdea({ oneLiner })}
                rows={2}
                placeholder="Для [кого], у которых [проблема], [продукт] — это [категория], который [выгода]"
              />
              <div className="grid grid-2">
                <TextArea label="Проблема" value={p.idea.problem} onChange={(problem) => setIdea({ problem })} rows={4} />
                <TextArea label="Решение" value={p.idea.solution} onChange={(solution) => setIdea({ solution })} rows={4} />
              </div>
              <TextField label="Целевая аудитория" value={p.idea.audience} onChange={(audience) => setIdea({ audience })} />
              <div className="form-grid">
                <Select
                  label="Сегмент"
                  value={p.idea.segment}
                  onChange={(segment) => setIdea({ segment })}
                  options={(Object.keys(SEGMENTS) as Segment[]).map((s) => ({ value: s, label: SEGMENTS[s] }))}
                />
                <Select
                  label="Отрасль"
                  value={p.idea.industryId ?? ""}
                  onChange={(industryId) => setIdea({ industryId: industryId || undefined })}
                  options={[
                    { value: "", label: "— не выбрана —" },
                    ...INDUSTRIES.map((i) => ({ value: i.id, label: `${i.emoji} ${i.name}` })),
                  ]}
                />
                <Select
                  label="Бизнес-модель"
                  value={p.idea.modelId ?? ""}
                  onChange={(modelId) => setIdea({ modelId: modelId || undefined })}
                  options={[
                    { value: "", label: "— не выбрана —" },
                    ...BUSINESS_MODELS.map((m) => ({ value: m.id, label: `${m.emoji} ${m.name}` })),
                  ]}
                />
                <Select
                  label="Стадия"
                  value={p.idea.stage}
                  onChange={(stage) => setIdea({ stage })}
                  options={[
                    { value: "idea", label: "Идея" },
                    { value: "validation", label: "Проверка гипотез" },
                    { value: "mvp", label: "MVP" },
                    { value: "launched", label: "Запущен" },
                  ]}
                />
                <Select
                  label="Валюта"
                  value={p.currency}
                  onChange={(currency) => update((d) => void (d.currency = currency as CurrencyCode))}
                  options={(Object.keys(CURRENCIES) as CurrencyCode[]).map((c) => ({ value: c, label: CURRENCIES[c].label }))}
                />
              </div>
            </div>
          </Card>
        </div>

        <div className="stack">
          <Card title="Что сделать дальше" subtitle="Автоматическая проверка согласованности всех разделов.">
            <ul className="list-plain">
              {a.checks.slice(0, 10).map((c) => (
                <li key={c.id} className={`check-item ${c.severity}`}>
                  <span className="ci-icon" aria-hidden>
                    {SEVERITY_ICON[c.severity]}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <b>{c.title}</b>
                    <div className="small text-2">{c.detail}</div>
                  </div>
                  <button className="btn sm ghost" onClick={() => navigate(c.route)} aria-label={`Перейти: ${c.title}`}>
                    →
                  </button>
                </li>
              ))}
            </ul>
            {a.checks.length > 10 && <div className="muted small mt-8">И ещё {a.checks.length - 10}…</div>}
          </Card>

          <Card title="Готовность по разделам">
            <div className="stack" style={{ gap: 10 }}>
              {a.readiness.parts.map((part) => (
                <a key={part.label} href={`#/${part.route}`} style={{ color: "inherit", textDecoration: "none" }}>
                  <div className="row-between small">
                    <span>{part.label}</span>
                    <span className="muted num">
                      {fmtNumber(part.value, 1)} / {part.max}
                    </span>
                  </div>
                  <Progress value={part.value / part.max} label={part.label} />
                </a>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
