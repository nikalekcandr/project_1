import { useState } from "react";
import { completeJson } from "../../ai/client";
import { LEAN_PROMPT, LEAN_SCHEMA, SYSTEM_BASE, projectContext } from "../../ai/prompts";
import { BMC_BLOCKS, LEAN_BLOCKS, leanToBmc, type CanvasBlock } from "../../core/canvas";
import { defaultUnit } from "../../core/factory";
import { fmtMoney, fmtPercent } from "../../core/format";
import { BUSINESS_MODELS, getModel, type BusinessModelPattern } from "../../core/knowledge/businessModels";
import type { CanvasData, LeanBlockId } from "../../core/types";
import { AiButton, useAiTask } from "../components/Ai";
import { Badge, Card, PageHeader, Progress, Tabs, toast } from "../components/ui";
import { useProject } from "../hooks";

type Tab = "lean" | "bmc" | "library";

function CanvasGrid<K extends string>(props: {
  blocks: CanvasBlock<K>[];
  data: CanvasData<K>;
  onChange: (id: K, text: string) => void;
  className: string;
}) {
  return (
    <div className={props.className}>
      {props.blocks.map((b) => {
        const filled = (props.data[b.id] ?? "").trim().length > 0;
        return (
          <div key={b.id} className="canvas-block" style={{ gridArea: b.area }}>
            <div className="cb-title">
              <span>{b.title}</span>
              {filled ? <span aria-label="заполнено">✓</span> : <span className="muted" aria-label="пусто">○</span>}
            </div>
            <div className="cb-hint">{b.hint}</div>
            <textarea
              aria-label={b.title}
              value={props.data[b.id] ?? ""}
              placeholder={b.placeholder}
              onChange={(e) => props.onChange(b.id, e.target.value)}
            />
          </div>
        );
      })}
    </div>
  );
}

export function CanvasPage() {
  const { project: p, analysis: a, update } = useProject();
  const [tab, setTab] = useState<Tab>("lean");
  const ai = useAiTask();
  const report = tab === "bmc" ? a.bmc : a.lean;

  const fillWithAi = async () => {
    const res = await ai.run((signal) =>
      completeJson<Record<LeanBlockId, string>>({
        system: `${SYSTEM_BASE}\n\n${projectContext(p, a)}`,
        messages: [{ role: "user", content: LEAN_PROMPT }],
        schema: LEAN_SCHEMA,
        signal,
      }),
    );
    if (!res) return;
    const hasContent = LEAN_BLOCKS.some((b) => (p.lean[b.id] ?? "").trim());
    const overwrite = !hasContent || confirm("Заменить текущее содержимое Lean Canvas вариантом ИИ? «Отмена» — заполнить только пустые блоки.");
    update((d) => {
      for (const b of LEAN_BLOCKS) {
        if (res[b.id] && (overwrite || !(d.lean[b.id] ?? "").trim())) d.lean[b.id] = res[b.id];
      }
    });
    toast("Lean Canvas заполнен с помощью ИИ — проверьте и отредактируйте");
  };

  const applyModel = (m: BusinessModelPattern) => {
    const updateUnit = confirm(
      `Применить модель «${m.name}»?\n\nПустые блоки холстов заполнятся типовыми формулировками.\nНажмите «ОК», чтобы также подставить типовые метрики юнит-экономики и финмодели (чек, маржа, отток, CAC), или «Отмена», чтобы изменить только холсты.`,
    );
    update((d) => {
      d.idea.modelId = m.id;
      for (const [k, v] of Object.entries(m.lean)) {
        const key = k as LeanBlockId;
        if (!(d.lean[key] ?? "").trim()) d.lean[key] = v;
      }
      for (const [k, v] of Object.entries(m.bmc)) {
        const key = k as keyof typeof d.bmc;
        if (!(d.bmc[key] ?? "").trim()) d.bmc[key] = v;
      }
      if (updateUnit) {
        const u = defaultUnit(m);
        d.unit = { ...d.unit, avgCheck: u.avgCheck, purchasesPerMonth: u.purchasesPerMonth, grossMargin: u.grossMargin, monthlyChurn: u.monthlyChurn, cac: u.cac, cacMode: "direct" };
        d.finance.arpu = Math.round(u.avgCheck * u.purchasesPerMonth);
        d.finance.grossMargin = u.grossMargin;
        d.finance.monthlyChurn = u.monthlyChurn;
        d.finance.cac = u.cac;
      }
    });
    toast(`Модель «${m.name}» применена`);
    setTab("lean");
  };

  const current = getModel(p.idea.modelId);

  return (
    <>
      <PageHeader
        title="Бизнес-модель"
        subtitle="Lean Canvas — для стартапа на стадии проверки, Business Model Canvas — для описания работающей модели. Библиотека — 15 проверенных моделей монетизации."
        actions={
          tab !== "library" && (
            <>
              {tab === "bmc" && (
                <button
                  className="btn"
                  onClick={() => {
                    update((d) => {
                      const mapped = leanToBmc(d.lean);
                      for (const [k, v] of Object.entries(mapped)) {
                        const key = k as keyof typeof d.bmc;
                        if (v && !(d.bmc[key] ?? "").trim()) d.bmc[key] = v;
                      }
                    });
                    toast("Пустые блоки заполнены из Lean Canvas");
                  }}
                >
                  ⇄ Перенести из Lean
                </button>
              )}
              {tab === "lean" && (
                <AiButton onClick={fillWithAi} loading={ai.loading}>
                  Заполнить с ИИ
                </AiButton>
              )}
            </>
          )
        }
      />
      <Tabs
        tabs={[
          { id: "lean", label: "Lean Canvas" },
          { id: "bmc", label: "Business Model Canvas" },
          { id: "library", label: "Библиотека моделей" },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab !== "library" ? (
        <div className="stack">
          <Card>
            <div className="row-between">
              <div style={{ flex: "1 1 300px" }}>
                <div className="row-between small">
                  <span>Заполненность холста</span>
                  <b>
                    {report.filled} из {report.total} блоков · {fmtPercent(report.completeness)}
                  </b>
                </div>
                <Progress value={report.completeness} label="Заполненность холста" />
              </div>
              {current && (
                <Badge tone="ok">
                  {current.emoji} {current.name}
                </Badge>
              )}
            </div>
            {report.issues.length > 0 && (
              <ul className="list-plain mt-16">
                {report.issues.map((i) => (
                  <li key={i} className="check-item warning small">
                    <span className="ci-icon">💡</span>
                    {i}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {tab === "lean" ? (
            <CanvasGrid className="canvas-lean" blocks={LEAN_BLOCKS} data={p.lean} onChange={(id, text) => update((d) => void (d.lean[id] = text))} />
          ) : (
            <CanvasGrid className="canvas-bmc" blocks={BMC_BLOCKS} data={p.bmc} onChange={(id, text) => update((d) => void (d.bmc[id] = text))} />
          )}
        </div>
      ) : (
        <div className="grid grid-auto">
          {BUSINESS_MODELS.map((m) => (
            <Card key={m.id} className={m.id === p.idea.modelId ? "accent" : ""}>
              <div className="stack" style={{ gap: 8 }}>
                <div className="row-between">
                  <h3>
                    {m.emoji} {m.name}
                  </h3>
                  {m.id === p.idea.modelId && <Badge tone="ok">Выбрана</Badge>}
                </div>
                <p className="small" style={{ margin: 0 }}>
                  {m.description}
                </p>
                <p className="small text-2" style={{ margin: 0 }}>
                  <b>Как зарабатывает:</b> {m.howItMakesMoney}
                </p>
                <div className="small text-2">
                  <b>Примеры:</b> {m.examples.join(", ")}
                </div>
                <div className="row">
                  <span className="tag">Масштабируемость {"●".repeat(m.scalability)}{"○".repeat(5 - m.scalability)}</span>
                  <span className="tag">Капиталоёмкость {"●".repeat(m.capital)}{"○".repeat(5 - m.capital)}</span>
                  <span className="tag">Скорость денег {"●".repeat(m.speedToRevenue)}{"○".repeat(5 - m.speedToRevenue)}</span>
                </div>
                <div className="small text-2">
                  <b>Типично:</b> чек {fmtMoney(m.defaults.avgCheck)}, маржа {fmtPercent(m.defaults.grossMargin)}, отток{" "}
                  {fmtPercent(m.defaults.monthlyChurn)}/мес
                </div>
                <div className="small text-2">
                  <b>Метрики:</b> {m.keyMetrics.join(", ")}
                </div>
                <div className="small text-2">
                  <b>Риски:</b> {m.risks.join("; ")}
                </div>
                <div>
                  <button className="btn sm primary" onClick={() => applyModel(m)}>
                    Применить к проекту
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
