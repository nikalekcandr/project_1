import { useMemo, useState } from "react";
import { completeJson } from "../../ai/client";
import { HYPOTHESES_PROMPT, HYPOTHESES_SCHEMA, SYSTEM_BASE, projectContext } from "../../ai/prompts";
import {
  getExperiment,
  hypothesisTemplate,
  interviewScript,
  priorityScore,
  recommendExperiments,
  sortByPriority,
} from "../../core/experiments";
import { EXPERIMENTS, HYPOTHESIS_TYPES } from "../../core/knowledge/library";
import { newId } from "../../core/random";
import type { Hypothesis, HypothesisStatus, HypothesisType } from "../../core/types";
import { CRITERIA } from "../../core/validation";
import { AiButton, useAiTask } from "../components/Ai";
import { Badge, Card, Chips, Empty, Modal, NumberField, PageHeader, Select, Tabs, copyText, toast, type Tone } from "../components/ui";
import { useProject } from "../hooks";

const STATUS: Record<HypothesisStatus, { label: string; tone: Tone }> = {
  untested: { label: "Не проверена", tone: "muted" },
  running: { label: "В работе", tone: "ok" },
  validated: { label: "Подтверждена", tone: "good" },
  invalidated: { label: "Опровергнута", tone: "bad" },
};

type Tab = "hypotheses" | "library";

export function ExperimentsPage() {
  const { project: p, analysis: a, update } = useProject();
  const [tab, setTab] = useState<Tab>("hypotheses");
  const [script, setScript] = useState(false);
  const [libFilter, setLibFilter] = useState<HypothesisType[]>([]);
  const ai = useAiTask();
  // Order is frozen while editing (so cards don't jump under the cursor) and re-sorted on demand.
  const [order, setOrder] = useState(() => sortByPriority(p.hypotheses).map((h) => h.id));
  const ordered = useMemo(() => {
    const byId = new Map(p.hypotheses.map((h) => [h.id, h]));
    const known = order.filter((id) => byId.has(id)).map((id) => byId.get(id)!);
    return [...p.hypotheses.filter((h) => !order.includes(h.id)), ...known];
  }, [p.hypotheses, order]);

  const setH = (id: string, patch: Partial<Hypothesis>) =>
    update((d) => void (d.hypotheses = d.hypotheses.map((h) => (h.id === id ? { ...h, ...patch } : h))));

  const add = (type: HypothesisType) =>
    update(
      (d) =>
        void d.hypotheses.unshift({
          id: newId("hyp"),
          statement: hypothesisTemplate(type, d.idea),
          type,
          criterionId: HYPOTHESIS_TYPES[type].criterion,
          impact: 7,
          confidence: 4,
          ease: 6,
          experimentId: recommendExperiments(type, 1)[0]?.id,
          successMetric: "",
          status: "untested",
          result: "",
        }),
    );

  const generate = async () => {
    const res = await ai.run((signal) =>
      completeJson<{ hypotheses: Omit<Hypothesis, "id" | "status" | "result" | "criterionId">[] }>({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: HYPOTHESES_PROMPT }],
        schema: HYPOTHESES_SCHEMA,
        signal,
      }),
    );
    if (!res) return;
    const c10 = (v: number) => Math.min(10, Math.max(1, Math.round(v)));
    update((d) => {
      for (const h of res.hypotheses) {
        d.hypotheses.push({
          ...h,
          id: newId("hyp"),
          impact: c10(h.impact),
          confidence: c10(h.confidence),
          ease: c10(h.ease),
          criterionId: HYPOTHESIS_TYPES[h.type]?.criterion,
          status: "untested",
          result: "",
        });
      }
    });
    toast(`ИИ добавил гипотез: ${res.hypotheses.length}`);
  };

  const counts = {
    total: p.hypotheses.length,
    validated: p.hypotheses.filter((h) => h.status === "validated").length,
    invalidated: p.hypotheses.filter((h) => h.status === "invalidated").length,
    running: p.hypotheses.filter((h) => h.status === "running").length,
  };

  return (
    <>
      <PageHeader
        title="Гипотезы и эксперименты"
        subtitle="Бизнес-план — это набор гипотез. Проверяйте самые рискованные дёшево и быстро. Подтверждённые гипотезы автоматически повышают уверенность в оценке идеи."
        actions={
          <>
            <button className="btn" onClick={() => setScript(true)}>
              🎤 Скрипт интервью
            </button>
            <AiButton onClick={generate} loading={ai.loading}>
              Гипотезы с ИИ
            </AiButton>
          </>
        }
      />
      <Tabs
        tabs={[
          { id: "hypotheses", label: `Гипотезы (${counts.total})` },
          { id: "library", label: "Библиотека экспериментов" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "hypotheses" ? (
        <div className="stack">
          <Card>
            <div className="row-between">
              <div className="row small">
                <Badge tone="good">✓ {counts.validated} подтверждено</Badge>
                <Badge tone="bad">✕ {counts.invalidated} опровергнуто</Badge>
                <Badge tone="ok">⏳ {counts.running} в работе</Badge>
              </div>
              <div className="row">
                <span className="small text-2">Новая гипотеза:</span>
                {(Object.keys(HYPOTHESIS_TYPES) as HypothesisType[]).map((t) => (
                  <button key={t} className="btn sm" onClick={() => add(t)}>
                    ＋ {HYPOTHESIS_TYPES[t].label}
                  </button>
                ))}
              </div>
            </div>
            <div className="row-between mt-8">
              <p className="small text-2" style={{ margin: 0, flex: "1 1 320px" }}>
                Приоритет = влияние × (11 − уверенность) × простота. Наверху — то, что сильнее всего влияет на успех, в чём вы меньше всего
                уверены и что проще проверить.
              </p>
              <button className="btn sm" onClick={() => setOrder(sortByPriority(p.hypotheses).map((h) => h.id))}>
                ↕ Упорядочить по приоритету
              </button>
            </div>
          </Card>

          {ordered.length === 0 && (
            <Card>
              <Empty icon="🧪" title="Гипотез пока нет">
                Добавьте гипотезу кнопками выше или сгенерируйте с ИИ.
              </Empty>
            </Card>
          )}

          {ordered.map((h) => {
            const exp = getExperiment(h.experimentId);
            const recs = recommendExperiments(h.type);
            return (
              <Card key={h.id}>
                <div className="stack" style={{ gap: 12 }}>
                  <div className="row-between" style={{ alignItems: "flex-start" }}>
                    <div className="row">
                      <Badge tone={STATUS[h.status].tone}>{STATUS[h.status].label}</Badge>
                      <span className="tag">{HYPOTHESIS_TYPES[h.type].label}</span>
                      <span className="small text-2">
                        Приоритет <b className="num">{priorityScore(h)}</b>
                      </span>
                    </div>
                    <button
                      className="btn sm ghost danger"
                      onClick={() => update((d) => void (d.hypotheses = d.hypotheses.filter((x) => x.id !== h.id)))}
                    >
                      Удалить
                    </button>
                  </div>
                  <textarea
                    className="textarea"
                    aria-label="Формулировка гипотезы"
                    rows={2}
                    value={h.statement}
                    onChange={(e) => setH(h.id, { statement: e.target.value })}
                  />
                  <div className="form-grid">
                    <Select
                      label="Тип"
                      value={h.type}
                      onChange={(type) => setH(h.id, { type })}
                      options={(Object.keys(HYPOTHESIS_TYPES) as HypothesisType[]).map((t) => ({
                        value: t,
                        label: HYPOTHESIS_TYPES[t].label,
                      }))}
                    />
                    <Select
                      label="Влияет на критерий"
                      value={h.criterionId ?? ""}
                      onChange={(v) => setH(h.id, { criterionId: (v || undefined) as Hypothesis["criterionId"] })}
                      options={[{ value: "", label: "—" }, ...CRITERIA.map((c) => ({ value: c.id, label: c.name }))]}
                    />
                    <NumberField
                      label="Влияние (1–10)"
                      value={h.impact}
                      digits={0}
                      min={1}
                      max={10}
                      onChange={(v) => setH(h.id, { impact: Math.round(v) })}
                    />
                    <NumberField
                      label="Уверенность (1–10)"
                      value={h.confidence}
                      digits={0}
                      min={1}
                      max={10}
                      onChange={(v) => setH(h.id, { confidence: Math.round(v) })}
                    />
                    <NumberField
                      label="Простота (1–10)"
                      value={h.ease}
                      digits={0}
                      min={1}
                      max={10}
                      onChange={(v) => setH(h.id, { ease: Math.round(v) })}
                    />
                    <Select
                      label="Статус"
                      value={h.status}
                      onChange={(status) => setH(h.id, { status })}
                      options={(Object.keys(STATUS) as HypothesisStatus[]).map((s) => ({ value: s, label: STATUS[s].label }))}
                    />
                  </div>
                  <div className="grid grid-2">
                    <div className="field">
                      <Select
                        label="Эксперимент"
                        value={h.experimentId ?? ""}
                        onChange={(v) => setH(h.id, { experimentId: v || undefined })}
                        options={[
                          { value: "", label: "— не выбран —" },
                          ...EXPERIMENTS.map((e) => ({ value: e.id, label: `${e.emoji} ${e.name}` })),
                        ]}
                      />
                      <span className="field-hint">Рекомендуем: {recs.map((r) => r.name).join(", ")}</span>
                    </div>
                    <div className="field">
                      <label>Критерий успеха</label>
                      <input
                        className="input"
                        value={h.successMetric}
                        placeholder={exp?.metricExample ?? "Число, при котором гипотеза подтверждена"}
                        onChange={(e) => setH(h.id, { successMetric: e.target.value })}
                      />
                    </div>
                  </div>
                  {exp && (
                    <details className="disclosure">
                      <summary>
                        Как провести: {exp.emoji} {exp.name} · ~{exp.days} дн.
                      </summary>
                      <ol className="small text-2" style={{ margin: "8px 0 0", paddingLeft: 20 }}>
                        {exp.steps.map((s) => (
                          <li key={s}>{s}</li>
                        ))}
                      </ol>
                    </details>
                  )}
                  {(h.status === "validated" || h.status === "invalidated" || h.status === "running") && (
                    <textarea
                      className="textarea"
                      aria-label="Результат эксперимента"
                      rows={2}
                      placeholder="Результат: цифры, выводы, что меняем"
                      value={h.result}
                      onChange={(e) => setH(h.id, { result: e.target.value })}
                    />
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <>
          <div className="mb-8" style={{ marginBottom: 16 }}>
            <Chips
              options={(Object.keys(HYPOTHESIS_TYPES) as HypothesisType[]).map((t) => ({ value: t, label: HYPOTHESIS_TYPES[t].label }))}
              selected={libFilter}
              onChange={setLibFilter}
            />
          </div>
          <div className="grid grid-auto">
            {EXPERIMENTS.filter((e) => !libFilter.length || e.bestFor.some((t) => libFilter.includes(t))).map((e) => (
              <Card key={e.id} title={`${e.emoji} ${e.name}`} subtitle={e.description}>
                <div className="row small">
                  <span className="tag">Стоимость {"₽".repeat(e.cost)}</span>
                  <span className="tag">~{e.days} дн.</span>
                  <span className="tag">
                    Сила доказательства {"●".repeat(e.evidence)}
                    {"○".repeat(5 - e.evidence)}
                  </span>
                </div>
                <ol className="small text-2" style={{ paddingLeft: 20, margin: "10px 0" }}>
                  {e.steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
                <div className="small">
                  <b>Пример критерия:</b> {e.metricExample}
                </div>
                <div className="small text-2 mt-8">Подходит для: {e.bestFor.map((t) => HYPOTHESIS_TYPES[t].label).join(", ")}</div>
              </Card>
            ))}
          </div>
        </>
      )}

      {script && <InterviewModal onClose={() => setScript(false)} />}
    </>
  );
}

function InterviewModal(props: { onClose: () => void }) {
  const { project: p } = useProject();
  const s = interviewScript(p.idea);
  const sections: [string, string[]][] = [
    ["Вступление", s.intro],
    ["Контекст", s.context],
    ["Проблема", s.problem],
    ["Текущие решения", s.currentSolutions],
    ["Деньги", s.money],
    ["Завершение", s.closing],
  ];
  const text = [
    `Скрипт проблемного интервью: ${p.idea.title || p.name}`,
    "",
    ...sections.flatMap(([t, qs]) => [t.toUpperCase(), ...qs.map((q) => `— ${q}`), ""]),
    "ПРАВИЛА",
    ...s.rules.map((r) => `• ${r}`),
  ].join("\n");
  return (
    <Modal title="🎤 Скрипт проблемного интервью" onClose={props.onClose} wide>
      <p className="small text-2">
        По принципам книги «Спроси маму» (The Mom Test): узнаём о реальном прошлом опыте клиента, а не просим оценить идею.
      </p>
      <div className="grid grid-2">
        {sections.map(([t, qs]) => (
          <div key={t} className="card flat">
            <h4 className="mb-8">{t}</h4>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
              {qs.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="callout warn small mt-16">
        <b>Правила:</b>
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          {s.rules.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </div>
      <div className="row mt-16">
        <button className="btn primary" onClick={() => copyText(text)}>
          Копировать скрипт
        </button>
      </div>
    </Modal>
  );
}
