import { completeAi, completeJson } from "../../ai/client";
import { CRITIQUE_PROMPT, SYSTEM_BASE, VALIDATION_PROMPT, VALIDATION_SCHEMA, projectContext } from "../../ai/prompts";
import { hypothesisTemplate, recommendExperiments } from "../../core/experiments";
import { fmtPercent } from "../../core/format";
import { conservativeSam } from "../../core/market";
import { newId } from "../../core/random";
import type { CriterionId, EvidenceLevel, HypothesisType } from "../../core/types";
import { CRITERIA, DIMENSIONS, EVIDENCE, VERDICTS, ltvCacToScore, marketSizeToScore, type DimensionId } from "../../core/validation";
import { AiButton, AiOutput, useAiTask } from "../components/Ai";
import { RadarChart } from "../components/charts";
import { Badge, Card, PageHeader, Progress, ScoreSelector, toast } from "../components/ui";
import { useProject } from "../hooks";
import { navigate } from "../router";

const CRITERION_HYPOTHESIS: Partial<Record<CriterionId, HypothesisType>> = {
  problem_pain: "problem",
  problem_frequency: "problem",
  willingness_to_pay: "wtp",
  market_size: "segment",
  differentiation: "solution",
  unit_economics: "retention",
  go_to_market: "channel",
  mvp_feasibility: "solution",
  scalability: "operations",
};

export function ValidationPage() {
  const { project: p, analysis: a, update, money } = useProject();
  const v = a.validation;
  const verdict = VERDICTS[v.verdict];
  const critique = useAiTask();
  const scoring = useAiTask();

  const setAnswer = (id: CriterionId, patch: { score?: number; evidence?: EvidenceLevel; note?: string }) =>
    update((d) => {
      const prev = d.validation[id] ?? { score: 3, evidence: "guess" as EvidenceLevel };
      d.validation[id] = { ...prev, ...patch };
    });

  const sam = conservativeSam(a.market);
  const autoFill = () => {
    update((d) => {
      if (sam > 0) d.validation.market_size = { score: marketSizeToScore(sam), evidence: "research", note: `SAM ≈ ${money(sam)} (расчёт)` };
      d.validation.unit_economics = {
        score: ltvCacToScore(a.unit.ltvToCac),
        evidence: d.validation.unit_economics?.evidence ?? "guess",
        note: `LTV/CAC = ${a.unit.ltvToCac.toFixed(1)} (расчёт)`,
      };
    });
    toast("Оценки рынка и юнит-экономики подставлены из расчётов");
  };

  const addHypothesis = (criterionId: CriterionId) => {
    const type = CRITERION_HYPOTHESIS[criterionId] ?? "solution";
    const c = CRITERIA.find((x) => x.id === criterionId)!;
    update(
      (d) =>
        void d.hypotheses.push({
          id: newId("hyp"),
          statement: hypothesisTemplate(type, p.idea),
          type,
          criterionId,
          impact: Math.min(10, Math.round(c.weight * 3)),
          confidence: 3,
          ease: 6,
          experimentId: recommendExperiments(type, 1)[0]?.id,
          successMetric: "",
          status: "untested",
          result: "",
        }),
    );
    toast("Гипотеза добавлена — уточните её формулировку");
    navigate("experiments");
  };

  const runCritique = () =>
    critique.run(async (signal, onText) => {
      const text = await completeAi({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: CRITIQUE_PROMPT }],
        onText,
        signal,
      });
      update((d) => void (d.ai.critique = text));
      return text;
    });

  const runScoring = async () => {
    const res = await scoring.run((signal) =>
      completeJson<{ scores: { criterion: CriterionId; score: number; rationale: string }[] }>({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: VALIDATION_PROMPT }],
        schema: VALIDATION_SCHEMA,
        signal,
      }),
    );
    if (!res) return;
    let filled = 0;
    update((d) => {
      for (const s of res.scores) {
        if (!CRITERIA.some((c) => c.id === s.criterion)) continue;
        const prev = d.validation[s.criterion];
        if (prev && prev.evidence !== "guess") continue; // never overwrite evidence-backed answers
        d.validation[s.criterion] = {
          score: Math.min(5, Math.max(1, Math.round(s.score))),
          evidence: "guess",
          note: `ИИ: ${s.rationale}`,
        };
        filled++;
      }
    });
    toast(`ИИ оценил критериев: ${filled}. Подтверждённые данными оценки не изменены.`);
  };

  const dims = Object.keys(DIMENSIONS) as DimensionId[];

  return (
    <>
      <PageHeader
        title="Оценка идеи"
        subtitle="14 критериев, на которых проваливаются стартапы. Для каждого укажите оценку и насколько она подтверждена — итог учитывает и силу идеи, и уверенность в ней."
        actions={
          <>
            <button className="btn" onClick={autoFill} title="Подставить оценки рынка и юнит-экономики из расчётов">
              ⚙️ Из расчётов
            </button>
            <AiButton onClick={runScoring} loading={scoring.loading}>
              Оценить с ИИ
            </AiButton>
            <AiButton onClick={runCritique} loading={critique.loading}>
              Адвокат дьявола
            </AiButton>
          </>
        }
      />

      <div className="grid grid-side">
        <div className="stack">
          <AiOutput
            title="Разбор «адвоката дьявола»"
            task={critique.text || critique.loading || critique.error ? critique : { ...critique, text: p.ai.critique ?? "" }}
            onClose={() => {
              critique.reset();
              update((d) => void delete d.ai.critique);
            }}
          />
          {dims.map((dim) => (
            <Card key={dim} title={DIMENSIONS[dim]}>
              <div className="stack" style={{ gap: 18 }}>
                {CRITERIA.filter((c) => c.dimension === dim).map((c) => {
                  const ans = p.validation[c.id];
                  const result = v.results.find((r) => r.criterion.id === c.id)!;
                  return (
                    <div key={c.id} className="stack" style={{ gap: 8 }}>
                      <div className="row-between" style={{ alignItems: "flex-start" }}>
                        <div style={{ flex: "1 1 280px", minWidth: 0 }}>
                          <div className="row">
                            <b>{c.name}</b>
                            <span className="muted tiny">вес {c.weight}</span>
                            {result.effectiveEvidence === "data" && ans?.evidence !== "data" && (
                              <Badge tone="good" title="Связанная гипотеза подтверждена экспериментом">
                                ✓ подтверждено экспериментом
                              </Badge>
                            )}
                          </div>
                          <div className="small text-2">{c.question}</div>
                        </div>
                        <ScoreSelector label={c.name} value={ans?.score} onChange={(score) => setAnswer(c.id, { score })} />
                      </div>
                      <div className="small muted">
                        1 — {c.anchors[0]} · 3 — {c.anchors[1]} · 5 — {c.anchors[2]}
                      </div>
                      {ans && (
                        <div className="row">
                          <div className="chips">
                            {(Object.keys(EVIDENCE) as EvidenceLevel[]).map((e) => (
                              <button
                                key={e}
                                className={`chip ${ans.evidence === e ? "on" : ""}`}
                                title={EVIDENCE[e].hint}
                                aria-pressed={ans.evidence === e}
                                onClick={() => setAnswer(c.id, { evidence: e })}
                              >
                                {EVIDENCE[e].label}
                              </button>
                            ))}
                          </div>
                          <input
                            className="input"
                            style={{ flex: "1 1 220px" }}
                            aria-label={`Комментарий: ${c.name}`}
                            placeholder="Обоснование или источник данных"
                            value={ans.note ?? ""}
                            onChange={(e) => setAnswer(c.id, { note: e.target.value })}
                          />
                          <button className="btn sm ghost" onClick={() => update((d) => void delete d.validation[c.id])}>
                            Сбросить
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          ))}
        </div>

        <div className="stack sticky-side">
          <Card>
            <div className="row-between">
              <div>
                <div className="small text-2">Итоговая оценка</div>
                <div className="hero-number">{v.answered ? Math.round(v.score) : "—"}</div>
              </div>
              <Badge tone={verdict.tone}>{verdict.label}</Badge>
            </div>
            <p className="small text-2 mt-8">{verdict.description}</p>
            <div className="mt-8">
              <div className="row-between small">
                <span>Уверенность в оценке</span>
                <b>{fmtPercent(v.confidence)}</b>
              </div>
              <Progress value={v.confidence} label="Уверенность в оценке" />
              <div className="tiny muted mt-8">
                Оценено {v.answered} из {v.total}. Уверенность растёт, когда оценки подтверждены данными и экспериментами.
              </div>
            </div>
          </Card>

          <Card title="Профиль идеи">
            <RadarChart ariaLabel="Оценка по измерениям" axes={v.dimensions.map((d) => ({ label: d.label, value: d.score }))} size={300} />
          </Card>

          {v.redFlags.length > 0 && (
            <Card title="⛔ Красные флаги">
              <ul className="list-plain">
                {v.redFlags.map((f) => (
                  <li key={f} className="check-item error small">
                    {f}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {v.weaknesses.length > 0 && (
            <Card title="Что усилить в первую очередь">
              <ul className="list-plain">
                {v.weaknesses.slice(0, 3).map((w) => (
                  <li key={w.criterion.id} className="check-item small">
                    <div>
                      <b>{w.criterion.name}</b>
                      <div className="text-2">{w.criterion.advice}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {v.riskiestAssumptions.length > 0 && (
            <Card title="Самые рискованные допущения" subtitle="Высокая оценка держится только на предположении — проверьте это первым.">
              <ul className="list-plain">
                {v.riskiestAssumptions.map((c) => (
                  <li key={c.id} className="check-item warning small">
                    <span style={{ flex: 1 }}>{c.name}</span>
                    <button className="btn sm" onClick={() => addHypothesis(c.id)}>
                      → Гипотеза
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
