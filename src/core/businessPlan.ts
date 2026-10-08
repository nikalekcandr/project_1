import type { ProjectAnalysis } from "./analysis";
import { LEAN_BLOCKS } from "./canvas";
import { getExperiment, sortByPriority } from "./experiments";
import { SCENARIOS, applyScenario, computeFinance } from "./finance";
import { fmtMoney, fmtMonths, fmtNumber, fmtPercent, niceCeil } from "./format";
import { getIndustry } from "./knowledge/industries";
import { getModel } from "./knowledge/businessModels";
import { HYPOTHESIS_TYPES, RISK_CATEGORIES, SEGMENTS } from "./knowledge/library";
import { conservativeSom } from "./market";
import type { MonteCarloResult } from "./monteCarlo";
import { RISK_LEVEL_LABELS, riskLevel, riskScore } from "./risks";
import type { PlanSectionId, Project } from "./types";
import { VERDICTS } from "./validation";

export const PLAN_SECTIONS: { id: PlanSectionId; title: string }[] = [
  { id: "summary", title: "1. Резюме проекта" },
  { id: "problemSolution", title: "2. Проблема и решение" },
  { id: "market", title: "3. Рынок и целевая аудитория" },
  { id: "competition", title: "4. Конкуренты и позиционирование" },
  { id: "model", title: "5. Бизнес-модель и юнит-экономика" },
  { id: "marketing", title: "6. Маркетинг и продажи" },
  { id: "operations", title: "7. Команда и операционный план" },
  { id: "finance", title: "8. Финансовый план" },
  { id: "risks", title: "9. Риски и их снижение" },
  { id: "roadmap", title: "10. Проверка гипотез и дорожная карта" },
  { id: "investment", title: "11. Потребность в инвестициях" },
];

const table = (headers: string[], rows: (string | number)[][]) =>
  [`| ${headers.join(" | ")} |`, `| ${headers.map(() => "---").join(" | ")} |`, ...rows.map((r) => `| ${r.join(" | ")} |`)].join("\n");

const clean = (text: string | undefined, fallback = "_Не заполнено_") => {
  const t = (text ?? "").trim();
  return t ? t.replace(/\|/g, "/") : fallback;
};

export function fundingAsk(project: Project, analysis: ProjectAnalysis): number {
  if (project.plan.fundingAsk != null) return project.plan.fundingAsk;
  const external = Math.max(0, analysis.finance.fundingNeed - project.finance.startingCash);
  return niceCeil(external * 1.2);
}

export interface PlanContext {
  project: Project;
  analysis: ProjectAnalysis;
  monteCarlo?: MonteCarloResult | null;
}

type SectionBuilder = (ctx: PlanContext) => string;

const sections: Record<PlanSectionId, SectionBuilder> = {
  summary: ({ project: p, analysis: a, monteCarlo }) => {
    const money = (v: number) => fmtMoney(v, p.currency);
    const y = a.finance.years;
    const lines = [
      `**${clean(p.idea.title, p.name)}** — ${clean(p.idea.oneLiner, "")}`,
      "",
      `- **Проблема:** ${clean(p.idea.problem)}`,
      `- **Решение:** ${clean(p.idea.solution)}`,
      `- **Целевая аудитория:** ${clean(p.idea.audience)} (${SEGMENTS[p.idea.segment]})`,
      `- **Рынок:** SAM ${money(a.market.bottomUp.sam || a.market.topDown.sam)}, реалистичная доля (SOM) ${money(conservativeSom(a.market))} в год`,
      `- **Бизнес-модель:** ${getModel(p.idea.modelId)?.name ?? "—"}; LTV/CAC = ${fmtNumber(a.unit.ltvToCac, 1)}, окупаемость клиента ${fmtMonths(a.unit.paybackMonths, true)}`,
      `- **Финансы:** выручка ${y.map((r) => `год ${r.year} — ${money(r.revenue)}`).join(", ")}`,
      `- **Безубыточность:** ${a.finance.breakEvenMonth ? `${a.finance.breakEvenMonth}-й месяц` : "не достигается на горизонте модели"}`,
      `- **Потребность в инвестициях:** ${money(fundingAsk(p, a))}`,
      `- **Оценка идеи:** ${Math.round(a.validation.score)}/100 — ${VERDICTS[a.validation.verdict].label} (уверенность ${fmtPercent(a.validation.confidence)})`,
    ];
    if (monteCarlo) {
      lines.push(
        `- **Вероятность выхода в безубыточность** (Монте-Карло, ${fmtNumber(monteCarlo.runs)} сценариев): ${fmtPercent(monteCarlo.probBreakEven)}`,
      );
    }
    return lines.join("\n");
  },

  problemSolution: ({ project: p }) =>
    [
      "### Проблема",
      clean(p.lean.problem || p.idea.problem),
      "",
      "### Как клиенты решают проблему сейчас",
      clean(p.lean.existingAlternatives),
      "",
      "### Решение",
      clean(p.lean.solution || p.idea.solution),
      "",
      "### Уникальное ценностное предложение",
      clean(p.lean.uniqueValueProposition || p.idea.oneLiner),
      "",
      "### Скрытое преимущество",
      clean(p.lean.unfairAdvantage),
    ].join("\n"),

  market: ({ project: p, analysis: a }) => {
    const money = (v: number) => fmtMoney(v, p.currency);
    const industry = getIndustry(p.idea.industryId);
    return [
      `**География:** ${clean(p.market.geography)}${industry ? `. **Отрасль:** ${industry.name}` : ""}`,
      "",
      `**Сегменты клиентов:** ${clean(p.lean.customerSegments || p.idea.audience)}`,
      "",
      `**Ранние последователи:** ${clean(p.lean.earlyAdopters)}`,
      "",
      "### Объём рынка",
      table(
        ["Метод", "TAM", "SAM", "SOM"],
        [
          ["Сверху вниз", money(a.market.topDown.tam), money(a.market.topDown.sam), money(a.market.topDown.som)],
          ["Снизу вверх", money(a.market.bottomUp.tam), money(a.market.bottomUp.sam), money(a.market.bottomUp.som)],
        ],
      ),
      "",
      ...a.market.warnings.map((w) => `> ⚠️ ${w}`),
    ].join("\n");
  },

  competition: ({ project: p }) => {
    const kinds = { direct: "Прямой", indirect: "Косвенный", substitute: "Заменитель" } as const;
    if (!p.competitors.length) return "_Конкуренты не добавлены._";
    return [
      table(
        ["Конкурент", "Тип", "Цена", "Сильные стороны", "Слабые стороны"],
        p.competitors.map((c) => [clean(c.name), kinds[c.kind], clean(c.price, "—"), clean(c.strengths, "—"), clean(c.weaknesses, "—")]),
      ),
      "",
      `**Позиционирование:** по осям «${p.positioning.xLabel.replace(" →", "")}» и «${p.positioning.yLabel.replace(" →", "")}» проект занимает позицию (${p.positioning.selfX}; ${p.positioning.selfY}) из 10.`,
    ].join("\n");
  },

  model: ({ project: p, analysis: a }) => {
    const money = (v: number) => fmtMoney(v, p.currency);
    const model = getModel(p.idea.modelId);
    return [
      model ? `**Модель:** ${model.name}. ${model.howItMakesMoney}` : "",
      "",
      "### Lean Canvas",
      table(
        ["Блок", "Содержание"],
        LEAN_BLOCKS.map((b) => [b.title, clean(p.lean[b.id], "—").replace(/\n/g, "<br>")]),
      ),
      "",
      "### Юнит-экономика",
      table(
        ["Показатель", "Значение"],
        [
          ["Средний доход с клиента в месяц (ARPU)", money(a.unit.arpu)],
          ["Валовая маржа", fmtPercent(p.unit.grossMargin)],
          ["Отток в месяц", fmtPercent(p.unit.monthlyChurn, 1)],
          ["Срок жизни клиента", fmtMonths(a.unit.lifetimeMonths)],
          ["LTV (по валовой прибыли)", money(a.unit.ltv)],
          ["CAC", money(a.unit.cac)],
          ["LTV/CAC", fmtNumber(a.unit.ltvToCac, 1)],
          ["Окупаемость клиента", fmtMonths(a.unit.paybackMonths, true)],
        ],
      ),
      "",
      `> ${a.unit.verdict}`,
    ].join("\n");
  },

  marketing: ({ project: p, analysis: a }) => {
    const money = (v: number) => fmtMoney(v, p.currency);
    const f = p.finance;
    return [
      `**Каналы привлечения:** ${clean(p.lean.channels || p.bmc.channels)}`,
      "",
      `**Отношения с клиентами:** ${clean(p.bmc.customerRelationships)}`,
      "",
      table(
        ["Параметр", "Значение"],
        [
          ["Стартовый маркетинговый бюджет", `${money(f.marketingStart)}/мес`],
          ["Рост бюджета", `${fmtPercent(f.marketingGrowth)} в месяц до ${money(f.marketingMax)}/мес`],
          ["Стоимость привлечения клиента (CAC)", money(f.cac)],
          ["Органический приток на старте", `${fmtNumber(f.organicStart)} клиентов/мес`],
          ["Клиентов в конце горизонта", fmtNumber(a.finance.endCustomers)],
        ],
      ),
    ].join("\n");
  },

  operations: ({ project: p }) => {
    const money = (v: number) => fmtMoney(v, p.currency, false);
    return [
      `**Ключевые виды деятельности:** ${clean(p.bmc.keyActivities)}`,
      "",
      `**Ключевые ресурсы:** ${clean(p.bmc.keyResources)}`,
      "",
      `**Ключевые партнёры:** ${clean(p.bmc.keyPartners)}`,
      "",
      "### Команда",
      p.finance.team.length
        ? table(
            ["Роль", "Кол-во", "Зарплата/мес", "С месяца"],
            p.finance.team.map((m) => [clean(m.role), m.count, money(m.salary), m.startMonth]),
          )
        : "_Команда не указана._",
    ].join("\n");
  },

  finance: ({ project: p, analysis: a, monteCarlo }) => {
    const money = (v: number) => fmtMoney(v, p.currency);
    const fin = a.finance;
    const scenarioRows = SCENARIOS.map((s) => {
      const r = computeFinance(applyScenario(p.finance, s));
      return [
        s.label,
        money(r.years[r.years.length - 1]?.revenue ?? 0),
        r.breakEvenMonth ? `${r.breakEvenMonth}-й мес.` : "не достигается",
        money(r.fundingNeed),
        money(r.npv),
      ];
    });
    const parts = [
      table(
        ["Показатель", ...fin.years.map((y) => `Год ${y.year}`)],
        [
          ["Выручка", ...fin.years.map((y) => money(y.revenue))],
          ["Валовая прибыль", ...fin.years.map((y) => money(y.grossProfit))],
          ["Маркетинг", ...fin.years.map((y) => money(y.marketing))],
          ["ФОТ", ...fin.years.map((y) => money(y.payroll))],
          ["Прочие расходы", ...fin.years.map((y) => money(y.opex))],
          ["EBITDA", ...fin.years.map((y) => money(y.ebitda))],
          ["Чистая прибыль", ...fin.years.map((y) => money(y.netIncome))],
          ["Деньги на конец года", ...fin.years.map((y) => money(y.endCash))],
          ["Клиентов на конец года", ...fin.years.map((y) => fmtNumber(y.endCustomers))],
        ],
      ),
      "",
      table(
        ["Ключевая метрика", "Значение"],
        [
          ["Операционная безубыточность", fin.breakEvenMonth ? `${fin.breakEvenMonth}-й месяц` : "не достигается"],
          ["Пиковая потребность в деньгах", money(fin.fundingNeed)],
          ["Минимальный остаток денег", `${money(fin.minCash)} (месяц ${fin.minCashMonth})`],
          ["Окупаемость вложений", fin.paybackMonth ? `${fin.paybackMonth}-й месяц` : "за горизонтом модели"],
          ["NPV (ставка " + fmtPercent(p.finance.discountRateYear) + ")", money(fin.npv)],
          ["IRR", fin.irrAnnual === null ? "—" : fmtPercent(fin.irrAnnual)],
          ["MRR на конец горизонта", money(fin.endMrr)],
        ],
      ),
      "",
      "### Сценарии",
      table(["Сценарий", "Выручка последнего года", "Безубыточность", "Потребность в деньгах", "NPV"], scenarioRows),
    ];
    if (monteCarlo) {
      parts.push(
        "",
        `### Анализ рисков методом Монте-Карло (${fmtNumber(monteCarlo.runs)} сценариев)`,
        table(
          ["Метрика", "P10 (плохо)", "P50 (медиана)", "P90 (хорошо)"],
          [
            ["Потребность в деньгах", money(monteCarlo.fundingNeed.p90), money(monteCarlo.fundingNeed.p50), money(monteCarlo.fundingNeed.p10)],
            ["NPV", money(monteCarlo.npv.p10), money(monteCarlo.npv.p50), money(monteCarlo.npv.p90)],
            ["MRR на конец горизонта", money(monteCarlo.endMrr.p10), money(monteCarlo.endMrr.p50), money(monteCarlo.endMrr.p90)],
          ],
        ),
        "",
        `Вероятность выйти в безубыточность на горизонте модели: **${fmtPercent(monteCarlo.probBreakEven)}**; вероятность, что запланированного финансирования хватит: **${fmtPercent(monteCarlo.probFullyFunded)}**; вероятность положительного NPV: **${fmtPercent(monteCarlo.npv.probPositive)}**.`,
      );
    }
    return parts.join("\n");
  },

  risks: ({ project: p }) => {
    const sorted = [...p.risks].sort((a, b) => riskScore(b) - riskScore(a));
    const swot = p.swot;
    const list = (xs: string[]) => (xs.length ? xs.map((x) => `- ${x}`).join("\n") : "- —");
    return [
      sorted.length
        ? table(
            ["Риск", "Категория", "Уровень", "Меры снижения"],
            sorted.map((r) => [clean(r.title), RISK_CATEGORIES[r.category], `${RISK_LEVEL_LABELS[riskLevel(riskScore(r))]} (${r.probability}×${r.impact})`, clean(r.mitigation, "—")]),
          )
        : "_Риски не добавлены._",
      "",
      "### SWOT-анализ",
      "**Сильные стороны**",
      list(swot.strengths),
      "",
      "**Слабые стороны**",
      list(swot.weaknesses),
      "",
      "**Возможности**",
      list(swot.opportunities),
      "",
      "**Угрозы**",
      list(swot.threats),
    ].join("\n");
  },

  roadmap: ({ project: p }) => {
    const statuses = { untested: "Не проверена", running: "В работе", validated: "✅ Подтверждена", invalidated: "❌ Опровергнута" } as const;
    const hyps = sortByPriority(p.hypotheses);
    return [
      "### Ключевые гипотезы",
      hyps.length
        ? table(
            ["Гипотеза", "Тип", "Эксперимент", "Критерий успеха", "Статус"],
            hyps.map((h) => [clean(h.statement), HYPOTHESIS_TYPES[h.type].label, getExperiment(h.experimentId)?.name ?? "—", clean(h.successMetric, "—"), statuses[h.status]]),
          )
        : "_Гипотезы не добавлены._",
      "",
      "### Дорожная карта",
      p.plan.milestones.length
        ? table(
            ["Месяц", "Веха", "Измеримый результат"],
            [...p.plan.milestones].sort((a, b) => a.month - b.month).map((m) => [m.month, clean(m.title), clean(m.metric, "—")]),
          )
        : "_Вехи не добавлены._",
    ].join("\n");
  },

  investment: ({ project: p, analysis: a }) => {
    const money = (v: number) => fmtMoney(v, p.currency);
    const ask = fundingAsk(p, a);
    const u = p.plan.useOfFunds;
    const total = u.product + u.marketing + u.team + u.reserve || 1;
    return [
      `**Запрашиваемая сумма:** ${money(ask)}`,
      "",
      `Собственные средства основателей: ${money(p.finance.startingCash)}. Пиковая потребность бизнеса в деньгах по базовому сценарию: ${money(a.finance.fundingNeed)}.`,
      "",
      table(
        ["Направление", "Доля", "Сумма"],
        [
          ["Продукт и разработка", fmtPercent(u.product / total), money((ask * u.product) / total)],
          ["Маркетинг и продажи", fmtPercent(u.marketing / total), money((ask * u.marketing) / total)],
          ["Команда", fmtPercent(u.team / total), money((ask * u.team) / total)],
          ["Резерв", fmtPercent(u.reserve / total), money((ask * u.reserve) / total)],
        ],
      ),
    ].join("\n");
  },
};

export function buildSection(id: PlanSectionId, ctx: PlanContext): string {
  const override = ctx.project.plan.overrides[id];
  return override?.trim() ? override : sections[id](ctx);
}

export function buildBusinessPlan(ctx: PlanContext): string {
  const p = ctx.project;
  const date = new Date().toLocaleDateString("ru-RU", { year: "numeric", month: "long", day: "numeric" });
  const header = [`# Бизнес-план: ${clean(p.idea.title, p.name)}`, "", `_Подготовлено в BizForge · ${date}_`].join("\n");
  const body = PLAN_SECTIONS.map((s) => `## ${s.title}\n\n${buildSection(s.id, ctx)}`).join("\n\n");
  return `${header}\n\n${body}\n`;
}
