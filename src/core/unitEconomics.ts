import type { UnitEconomicsInput } from "./types";

export type Health = "good" | "ok" | "bad";

export interface UnitEconomicsResult {
  arpu: number; // monthly revenue per customer
  contribution: number; // monthly gross profit per customer
  cac: number;
  lifetimeMonths: number;
  ltv: number; // gross-margin LTV (undiscounted)
  ltvDiscounted: number;
  ltvToCac: number;
  paybackMonths: number; // months of contribution to recover CAC
  profitPerCustomer: number; // LTV − CAC
  romi: number; // (LTV − CAC) / CAC
  breakEvenCustomers: number; // active customers needed to cover fixed costs
  health: {
    ltvToCac: Health;
    payback: Health;
    margin: Health;
    churn: Health;
  };
  verdict: string;
}

const MAX_LIFETIME = 120;

export function effectiveCac(input: UnitEconomicsInput): number {
  if (input.cacMode === "funnel") {
    return input.leadToCustomer > 0 ? input.costPerLead / input.leadToCustomer : Infinity;
  }
  return input.cac;
}

export function computeUnitEconomics(input: UnitEconomicsInput): UnitEconomicsResult {
  const arpu = Math.max(0, input.avgCheck * input.purchasesPerMonth);
  const contribution = arpu * input.grossMargin;
  const cac = Math.max(0, effectiveCac(input));
  const churn = Math.max(0, input.monthlyChurn);
  const lifetimeMonths = churn > 0 ? Math.min(MAX_LIFETIME, 1 / churn) : MAX_LIFETIME;
  const ltv = contribution * lifetimeMonths;

  // Discounted LTV: sum of contribution × survival / (1+r)^t over the horizon.
  const rMonthly = Math.pow(1 + Math.max(0, input.discountRateYear), 1 / 12) - 1;
  let ltvDiscounted = 0;
  let survival = 1;
  for (let t = 0; t < MAX_LIFETIME && survival > 1e-4; t++) {
    ltvDiscounted += (contribution * survival) / Math.pow(1 + rMonthly, t);
    survival *= 1 - Math.min(1, churn);
  }

  const ltvToCac = cac > 0 ? ltv / cac : Infinity;
  const paybackMonths = contribution > 0 ? cac / contribution : Infinity;
  const profitPerCustomer = ltv - cac;
  const romi = cac > 0 ? profitPerCustomer / cac : Infinity;
  const breakEvenCustomers = contribution > 0 ? input.fixedCostsMonthly / contribution : Infinity;

  const health = {
    ltvToCac: (ltvToCac >= 3 ? "good" : ltvToCac >= 1.5 ? "ok" : "bad") as Health,
    payback: (paybackMonths <= 12 ? "good" : paybackMonths <= 24 ? "ok" : "bad") as Health,
    margin: (input.grossMargin >= 0.5 ? "good" : input.grossMargin >= 0.25 ? "ok" : "bad") as Health,
    churn: (churn <= 0.03 ? "good" : churn <= 0.08 ? "ok" : "bad") as Health,
  };

  let verdict: string;
  if (ltvToCac < 1) verdict = "Экономика не сходится: клиент приносит меньше, чем стоит его привлечение.";
  else if (ltvToCac < 1.5) verdict = "Экономика на грани: любое ухудшение метрик приведёт к убыткам.";
  else if (ltvToCac < 3) verdict = "Экономика положительная, но запас прочности мал. Цель — LTV/CAC ≥ 3.";
  else if (paybackMonths > 18) verdict = "LTV/CAC хороший, но окупаемость клиента долгая — потребуется много оборотного капитала.";
  else verdict = "Здоровая юнит-экономика: можно масштабировать привлечение.";

  return {
    arpu,
    contribution,
    cac,
    lifetimeMonths,
    ltv,
    ltvDiscounted,
    ltvToCac,
    paybackMonths,
    profitPerCustomer,
    romi,
    breakEvenCustomers,
    health,
    verdict,
  };
}

export type SensitivityKey = "avgCheck" | "purchasesPerMonth" | "grossMargin" | "monthlyChurn" | "cac";

export const SENSITIVITY_LABELS: Record<SensitivityKey, string> = {
  avgCheck: "Средний чек",
  purchasesPerMonth: "Частота покупок",
  grossMargin: "Валовая маржа",
  monthlyChurn: "Отток",
  cac: "Стоимость привлечения (CAC)",
};

export interface SensitivityRow {
  key: SensitivityKey;
  label: string;
  low: number; // metric value when the input moves in the unfavourable direction
  high: number; // … favourable direction
  range: number;
}

/**
 * Tornado analysis: shifts each driver by ±delta and measures the impact on profit per customer (LTV − CAC).
 * Returned rows are sorted by impact so the most important lever is first.
 */
export function sensitivity(input: UnitEconomicsInput, delta = 0.2): SensitivityRow[] {
  const keys: SensitivityKey[] = ["avgCheck", "purchasesPerMonth", "grossMargin", "monthlyChurn", "cac"];
  const metric = (i: UnitEconomicsInput) => computeUnitEconomics(i).profitPerCustomer;
  const baseCac = effectiveCac(input);
  const rows = keys.map((key) => {
    const variant = (factor: number): UnitEconomicsInput => {
      if (key === "cac") return { ...input, cacMode: "direct", cac: baseCac * factor };
      const value = input[key] * factor;
      return { ...input, [key]: key === "grossMargin" ? Math.min(1, value) : value };
    };
    const down = metric(variant(1 - delta));
    const up = metric(variant(1 + delta));
    const low = Math.min(down, up);
    const high = Math.max(down, up);
    return { key, label: SENSITIVITY_LABELS[key], low, high, range: high - low };
  });
  return rows.sort((a, b) => b.range - a.range);
}
