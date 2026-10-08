import { computeFinance } from "./finance";
import { createRng, triangular } from "./random";
import type { FinanceAssumptions, MonteCarloConfig, MonteCarloKey, MonteCarloParam } from "./types";

export const MC_PARAMS: Record<MonteCarloKey, { label: string; hint: string; unit: "x" | "мес." }> = {
  arpu: { label: "Средний доход с клиента (ARPU)", hint: "Множитель к базовому ARPU", unit: "x" },
  cac: { label: "Стоимость привлечения (CAC)", hint: "Множитель к базовому CAC", unit: "x" },
  monthlyChurn: { label: "Отток клиентов", hint: "Множитель к базовому оттоку", unit: "x" },
  grossMargin: { label: "Валовая маржа", hint: "Множитель к базовой марже", unit: "x" },
  organicStart: { label: "Органический приток", hint: "Множитель к органике", unit: "x" },
  marketingStart: { label: "Маркетинговый бюджет", hint: "Множитель к бюджету", unit: "x" },
  fixedCosts: { label: "Постоянные расходы и ФОТ", hint: "Множитель к расходам", unit: "x" },
  launchDelay: { label: "Задержка запуска", hint: "Сдвиг запуска в месяцах", unit: "мес." },
};

export const DEFAULT_MC_PARAMS: MonteCarloParam[] = [
  { key: "arpu", enabled: true, min: 0.8, mode: 1, max: 1.15 },
  { key: "cac", enabled: true, min: 0.85, mode: 1, max: 1.6 },
  { key: "monthlyChurn", enabled: true, min: 0.7, mode: 1, max: 1.5 },
  { key: "grossMargin", enabled: false, min: 0.85, mode: 1, max: 1.05 },
  { key: "organicStart", enabled: true, min: 0.4, mode: 1, max: 1.6 },
  { key: "marketingStart", enabled: false, min: 0.8, mode: 1, max: 1.2 },
  { key: "fixedCosts", enabled: true, min: 0.95, mode: 1, max: 1.25 },
  { key: "launchDelay", enabled: true, min: 0, mode: 1, max: 3 },
];

export interface Distribution {
  p10: number;
  p50: number;
  p90: number;
  mean: number;
  values: number[];
}

export interface MonteCarloResult {
  runs: number;
  months: number[];
  cash: { p10: number[]; p50: number[]; p90: number[] };
  revenue: { p10: number[]; p50: number[]; p90: number[] };
  probBreakEven: number;
  breakEvenMonths: number[];
  breakEvenP50: number | null;
  probFullyFunded: number;
  fundingNeed: Distribution;
  npv: Distribution & { probPositive: number };
  endMrr: Distribution;
  totalRevenue: Distribution;
}

export function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return Number.NaN;
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function distribution(values: number[]): Distribution {
  const sorted = [...values].sort((a, b) => a - b);
  return {
    p10: percentile(sorted, 0.1),
    p50: percentile(sorted, 0.5),
    p90: percentile(sorted, 0.9),
    mean: values.reduce((s, v) => s + v, 0) / Math.max(1, values.length),
    values: sorted,
  };
}

export function sampleAssumptions(
  base: FinanceAssumptions,
  params: MonteCarloParam[],
  rnd: () => number,
): FinanceAssumptions {
  const a: FinanceAssumptions = { ...base };
  for (const p of params) {
    if (!p.enabled) continue;
    const v = triangular(rnd, p.min, p.mode, p.max);
    switch (p.key) {
      case "arpu":
        a.arpu = base.arpu * v;
        break;
      case "cac":
        a.cac = base.cac * v;
        break;
      case "monthlyChurn":
        a.monthlyChurn = Math.min(1, base.monthlyChurn * v);
        break;
      case "grossMargin":
        a.grossMargin = Math.min(0.99, base.grossMargin * v);
        break;
      case "organicStart":
        a.organicStart = base.organicStart * v;
        break;
      case "marketingStart":
        a.marketingStart = base.marketingStart * v;
        a.marketingMax = base.marketingMax * v;
        break;
      case "fixedCosts":
        a.team = base.team.map((m) => ({ ...m, salary: m.salary * v }));
        a.costs = base.costs.map((c) => ({ ...c, monthly: c.monthly * v }));
        break;
      case "launchDelay":
        a.launchMonth = base.launchMonth + Math.max(0, Math.round(v));
        break;
    }
  }
  return a;
}

export function runMonteCarlo(base: FinanceAssumptions, config: MonteCarloConfig): MonteCarloResult {
  const runs = Math.max(10, Math.min(20000, Math.round(config.runs)));
  const rnd = createRng(config.seed);
  const horizon = Math.max(1, Math.round(base.horizonMonths));
  const cashByMonth: number[][] = Array.from({ length: horizon }, () => []);
  const revenueByMonth: number[][] = Array.from({ length: horizon }, () => []);
  const breakEvenMonths: number[] = [];
  const fundingNeeds: number[] = [];
  const npvs: number[] = [];
  const endMrrs: number[] = [];
  const totals: number[] = [];
  let funded = 0;

  for (let i = 0; i < runs; i++) {
    const res = computeFinance(sampleAssumptions(base, config.params, rnd));
    res.rows.forEach((r, m) => {
      cashByMonth[m].push(r.cash);
      revenueByMonth[m].push(r.revenue);
    });
    if (res.breakEvenMonth !== null) breakEvenMonths.push(res.breakEvenMonth);
    fundingNeeds.push(res.fundingNeed);
    npvs.push(res.npv);
    endMrrs.push(res.endMrr);
    totals.push(res.totalRevenue);
    if (res.fundingGap <= 0) funded++;
  }

  const bands = (byMonth: number[][]) => {
    const p10: number[] = [];
    const p50: number[] = [];
    const p90: number[] = [];
    for (const values of byMonth) {
      const sorted = values.sort((a, b) => a - b);
      p10.push(percentile(sorted, 0.1));
      p50.push(percentile(sorted, 0.5));
      p90.push(percentile(sorted, 0.9));
    }
    return { p10, p50, p90 };
  };

  const npvDist = distribution(npvs);
  const sortedBe = [...breakEvenMonths].sort((a, b) => a - b);
  // Median break-even across ALL runs (runs that never break even count as +∞).
  const medianIdx = Math.floor((runs - 1) / 2);
  const breakEvenP50 = medianIdx < sortedBe.length ? sortedBe[medianIdx] : null;

  return {
    runs,
    months: Array.from({ length: horizon }, (_, i) => i + 1),
    cash: bands(cashByMonth),
    revenue: bands(revenueByMonth),
    probBreakEven: breakEvenMonths.length / runs,
    breakEvenMonths: sortedBe,
    breakEvenP50,
    probFullyFunded: funded / runs,
    fundingNeed: distribution(fundingNeeds),
    npv: { ...npvDist, probPositive: npvs.filter((v) => v > 0).length / runs },
    endMrr: distribution(endMrrs),
    totalRevenue: distribution(totals),
  };
}

/** Builds histogram bins for a list of values. */
export function histogram(values: number[], bins = 20): { x0: number; x1: number; count: number }[] {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [{ x0: min, x1: max, count: values.length }];
  const width = (max - min) / bins;
  const out = Array.from({ length: bins }, (_, i) => ({ x0: min + i * width, x1: min + (i + 1) * width, count: 0 }));
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.floor((v - min) / width));
    out[idx].count++;
  }
  return out;
}
