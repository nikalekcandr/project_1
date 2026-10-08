import { useState } from "react";
import { completeJson } from "../../ai/client";
import { COMPETITORS_SCHEMA, MARKET_PROMPT, MARKET_SCHEMA, SYSTEM_BASE, competitorsPrompt, projectContext } from "../../ai/prompts";
import { fmtNumber } from "../../core/format";
import { conservativeSam } from "../../core/market";
import { newId } from "../../core/random";
import type { Competitor } from "../../core/types";
import { marketSizeToScore } from "../../core/validation";
import { AiButton, useAiTask } from "../components/Ai";
import { BarChart, PositioningMap } from "../components/charts";
import { EditableTable } from "../components/EditableTable";
import { Markdown } from "../components/Markdown";
import { Card, NumberField, PageHeader, TextField, toast } from "../components/ui";
import { useProject } from "../hooks";

interface MarketAi {
  geography: string;
  totalCustomers: number;
  annualSpendPerCustomer: number;
  segmentShare: number;
  obtainableShare: number;
  targetCustomers: number;
  pricePerPurchase: number;
  purchasesPerYear: number;
  reachShare: number;
  conversionShare: number;
  rationale: string;
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, Number(v) || 0));

export function MarketPage() {
  const { project: p, analysis: a, update, money } = useProject();
  const m = a.market;
  const marketAi = useAiTask();
  const compAi = useAiTask();
  const [rationale, setRationale] = useState<string>(p.ai.market ?? "");
  const td = p.market.topDown;
  const bu = p.market.bottomUp;
  const sam = conservativeSam(m);

  const estimateMarket = async () => {
    const r = await marketAi.run((signal) =>
      completeJson<MarketAi>({
        system: `${SYSTEM_BASE}\n\nВалюта проекта: ${p.currency}.\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: MARKET_PROMPT }],
        schema: MARKET_SCHEMA,
        signal,
      }),
    );
    if (!r) return;
    update((d) => {
      d.market = {
        geography: r.geography || d.market.geography,
        topDown: {
          totalCustomers: Math.max(0, r.totalCustomers),
          annualSpendPerCustomer: Math.max(0, r.annualSpendPerCustomer),
          segmentShare: clamp01(r.segmentShare),
          obtainableShare: clamp01(r.obtainableShare),
        },
        bottomUp: {
          targetCustomers: Math.max(0, r.targetCustomers),
          pricePerPurchase: Math.max(0, r.pricePerPurchase),
          purchasesPerYear: Math.max(0, r.purchasesPerYear),
          reachShare: clamp01(r.reachShare),
          conversionShare: clamp01(r.conversionShare),
        },
      };
      d.ai.market = r.rationale;
    });
    setRationale(r.rationale);
    toast("Оценка рынка от ИИ подставлена — проверьте допущения");
  };

  const findCompetitors = async () => {
    const r = await compAi.run((signal) =>
      completeJson<{ competitors: Omit<Competitor, "id">[] }>({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: competitorsPrompt(p.positioning.xLabel, p.positioning.yLabel) }],
        schema: COMPETITORS_SCHEMA,
        signal,
      }),
    );
    if (!r) return;
    update((d) => {
      const names = new Set(d.competitors.map((c) => c.name.toLowerCase()));
      for (const c of r.competitors) {
        if (names.has(c.name.toLowerCase())) continue;
        d.competitors.push({ ...c, id: newId("cmp"), x: Math.min(10, Math.max(0, c.x)), y: Math.min(10, Math.max(0, c.y)) });
      }
    });
    toast("Конкуренты добавлены. Проверьте данные — ИИ может ошибаться в деталях.");
  };

  return (
    <>
      <PageHeader
        title="Рынок и конкуренты"
        subtitle="Считаем объём рынка двумя независимыми способами: если оценки сходятся — им можно доверять. Плюс карта конкурентов и позиционирования."
        actions={
          <AiButton onClick={estimateMarket} loading={marketAi.loading}>
            Оценить рынок с ИИ
          </AiButton>
        }
      />

      <div className="stack">
        <div className="grid grid-2">
          <Card title="Сверху вниз (top-down)" subtitle="От общего числа потенциальных клиентов к вашей доле.">
            <div className="stack" style={{ gap: 12 }}>
              <TextField label="География" value={p.market.geography} onChange={(geography) => update((d) => void (d.market.geography = geography))} />
              <div className="form-grid">
                <NumberField
                  label="Всего потенциальных клиентов"
                  value={td.totalCustomers}
                  digits={0}
                  min={0}
                  onChange={(v) => update((d) => void (d.market.topDown.totalCustomers = v))}
                />
                <NumberField
                  label="Годовые расходы клиента на задачу"
                  kind="money"
                  value={td.annualSpendPerCustomer}
                  min={0}
                  onChange={(v) => update((d) => void (d.market.topDown.annualSpendPerCustomer = v))}
                />
                <NumberField
                  label="Доля вашего сегмента (SAM)"
                  kind="percent"
                  value={td.segmentShare}
                  min={0}
                  max={1}
                  onChange={(v) => update((d) => void (d.market.topDown.segmentShare = v))}
                />
                <NumberField
                  label="Достижимая доля (SOM)"
                  kind="percent"
                  value={td.obtainableShare}
                  min={0}
                  max={1}
                  hint="Реалистично за 3–5 лет: 1–5%"
                  onChange={(v) => update((d) => void (d.market.topDown.obtainableShare = v))}
                />
              </div>
            </div>
          </Card>
          <Card title="Снизу вверх (bottom-up)" subtitle="От конкретных клиентов, цены и ваших каналов.">
            <div className="form-grid">
              <NumberField
                label="Клиентов в целевом сегменте"
                value={bu.targetCustomers}
                digits={0}
                min={0}
                onChange={(v) => update((d) => void (d.market.bottomUp.targetCustomers = v))}
              />
              <NumberField
                label="Цена покупки"
                kind="money"
                value={bu.pricePerPurchase}
                min={0}
                onChange={(v) => update((d) => void (d.market.bottomUp.pricePerPurchase = v))}
              />
              <NumberField
                label="Покупок в год"
                value={bu.purchasesPerYear}
                min={0}
                onChange={(v) => update((d) => void (d.market.bottomUp.purchasesPerYear = v))}
              />
              <NumberField
                label="Охват каналами"
                kind="percent"
                value={bu.reachShare}
                min={0}
                max={1}
                onChange={(v) => update((d) => void (d.market.bottomUp.reachShare = v))}
              />
              <NumberField
                label="Конверсия охваченных"
                kind="percent"
                value={bu.conversionShare}
                min={0}
                max={1}
                onChange={(v) => update((d) => void (d.market.bottomUp.conversionShare = v))}
              />
              <div className="field">
                <span className="field-label">Клиентов в SOM</span>
                <div className="stat-value" style={{ fontSize: 20 }}>
                  {fmtNumber(m.bottomUp.customers)}
                </div>
              </div>
            </div>
          </Card>
        </div>

        <div className="grid grid-2">
          <Card title="TAM · SAM · SOM" subtitle="Общий, доступный и реально достижимый рынок в год.">
            <BarChart
              ariaLabel="Сравнение оценок рынка"
              categories={["TAM", "SAM", "SOM"]}
              series={[
                { name: "Сверху вниз", values: [m.topDown.tam, m.topDown.sam, m.topDown.som], color: "var(--s1)" },
                { name: "Снизу вверх", values: [m.bottomUp.tam, m.bottomUp.sam, m.bottomUp.som], color: "var(--s2)" },
              ]}
              format={(v) => money(v)}
            />
            <div className="table-wrap mt-16">
              <table className="table">
                <thead>
                  <tr>
                    <th>Метод</th>
                    <th className="num">TAM</th>
                    <th className="num">SAM</th>
                    <th className="num">SOM</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Сверху вниз</td>
                    <td className="num">{money(m.topDown.tam)}</td>
                    <td className="num">{money(m.topDown.sam)}</td>
                    <td className="num">{money(m.topDown.som)}</td>
                  </tr>
                  <tr>
                    <td>Снизу вверх</td>
                    <td className="num">{money(m.bottomUp.tam)}</td>
                    <td className="num">{money(m.bottomUp.sam)}</td>
                    <td className="num">{money(m.bottomUp.som)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Выводы">
            <ul className="list-plain">
              {m.warnings.map((w) => (
                <li key={w} className="check-item warning small">
                  <span className="ci-icon">⚠️</span>
                  {w}
                </li>
              ))}
              {m.insights.map((w) => (
                <li key={w} className="check-item ok small">
                  <span className="ci-icon">✅</span>
                  {w}
                </li>
              ))}
              {sam > 0 && (
                <li className="check-item small">
                  <span className="ci-icon">🎯</span>
                  <span style={{ flex: 1 }}>
                    Консервативный SAM {money(sam)} соответствует оценке <b>{marketSizeToScore(sam)}/5</b> по критерию «Размер рынка».
                  </span>
                  <button
                    className="btn sm"
                    onClick={() => {
                      update((d) => void (d.validation.market_size = { score: marketSizeToScore(sam), evidence: "research", note: `SAM ≈ ${money(sam)} (расчёт)` }));
                      toast("Оценка рынка перенесена в «Оценку идеи»");
                    }}
                  >
                    В оценку
                  </button>
                </li>
              )}
              {!m.warnings.length && !m.insights.length && sam <= 0 && (
                <li className="muted small">Заполните параметры рынка — здесь появятся выводы и проверки.</li>
              )}
            </ul>
            {rationale && (
              <details className="disclosure mt-16" open>
                <summary>✨ Допущения ИИ</summary>
                <Markdown text={rationale} className="small mt-8" />
              </details>
            )}
          </Card>
        </div>

        <Card
          title="Конкуренты и альтернативы"
          subtitle="Прямые конкуренты, косвенные решения и заменители (включая «ничего не делать»)."
          actions={
            <AiButton small onClick={findCompetitors} loading={compAi.loading}>
              Найти с ИИ
            </AiButton>
          }
        >
          <EditableTable<Competitor>
            rows={p.competitors}
            onChange={(rows) => update((d) => void (d.competitors = rows))}
            newRow={() => ({ id: newId("cmp"), name: "", kind: "direct", price: "", strengths: "", weaknesses: "", x: 5, y: 5 })}
            addLabel="Добавить конкурента"
            empty="Конкурентов пока нет. «Конкурентов нет» почти всегда значит, что их плохо искали."
            columns={[
              { key: "name", label: "Название", kind: "text", width: 180 },
              {
                key: "kind",
                label: "Тип",
                kind: "select",
                width: 130,
                options: [
                  { value: "direct", label: "Прямой" },
                  { value: "indirect", label: "Косвенный" },
                  { value: "substitute", label: "Заменитель" },
                ],
              },
              { key: "price", label: "Цена", kind: "text", width: 120 },
              { key: "strengths", label: "Сильные стороны", kind: "textarea", width: 200 },
              { key: "weaknesses", label: "Слабые стороны", kind: "textarea", width: 200 },
              { key: "x", label: "X (0–10)", kind: "number", width: 80, min: 0, max: 10 },
              { key: "y", label: "Y (0–10)", kind: "number", width: 80, min: 0, max: 10 },
            ]}
          />
        </Card>

        <Card title="Карта позиционирования" subtitle="Найдите свободную зону, где ваше предложение заметно отличается от остальных.">
          <div className="grid grid-side" style={{ alignItems: "start" }}>
            <PositioningMap
              ariaLabel="Карта позиционирования конкурентов"
              xLabel={p.positioning.xLabel}
              yLabel={p.positioning.yLabel}
              points={[
                ...p.competitors.filter((c) => c.name.trim()).map((c) => ({ id: c.id, label: c.name, x: c.x, y: c.y })),
                { id: "self", label: p.idea.title ? "Мы" : "Наш проект", x: p.positioning.selfX, y: p.positioning.selfY, self: true },
              ]}
            />
            <div className="stack" style={{ gap: 12 }}>
              <TextField label="Ось X" value={p.positioning.xLabel} onChange={(xLabel) => update((d) => void (d.positioning.xLabel = xLabel))} />
              <TextField label="Ось Y" value={p.positioning.yLabel} onChange={(yLabel) => update((d) => void (d.positioning.yLabel = yLabel))} />
              <label className="field">
                <span className="field-label">Наша позиция по X: {p.positioning.selfX}</span>
                <input type="range" min={0} max={10} step={0.5} value={p.positioning.selfX} onChange={(e) => update((d) => void (d.positioning.selfX = Number(e.target.value)))} />
              </label>
              <label className="field">
                <span className="field-label">Наша позиция по Y: {p.positioning.selfY}</span>
                <input type="range" min={0} max={10} step={0.5} value={p.positioning.selfY} onChange={(e) => update((d) => void (d.positioning.selfY = Number(e.target.value)))} />
              </label>
            </div>
          </div>
        </Card>
      </div>
    </>
  );
}
