import { useState } from "react";
import { completeJson } from "../../ai/client";
import { RISKS_PROMPT, RISKS_SCHEMA, SYSTEM_BASE, projectContext } from "../../ai/prompts";
import { PREMORTEM_REASONS, RISK_CATEGORIES, RISK_LIBRARY } from "../../core/knowledge/library";
import { newId } from "../../core/random";
import { RISK_LEVEL_LABELS, riskLevel, riskScore, suggestSwot } from "../../core/risks";
import type { Risk, RiskCategory, Swot } from "../../core/types";
import { AiButton, useAiTask } from "../components/Ai";
import { EditableTable } from "../components/EditableTable";
import { Badge, Card, Modal, PageHeader, toast, type Tone } from "../components/ui";
import { useProject } from "../hooks";

const LEVEL_TONE: Record<string, Tone> = { critical: "bad", high: "warn", medium: "ok", low: "muted" };
const CELL_BG = (p: number, i: number) => {
  const s = p * i;
  return s >= 15 ? "var(--bad-soft)" : s >= 10 ? "var(--warn-soft)" : s >= 5 ? "var(--accent-soft)" : "var(--surface-2)";
};

const SWOT_META: { key: keyof Swot; title: string; hint: string }[] = [
  { key: "strengths", title: "💪 Сильные стороны", hint: "Внутренние преимущества" },
  { key: "weaknesses", title: "🩹 Слабые стороны", hint: "Внутренние ограничения" },
  { key: "opportunities", title: "🚀 Возможности", hint: "Внешние факторы роста" },
  { key: "threats", title: "⚡ Угрозы", hint: "Внешние опасности" },
];

export function RisksPage() {
  const { project: p, analysis: a, update } = useProject();
  const [library, setLibrary] = useState(false);
  const [premortem, setPremortem] = useState<string[]>([]);
  const ai = useAiTask();
  const sorted = [...p.risks].sort((x, y) => riskScore(y) - riskScore(x));

  const addRisks = (items: Omit<Risk, "id">[]) => {
    update((d) => {
      const titles = new Set(d.risks.map((r) => r.title.toLowerCase()));
      for (const r of items) if (!titles.has(r.title.toLowerCase())) d.risks.push({ ...r, id: newId("risk") });
    });
  };

  const findWithAi = async () => {
    const res = await ai.run((signal) =>
      completeJson<{ risks: Omit<Risk, "id">[] }>({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: RISKS_PROMPT }],
        schema: RISKS_SCHEMA,
        signal,
      }),
    );
    if (!res) return;
    const clamp = (v: number) => Math.min(5, Math.max(1, Math.round(v)));
    addRisks(res.risks.map((r) => ({ ...r, probability: clamp(r.probability), impact: clamp(r.impact) })));
    toast(`ИИ добавил рисков: ${res.risks.length}`);
  };

  return (
    <>
      <PageHeader
        title="Риски и SWOT"
        subtitle="Риски, о которых вы знаете, можно снизить. Опасны те, о которых вы не подумали — поэтому здесь есть библиотека типовых рисков и пре-мортем."
        actions={
          <>
            <button className="btn" onClick={() => setLibrary(true)}>
              📚 Библиотека рисков
            </button>
            <AiButton onClick={findWithAi} loading={ai.loading}>
              Найти риски с ИИ
            </AiButton>
          </>
        }
      />

      <div className="stack">
        <div className="grid grid-side">
          <Card title="Реестр рисков" subtitle="Вероятность и влияние — от 1 до 5. Риски с оценкой ≥ 10 требуют плана снижения.">
            <EditableTable<Risk>
              rows={p.risks}
              onChange={(rows) => update((d) => void (d.risks = rows))}
              newRow={() => ({ id: newId("risk"), title: "", category: "market", probability: 3, impact: 3, mitigation: "" })}
              addLabel="Добавить риск"
              empty="Рисков пока нет — добавьте из библиотеки или найдите с ИИ."
              columns={[
                { key: "title", label: "Риск", kind: "textarea", width: 220 },
                {
                  key: "category",
                  label: "Категория",
                  kind: "select",
                  width: 150,
                  options: (Object.keys(RISK_CATEGORIES) as RiskCategory[]).map((c) => ({ value: c, label: RISK_CATEGORIES[c] })),
                },
                { key: "probability", label: "Вер.", kind: "number", width: 70, min: 1, max: 5 },
                { key: "impact", label: "Влияние", kind: "number", width: 70, min: 1, max: 5 },
                { key: "mitigation", label: "Как снижаем", kind: "textarea", width: 240 },
              ]}
              extra={(r) => {
                const level = riskLevel(riskScore(r));
                return (
                  <div className="stack" style={{ gap: 4, alignItems: "flex-start" }}>
                    <span className="muted tiny">#{p.risks.indexOf(r) + 1}</span>
                    <Badge tone={LEVEL_TONE[level]}>{RISK_LEVEL_LABELS[level]}</Badge>
                  </div>
                );
              }}
            />
          </Card>

          <div className="stack">
            <Card title="Матрица рисков">
              <div className="risk-matrix" role="img" aria-label="Матрица рисков: вероятность по вертикали, влияние по горизонтали">
                {[5, 4, 3, 2, 1].map((prob) => (
                  <div key={prob} style={{ display: "contents" }}>
                    <div className="rm-axis">{prob}</div>
                    {[1, 2, 3, 4, 5].map((imp) => {
                      const here = p.risks.filter((r) => r.probability === prob && r.impact === imp);
                      return (
                        <div key={imp} className="rm-cell" style={{ background: CELL_BG(prob, imp) }}>
                          {here.map((r) => (
                            <span key={r.id} className="rm-dot" title={r.title}>
                              {p.risks.indexOf(r) + 1}
                            </span>
                          ))}
                        </div>
                      );
                    })}
                  </div>
                ))}
                <div />
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="rm-axis">
                    {i}
                  </div>
                ))}
              </div>
              <div className="row-between tiny muted mt-8">
                <span>↑ вероятность</span>
                <span>влияние →</span>
              </div>
              <div className="small text-2 mt-8">
                <b>Топ рисков:</b>
                {sorted.slice(0, 6).map((r) => (
                  <div key={r.id}>
                    #{p.risks.indexOf(r) + 1} {r.title || "Без названия"} <span className="muted">({riskScore(r)})</span>
                  </div>
                ))}
              </div>
            </Card>
            <Card>
              <div className="grid grid-2" style={{ gap: 8 }}>
                {(["critical", "high", "medium", "low"] as const).map((l) => (
                  <div key={l} className="small">
                    <Badge tone={LEVEL_TONE[l]}>{RISK_LEVEL_LABELS[l]}</Badge> <b className="num">{a.risks.byLevel[l]}</b>
                  </div>
                ))}
              </div>
              {a.risks.unmitigated.length > 0 && (
                <div className="callout warn small mt-16">Без плана снижения: {a.risks.unmitigated.map((r) => r.title).join("; ")}</div>
              )}
            </Card>
          </div>
        </div>

        <Card
          title="SWOT-анализ"
          subtitle="Каждый пункт — с новой строки."
          actions={
            <button
              className="btn sm"
              onClick={() => {
                const s = suggestSwot(p, a.validation, a.unit, a.market);
                update((d) => {
                  for (const m of SWOT_META) d.swot[m.key] = [...new Set([...d.swot[m.key], ...s[m.key]])];
                });
                toast("Добавлены пункты на основе оценки, рынка и юнит-экономики");
              }}
            >
              ⚙️ Предложить из анализа
            </button>
          }
        >
          <div className="grid grid-2">
            {SWOT_META.map((m) => (
              <div key={m.key} className="canvas-block" style={{ minHeight: 170 }}>
                <div className="cb-title">{m.title}</div>
                <div className="cb-hint">{m.hint}</div>
                <textarea
                  aria-label={m.title}
                  value={p.swot[m.key].join("\n")}
                  onChange={(e) => update((d) => void (d.swot[m.key] = e.target.value.split("\n")))}
                  onBlur={() => update((d) => void (d.swot[m.key] = d.swot[m.key].map((x) => x.trim()).filter(Boolean)))}
                />
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="Пре-мортем"
          subtitle="Представьте: прошло 18 месяцев, и проект провалился. Отметьте причины, которые кажутся вам реальными для вашего проекта, — и превратите их в риски с планом защиты."
          actions={
            <button
              className="btn sm primary"
              disabled={!premortem.length}
              onClick={() => {
                addRisks(premortem.map((title) => ({ title, category: "market", probability: 3, impact: 4, mitigation: "" })));
                setPremortem([]);
                toast("Причины провала добавлены в реестр рисков");
              }}
            >
              Добавить в реестр ({premortem.length})
            </button>
          }
        >
          <div className="grid grid-2" style={{ gap: 8 }}>
            {PREMORTEM_REASONS.map((r) => (
              <label key={r} className="check-item small" style={{ cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={premortem.includes(r)}
                  onChange={(e) => setPremortem(e.target.checked ? [...premortem, r] : premortem.filter((x) => x !== r))}
                />
                {r}
              </label>
            ))}
          </div>
        </Card>
      </div>

      {library && (
        <Modal title="Библиотека типовых рисков" onClose={() => setLibrary(false)} wide>
          <LibraryPicker
            existing={new Set(p.risks.map((r) => r.title))}
            onAdd={(items) => {
              addRisks(items);
              setLibrary(false);
              toast(`Добавлено рисков: ${items.length}`);
            }}
          />
        </Modal>
      )}
    </>
  );
}

function LibraryPicker(props: { existing: Set<string>; onAdd: (items: Omit<Risk, "id">[]) => void }) {
  const [picked, setPicked] = useState<string[]>([]);
  const groups = Object.keys(RISK_CATEGORIES) as RiskCategory[];
  return (
    <div className="stack">
      {groups.map((g) => {
        const items = RISK_LIBRARY.filter((r) => r.category === g);
        if (!items.length) return null;
        return (
          <div key={g}>
            <h4 className="mb-8">{RISK_CATEGORIES[g]}</h4>
            <div className="stack" style={{ gap: 6 }}>
              {items.map((r) => {
                const has = props.existing.has(r.title);
                return (
                  <label key={r.title} className="check-item small" style={{ cursor: has ? "default" : "pointer", opacity: has ? 0.6 : 1 }}>
                    <input
                      type="checkbox"
                      disabled={has}
                      checked={has || picked.includes(r.title)}
                      onChange={(e) => setPicked(e.target.checked ? [...picked, r.title] : picked.filter((x) => x !== r.title))}
                    />
                    <div>
                      <b>{r.title}</b>
                      <div className="text-2">{r.mitigation}</div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
      <div className="row">
        <button
          className="btn primary"
          disabled={!picked.length}
          onClick={() => props.onAdd(RISK_LIBRARY.filter((r) => picked.includes(r.title)))}
        >
          Добавить выбранные ({picked.length})
        </button>
      </div>
    </div>
  );
}
