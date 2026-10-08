import { useMemo, useState } from "react";
import { completeAi } from "../../ai/client";
import { PITCH_PROMPT, SYSTEM_BASE, planSectionPrompt, projectContext } from "../../ai/prompts";
import { PLAN_SECTIONS, buildBusinessPlan, buildSection, fundingAsk } from "../../core/businessPlan";
import { fmtPercent, slugify } from "../../core/format";
import { runMonteCarlo, type MonteCarloResult } from "../../core/monteCarlo";
import { newId } from "../../core/random";
import type { Milestone, PlanSectionId } from "../../core/types";
import { AiButton, AiOutput, useAiTask } from "../components/Ai";
import { EditableTable } from "../components/EditableTable";
import { Markdown } from "../components/Markdown";
import { Badge, Card, Checkbox, NumberField, PageHeader, copyText, downloadFile, toast } from "../components/ui";
import { useProject } from "../hooks";

function htmlDocument(title: string, bodyHtml: string): string {
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escapeHtml(title)}</title>
<style>body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;max-width:860px;margin:40px auto;padding:0 20px;color:#111;line-height:1.6}
h1{font-size:28px}h2{font-size:20px;border-bottom:1px solid #ddd;padding-bottom:6px;margin-top:32px}h3{font-size:16px}
table{border-collapse:collapse;width:100%;margin:10px 0 16px;font-size:13px}th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f5f5f3}
blockquote{border-left:3px solid #2a78d6;margin:10px 0;padding:6px 14px;background:#f6f8fb;color:#444}@media print{body{margin:0}}</style></head><body>${bodyHtml}</body></html>`;
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export function PlanPage() {
  const { project: p, analysis: a, update, money } = useProject();
  const [withMc, setWithMc] = useState(true);
  const [editing, setEditing] = useState<PlanSectionId | null>(null);
  const [improving, setImproving] = useState<PlanSectionId | null>(null);
  const sectionAi = useAiTask();
  const pitch = useAiTask();

  // Every edit deep-copies the project, so key the (expensive) simulation by content, not by reference.
  const mcKey = JSON.stringify([p.finance, p.monteCarlo]);
  const mc: MonteCarloResult | null = useMemo(() => {
    if (!withMc) return null;
    const [finance, monteCarlo] = JSON.parse(mcKey) as [typeof p.finance, typeof p.monteCarlo];
    return runMonteCarlo(finance, { ...monteCarlo, runs: Math.min(monteCarlo.runs, 1000) });
  }, [withMc, mcKey]);
  const ctx = { project: p, analysis: a, monteCarlo: mc };
  const markdown = useMemo(() => buildBusinessPlan({ project: p, analysis: a, monteCarlo: mc }), [p, a, mc]);
  const ask = fundingAsk(p, a);
  const u = p.plan.useOfFunds;
  const fundsTotal = u.product + u.marketing + u.team + u.reserve;

  const fileBase = `business-plan-${slugify(p.idea.title || p.name)}`;

  const exportHtml = () => {
    const container = document.getElementById("plan-preview");
    downloadFile(`${fileBase}.html`, htmlDocument(`Бизнес-план: ${p.idea.title || p.name}`, container?.innerHTML ?? ""), "text/html");
  };

  const improveSection = async (id: PlanSectionId) => {
    setImproving(id);
    const title = PLAN_SECTIONS.find((s) => s.id === id)!.title;
    const draft = buildSection(id, ctx);
    const text = await sectionAi.run((signal, onText) =>
      completeAi({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: planSectionPrompt(title, draft) }],
        onText,
        signal,
      }),
    );
    if (text) {
      update((d) => void (d.plan.overrides[id] = text));
      toast(`Раздел «${title}» улучшен — правка сохранена, её можно отменить`);
    }
    setImproving(null);
  };

  const runPitch = () =>
    pitch.run(async (signal, onText) => {
      const text = await completeAi({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: PITCH_PROMPT }],
        onText,
        signal,
      });
      update((d) => void (d.ai.pitch = text));
      return text;
    });

  const overridden = PLAN_SECTIONS.filter((s) => p.plan.overrides[s.id]?.trim()).length;

  return (
    <>
      <div className="no-print">
      <PageHeader
        title="Бизнес-план"
        subtitle="Собирается автоматически из всех разделов проекта и обновляется при любом изменении. Любой раздел можно переписать вручную или улучшить с ИИ."
        actions={
          <>
            <button className="btn" onClick={() => copyText(markdown)}>
              Копировать
            </button>
            <button className="btn" onClick={() => downloadFile(`${fileBase}.md`, markdown, "text/markdown")}>
              ⬇ Markdown
            </button>
            <button className="btn" onClick={exportHtml}>
              ⬇ HTML
            </button>
            <button className="btn primary" onClick={() => window.print()}>
              🖨 PDF / печать
            </button>
          </>
        }
      />
      </div>

      <div className="grid grid-side">
        <Card className="plan-card">
          <div id="plan-preview">
            <Markdown text={markdown} />
          </div>
        </Card>

        <div className="stack sticky-side no-print">
          <Card title="Запрос инвестиций">
            <div className="stack" style={{ gap: 12 }}>
              <Checkbox
                checked={p.plan.fundingAsk == null}
                onChange={(auto) => update((d) => void (d.plan.fundingAsk = auto ? null : fundingAsk(d, a)))}
              >
                Рассчитать автоматически (потребность + 20% запас)
              </Checkbox>
              {p.plan.fundingAsk == null ? (
                <div className="stat-value">{money(ask)}</div>
              ) : (
                <NumberField label="Сумма запроса" kind="money" value={p.plan.fundingAsk} min={0} onChange={(v) => update((d) => void (d.plan.fundingAsk = v))} />
              )}
              <div className="field-label">Использование средств</div>
              <div className="grid grid-2" style={{ gap: 8 }}>
                {(
                  [
                    ["product", "Продукт"],
                    ["marketing", "Маркетинг"],
                    ["team", "Команда"],
                    ["reserve", "Резерв"],
                  ] as const
                ).map(([k, label]) => (
                  <NumberField
                    key={k}
                    label={label}
                    kind="percent"
                    value={u[k]}
                    min={0}
                    max={1}
                    onChange={(v) => update((d) => void (d.plan.useOfFunds[k] = v))}
                  />
                ))}
              </div>
              {Math.abs(fundsTotal - 1) > 0.005 && (
                <div className="callout warn small">Сумма долей — {fmtPercent(fundsTotal)}. В плане доли будут нормированы до 100%.</div>
              )}
            </div>
          </Card>

          <Card title="Включить в план">
            <Checkbox checked={withMc} onChange={setWithMc}>
              Результаты Монте-Карло (1 000 сценариев)
            </Checkbox>
          </Card>

          <Card title="Разделы" subtitle={overridden ? `Изменено вручную или ИИ: ${overridden}` : "Все разделы собраны автоматически"}>
            <ul className="list-plain">
              {PLAN_SECTIONS.map((s) => {
                const custom = !!p.plan.overrides[s.id]?.trim();
                return (
                  <li key={s.id} className="check-item small" style={{ alignItems: "center" }}>
                    <span style={{ flex: 1 }}>
                      {s.title} {custom && <Badge tone="ok">изменён</Badge>}
                    </span>
                    <button className="btn sm ghost" onClick={() => setEditing(s.id)} title="Править вручную">
                      ✎
                    </button>
                    <AiButton small onClick={() => improveSection(s.id)} loading={sectionAi.loading && improving === s.id} title="Улучшить с ИИ">
                      {""}
                    </AiButton>
                    {custom && (
                      <button
                        className="btn sm ghost"
                        title="Вернуть автоматическую версию"
                        onClick={() => update((d) => void delete d.plan.overrides[s.id])}
                      >
                        ↺
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
            {sectionAi.loading && (
              <div className="small text-2 mt-8 row">
                <span className="spinner" /> Claude переписывает раздел…
                <button className="btn sm ghost" onClick={sectionAi.cancel}>
                  Отменить
                </button>
              </div>
            )}
          </Card>

          <Card title="Дорожная карта">
            <EditableTable<Milestone>
              rows={p.plan.milestones}
              onChange={(rows) => update((d) => void (d.plan.milestones = rows))}
              newRow={() => ({ id: newId("ms"), title: "", month: p.finance.launchMonth, metric: "" })}
              addLabel="Добавить веху"
              columns={[
                { key: "month", label: "Мес.", kind: "number", width: 70, min: 1 },
                { key: "title", label: "Веха", kind: "text", width: 150 },
                { key: "metric", label: "Результат", kind: "text", width: 150 },
              ]}
            />
          </Card>

          <Card title="Питч для инвесторов" subtitle="Речь на 60 секунд, структура питч-дека и ответы на сложные вопросы.">
            <AiButton onClick={runPitch} loading={pitch.loading}>
              Подготовить питч
            </AiButton>
          </Card>
        </div>
      </div>

      <div className="mt-16 no-print">
        <AiOutput
          title="Питч и вопросы инвесторов"
          task={pitch.text || pitch.loading || pitch.error ? pitch : { ...pitch, text: p.ai.pitch ?? "" }}
          onClose={() => {
            pitch.reset();
            update((d) => void delete d.ai.pitch);
          }}
        />
      </div>

      {editing && (
        <SectionEditor
          id={editing}
          initial={buildSection(editing, ctx)}
          onSave={(text) => update((d) => void (d.plan.overrides[editing] = text))}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}

function SectionEditor(props: { id: PlanSectionId; initial: string; onSave: (t: string) => void; onClose: () => void }) {
  const [text, setText] = useState(props.initial);
  const title = PLAN_SECTIONS.find((s) => s.id === props.id)!.title;
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className="modal" role="dialog" aria-modal="true" style={{ width: "min(1100px, 100%)" }}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="btn ghost icon" onClick={props.onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="grid grid-2">
          <textarea className="textarea" style={{ minHeight: 420, fontFamily: "var(--mono)", fontSize: 13 }} value={text} onChange={(e) => setText(e.target.value)} aria-label="Текст раздела в Markdown" />
          <div className="card flat" style={{ maxHeight: 420, overflow: "auto" }}>
            <Markdown text={text} />
          </div>
        </div>
        <div className="row mt-16">
          <button
            className="btn primary"
            onClick={() => {
              props.onSave(text);
              props.onClose();
            }}
          >
            Сохранить
          </button>
          <button className="btn ghost" onClick={props.onClose}>
            Отмена
          </button>
          <span className="small muted">Поддерживается Markdown: **жирный**, списки, таблицы.</span>
        </div>
      </div>
    </div>
  );
}
