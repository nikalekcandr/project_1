import { analyzeBmc, analyzeLean, type CanvasReport } from "./canvas";
import { computeFinance, type FinanceResult } from "./finance";
import { fmtMoney, fmtPercent } from "./format";
import { computeMarket, conservativeSam, conservativeSom, type MarketResult } from "./market";
import { summarizeRisks, type RiskSummary } from "./risks";
import type { Project } from "./types";
import { computeUnitEconomics, type UnitEconomicsResult } from "./unitEconomics";
import { evaluateValidation, ltvCacToScore, marketSizeToScore, type ValidationResult } from "./validation";

export type CheckSeverity = "error" | "warning" | "info" | "ok";

export interface ConsistencyCheck {
  id: string;
  severity: CheckSeverity;
  route: string;
  title: string;
  detail: string;
}

export interface ProjectAnalysis {
  validation: ValidationResult;
  unit: UnitEconomicsResult;
  market: MarketResult;
  finance: FinanceResult;
  lean: CanvasReport;
  bmc: CanvasReport;
  risks: RiskSummary;
  checks: ConsistencyCheck[];
  readiness: { score: number; parts: { label: string; value: number; max: number; route: string }[] };
}

const differs = (a: number, b: number, tolerance = 0.2) =>
  a > 0 && b > 0 && Math.abs(a - b) / Math.max(a, b) > tolerance;

export function analyzeProject(project: Project): ProjectAnalysis {
  const validation = evaluateValidation(project.validation, project.hypotheses);
  const unit = computeUnitEconomics(project.unit);
  const market = computeMarket(project.market);
  const finance = computeFinance(project.finance);
  const lean = analyzeLean(project.lean);
  const bmc = analyzeBmc(project.bmc);
  const risks = summarizeRisks(project.risks);
  const checks = runChecks(project, { validation, unit, market, finance, lean });
  const readiness = computeReadiness(project, { validation, unit, market, finance, lean, risks });
  return { validation, unit, market, finance, lean, bmc, risks, checks, readiness };
}

function runChecks(
  p: Project,
  r: Pick<ProjectAnalysis, "validation" | "unit" | "market" | "finance" | "lean">,
): ConsistencyCheck[] {
  const checks: ConsistencyCheck[] = [];
  const money = (v: number) => fmtMoney(v, p.currency);
  const add = (c: ConsistencyCheck) => checks.push(c);

  if (!p.idea.title.trim() || !p.idea.problem.trim() || !p.idea.solution.trim()) {
    add({ id: "idea", severity: "error", route: "overview", title: "Идея описана не полностью", detail: "Заполните название, проблему и решение — от них зависят все остальные разделы." });
  }

  if (r.validation.verdict === "incomplete") {
    add({ id: "validation", severity: "warning", route: "validation", title: "Идея не оценена", detail: `Оценено ${r.validation.answered} из ${r.validation.total} критериев. Нужно минимум 10 для вывода.` });
  } else if (r.validation.confidence < 0.4) {
    add({ id: "confidence", severity: "warning", route: "experiments", title: "Оценка держится на предположениях", detail: `Уверенность оценки ${fmtPercent(r.validation.confidence)}. Подтвердите ключевые гипотезы экспериментами.` });
  }
  for (const flag of r.validation.redFlags.slice(0, 3)) {
    add({ id: `flag-${flag}`, severity: "error", route: "validation", title: "Красный флаг", detail: flag });
  }

  // Cross-module consistency between unit economics and the financial model.
  if (differs(r.unit.arpu, p.finance.arpu)) {
    add({ id: "arpu", severity: "warning", route: "finance", title: "ARPU расходится", detail: `В юнит-экономике ${money(r.unit.arpu)}/мес, в финмодели ${money(p.finance.arpu)}/мес.` });
  }
  if (differs(r.unit.cac, p.finance.cac)) {
    add({ id: "cac", severity: "warning", route: "finance", title: "CAC расходится", detail: `В юнит-экономике ${money(r.unit.cac)}, в финмодели ${money(p.finance.cac)}.` });
  }
  if (differs(p.unit.monthlyChurn, p.finance.monthlyChurn, 0.25)) {
    add({ id: "churn", severity: "info", route: "finance", title: "Отток расходится", detail: `Юнит-экономика: ${fmtPercent(p.unit.monthlyChurn, 1)}, финмодель: ${fmtPercent(p.finance.monthlyChurn, 1)} в месяц.` });
  }
  if (differs(p.unit.grossMargin, p.finance.grossMargin, 0.1)) {
    add({ id: "margin", severity: "info", route: "finance", title: "Маржа расходится", detail: `Юнит-экономика: ${fmtPercent(p.unit.grossMargin)}, финмодель: ${fmtPercent(p.finance.grossMargin)}.` });
  }

  if (r.unit.ltvToCac < 1) {
    add({ id: "ltv", severity: "error", route: "unit", title: "LTV меньше CAC", detail: "Каждый новый клиент увеличивает убыток. Масштабирование маркетинга сейчас опасно." });
  } else if (r.unit.ltvToCac < 3) {
    add({ id: "ltv3", severity: "warning", route: "unit", title: "LTV/CAC ниже 3", detail: `Сейчас ${r.unit.ltvToCac.toFixed(1)}. Инвесторы обычно ждут ≥ 3.` });
  }

  const som = conservativeSom(r.market);
  const sam = conservativeSam(r.market);
  const lastYear = r.finance.years[r.finance.years.length - 1];
  if (sam <= 0) {
    add({ id: "market", severity: "warning", route: "market", title: "Рынок не посчитан", detail: "Оцените TAM/SAM/SOM, чтобы проверить реалистичность плана продаж." });
  } else if (lastYear && lastYear.revenue > sam) {
    add({ id: "sam", severity: "error", route: "market", title: "Выручка больше SAM", detail: `Выручка в год ${lastYear.year} (${money(lastYear.revenue)}) превышает весь доступный рынок (${money(sam)}).` });
  } else if (lastYear && som > 0 && lastYear.revenue > som * 1.2) {
    add({ id: "som", severity: "warning", route: "market", title: "План продаж выше SOM", detail: `Выручка в год ${lastYear.year} (${money(lastYear.revenue)}) выше реалистичной доли рынка (${money(som)}).` });
  }
  for (const w of r.market.warnings) add({ id: `mw-${w}`, severity: "info", route: "market", title: "Оценка рынка", detail: w });

  if (r.finance.breakEvenMonth === null) {
    add({ id: "be", severity: "warning", route: "finance", title: "Нет безубыточности", detail: `Бизнес не выходит в операционный плюс за ${p.finance.horizonMonths} мес. Проверьте цену, отток и расходы.` });
  }
  if (r.finance.fundingGap > 0) {
    add({ id: "gap", severity: "error", route: "finance", title: "Не хватает денег", detail: `Деньги заканчиваются на ${(r.finance.runwayMonths ?? 0) + 1}-м месяце. Дефицит ${money(r.finance.fundingGap)} — добавьте раунд или сократите расходы.` });
  }
  if (p.finance.team.length === 0) {
    add({ id: "team", severity: "info", route: "finance", title: "В финмодели нет команды", detail: "Учтите хотя бы зарплату основателей — иначе модель будет слишком оптимистичной." });
  }

  const mScore = p.validation.market_size?.score;
  if (mScore && sam > 0 && Math.abs(mScore - marketSizeToScore(sam)) >= 2) {
    add({ id: "vm", severity: "info", route: "validation", title: "Оценка рынка не совпадает с расчётом", detail: `Вы поставили ${mScore}/5 за размер рынка, а расчёт SAM (${money(sam)}) соответствует ${marketSizeToScore(sam)}/5.` });
  }
  const uScore = p.validation.unit_economics?.score;
  if (uScore && Math.abs(uScore - ltvCacToScore(r.unit.ltvToCac)) >= 2) {
    add({ id: "vu", severity: "info", route: "validation", title: "Оценка юнит-экономики не совпадает с расчётом", detail: `Вы поставили ${uScore}/5, а LTV/CAC = ${r.unit.ltvToCac.toFixed(1)} соответствует ${ltvCacToScore(r.unit.ltvToCac)}/5.` });
  }

  if (r.lean.completeness < 0.6) {
    add({ id: "lean", severity: "warning", route: "canvas", title: "Lean Canvas заполнен частично", detail: `Заполнено ${r.lean.filled} из ${r.lean.total} блоков.` });
  }
  if (p.competitors.length < 2) {
    add({ id: "comp", severity: "warning", route: "market", title: "Мало конкурентов", detail: "«Конкурентов нет» почти всегда значит, что их плохо искали — или что рынка нет. Добавьте прямых и косвенных конкурентов." });
  }
  if (p.risks.length < 3) {
    add({ id: "risks", severity: "warning", route: "risks", title: "Риски не проработаны", detail: "Добавьте хотя бы 5 ключевых рисков и план их снижения." });
  }
  if (p.hypotheses.length === 0) {
    add({ id: "hyp", severity: "warning", route: "experiments", title: "Нет гипотез", detail: "Сформулируйте самые рискованные предположения и спланируйте их проверку." });
  }
  if (!checks.some((c) => c.severity === "error" || c.severity === "warning")) {
    add({ id: "ok", severity: "ok", route: "plan", title: "Проект согласован", detail: "Критичных противоречий между разделами не найдено — можно собирать бизнес-план." });
  }
  const order: Record<CheckSeverity, number> = { error: 0, warning: 1, info: 2, ok: 3 };
  return checks.sort((a, b) => order[a.severity] - order[b.severity]);
}

function computeReadiness(
  p: Project,
  r: Pick<ProjectAnalysis, "validation" | "unit" | "market" | "finance" | "lean" | "risks">,
): ProjectAnalysis["readiness"] {
  const ideaFields = [p.idea.title, p.idea.oneLiner, p.idea.problem, p.idea.solution, p.idea.audience];
  const mitigated = p.risks.filter((x) => x.mitigation.trim().length >= 5).length;
  const validatedHyp = p.hypotheses.filter((h) => h.status === "validated").length;
  const parts = [
    { label: "Описание идеи", max: 10, value: (ideaFields.filter((f) => f.trim()).length / ideaFields.length) * 10, route: "overview" },
    { label: "Оценка идеи", max: 15, value: (r.validation.answered / r.validation.total) * 15, route: "validation" },
    { label: "Уверенность в оценке", max: 10, value: r.validation.confidence * 10, route: "experiments" },
    { label: "Lean Canvas", max: 10, value: r.lean.completeness * 10, route: "canvas" },
    { label: "Рынок и конкуренты", max: 15, value: (conservativeSam(r.market) > 0 ? 10 : 0) + Math.min(2, p.competitors.length) * 2.5, route: "market" },
    { label: "Юнит-экономика", max: 10, value: Math.min(1, Math.max(0, r.unit.ltvToCac) / 3) * 10, route: "unit" },
    { label: "Финансовая модель", max: 10, value: (r.finance.breakEvenMonth !== null ? 7 : 2) + (r.finance.fundingGap <= 0 ? 3 : 0), route: "finance" },
    { label: "Риски", max: 10, value: Math.min(5, mitigated) * 2, route: "risks" },
    { label: "Гипотезы и эксперименты", max: 10, value: Math.min(3, p.hypotheses.length) * 2 + Math.min(2, validatedHyp) * 2, route: "experiments" },
  ];
  const score = parts.reduce((s, x) => s + x.value, 0);
  return { score: Math.round(score), parts: parts.map((x) => ({ ...x, value: Math.round(x.value * 10) / 10 })) };
}
