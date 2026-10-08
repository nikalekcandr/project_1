import type { FinanceAssumptions } from "./types";

export interface MonthRow {
  month: number;
  headcount: number;
  newCustomers: number;
  churned: number;
  activeCustomers: number;
  arpu: number;
  cac: number;
  revenue: number;
  cogs: number;
  grossProfit: number;
  marketing: number;
  payroll: number;
  opex: number;
  ebitda: number;
  depreciation: number;
  ebit: number;
  tax: number;
  netIncome: number;
  capex: number;
  freeCashFlow: number;
  funding: number;
  cash: number;
}

export interface YearRow {
  year: number;
  revenue: number;
  grossProfit: number;
  marketing: number;
  payroll: number;
  opex: number;
  ebitda: number;
  netIncome: number;
  freeCashFlow: number;
  endCash: number;
  endCustomers: number;
  endMrr: number;
  newCustomers: number;
}

export interface FinanceResult {
  rows: MonthRow[];
  years: YearRow[];
  breakEvenMonth: number | null;
  cashFlowPositiveMonth: number | null;
  paybackMonth: number | null;
  minCash: number;
  minCashMonth: number;
  /** Peak cumulative burn — total money the business consumes before it pays for itself. */
  fundingNeed: number;
  /** Extra money needed beyond starting cash and planned funding (0 if the plan is fully funded). */
  fundingGap: number;
  runwayMonths: number | null;
  totalRevenue: number;
  endMrr: number;
  endCustomers: number;
  terminalValue: number;
  npv: number;
  irrAnnual: number | null;
}

const monthlyRate = (annual: number) => Math.pow(1 + annual, 1 / 12) - 1;

export function computeFinance(a: FinanceAssumptions): FinanceResult {
  const n = Math.max(1, Math.round(a.horizonMonths));
  const rows: MonthRow[] = [];
  let active = 0;
  let cash = a.startingCash;
  let lossPool = 0;

  for (let t = 1; t <= n; t++) {
    const launched = t >= a.launchMonth;
    const sinceLaunch = t - a.launchMonth;
    const yearIndex = Math.floor((t - 1) / 12);
    const arpu = a.arpu * Math.pow(1 + a.priceGrowthPerYear, yearIndex);
    const cac = a.cac * Math.pow(1 + a.cacGrowthPerYear, (t - 1) / 12);

    const marketing = launched
      ? Math.min(a.marketingMax > 0 ? a.marketingMax : Infinity, a.marketingStart * Math.pow(1 + a.marketingGrowth, sinceLaunch))
      : 0;
    const paidNew = cac > 0 ? marketing / cac : 0;
    const organic = launched ? a.organicStart * Math.pow(1 + a.organicGrowth, sinceLaunch) : 0;
    const referral = launched ? active * a.referralRate : 0;
    const seed = t === a.launchMonth ? a.initialCustomers : 0;
    const newCustomers = launched ? paidNew + organic + referral + seed : 0;

    const churned = active * Math.min(1, Math.max(0, a.monthlyChurn));
    active = Math.max(0, active - churned + newCustomers);

    const revenue = active * arpu;
    const cogs = revenue * (1 - a.grossMargin);
    const grossProfit = revenue - cogs;

    let payroll = 0;
    let headcount = 0;
    for (const m of a.team) {
      if (t >= m.startMonth) {
        payroll += m.salary * m.count * (1 + a.payrollTax);
        headcount += m.count;
      }
    }
    let opex = 0;
    for (const c of a.costs) {
      if (t >= c.startMonth) opex += c.monthly * Math.pow(1 + c.growthPerYear, (t - c.startMonth) / 12);
    }

    const ebitda = grossProfit - marketing - payroll - opex;
    let depreciation = 0;
    let capex = 0;
    for (const c of a.capex) {
      const months = Math.max(1, c.depreciationMonths);
      if (t === c.month) capex += c.amount;
      if (t >= c.month && t < c.month + months) depreciation += c.amount / months;
    }
    const ebit = ebitda - depreciation;

    let tax = 0;
    if (a.taxMode === "revenue") {
      tax = revenue * a.taxRate;
    } else if (a.taxMode === "profit") {
      if (ebit > 0) {
        const offset = Math.min(lossPool, ebit);
        lossPool -= offset;
        tax = (ebit - offset) * a.taxRate;
      } else {
        lossPool += -ebit;
      }
    }

    const netIncome = ebit - tax;
    const freeCashFlow = netIncome + depreciation - capex;
    const funding = a.funding.filter((f) => f.month === t).reduce((s, f) => s + f.amount, 0);
    cash += freeCashFlow + funding;

    rows.push({
      month: t,
      headcount,
      newCustomers,
      churned,
      activeCustomers: active,
      arpu,
      cac,
      revenue,
      cogs,
      grossProfit,
      marketing,
      payroll,
      opex,
      ebitda,
      depreciation,
      ebit,
      tax,
      netIncome,
      capex,
      freeCashFlow,
      funding,
      cash,
    });
  }

  return summarize(a, rows);
}

function firstSustained(rows: MonthRow[], test: (r: MonthRow) => boolean, window = 3): number | null {
  for (let i = 0; i < rows.length; i++) {
    const end = Math.min(rows.length, i + window);
    let ok = true;
    for (let j = i; j < end; j++) {
      if (!test(rows[j])) {
        ok = false;
        break;
      }
    }
    if (ok) return rows[i].month;
  }
  return null;
}

function summarize(a: FinanceAssumptions, rows: MonthRow[]): FinanceResult {
  const years: YearRow[] = [];
  for (let y = 0; y * 12 < rows.length; y++) {
    const slice = rows.slice(y * 12, y * 12 + 12);
    const last = slice[slice.length - 1];
    const sum = (k: keyof MonthRow) => slice.reduce((s, r) => s + (r[k] as number), 0);
    years.push({
      year: y + 1,
      revenue: sum("revenue"),
      grossProfit: sum("grossProfit"),
      marketing: sum("marketing"),
      payroll: sum("payroll"),
      opex: sum("opex"),
      ebitda: sum("ebitda"),
      netIncome: sum("netIncome"),
      freeCashFlow: sum("freeCashFlow"),
      endCash: last.cash,
      endCustomers: last.activeCustomers,
      endMrr: last.revenue,
      newCustomers: sum("newCustomers"),
    });
  }

  let minCash = a.startingCash;
  let minCashMonth = 0;
  let cumFcf = 0;
  let minCumFcf = 0;
  let paybackMonth: number | null = null;
  let wasNegative = false;
  let runwayMonths: number | null = null;
  for (const r of rows) {
    if (r.cash < minCash) {
      minCash = r.cash;
      minCashMonth = r.month;
    }
    if (runwayMonths === null && r.cash < 0) runwayMonths = r.month - 1;
    cumFcf += r.freeCashFlow;
    if (cumFcf < 0) wasNegative = true;
    if (cumFcf < minCumFcf) minCumFcf = cumFcf;
    if (paybackMonth === null && wasNegative && cumFcf >= 0) paybackMonth = r.month;
  }

  const breakEvenMonth = firstSustained(rows, (r) => r.ebitda >= 0 && r.revenue > 0);
  const cashFlowPositiveMonth = firstSustained(rows, (r) => r.freeCashFlow >= 0 && r.revenue > 0);

  const r = monthlyRate(a.discountRateYear);
  const last12 = rows.slice(-12);
  const trailingEbitda = last12.reduce((s, x) => s + x.ebitda, 0) * (12 / Math.max(1, last12.length));
  const terminalValue = Math.max(0, trailingEbitda) * Math.max(0, a.exitMultiple);
  const flows = rows.map((x) => x.freeCashFlow);
  flows[flows.length - 1] += terminalValue;
  const npv = flows.reduce((s, cf, i) => s + cf / Math.pow(1 + r, i + 1), 0);
  const irrMonthly = irr(flows);

  const lastRow = rows[rows.length - 1];
  return {
    rows,
    years,
    breakEvenMonth,
    cashFlowPositiveMonth,
    paybackMonth,
    minCash,
    minCashMonth,
    fundingNeed: Math.max(0, -minCumFcf),
    fundingGap: Math.max(0, -minCash),
    runwayMonths,
    totalRevenue: rows.reduce((s, x) => s + x.revenue, 0),
    endMrr: lastRow.revenue,
    endCustomers: lastRow.activeCustomers,
    terminalValue,
    npv,
    irrAnnual: irrMonthly === null ? null : Math.pow(1 + irrMonthly, 12) - 1,
  };
}

/** Monthly IRR by bisection; null when cash flows don't change sign. */
export function irr(flows: number[]): number | null {
  const hasNeg = flows.some((f) => f < 0);
  const hasPos = flows.some((f) => f > 0);
  if (!hasNeg || !hasPos) return null;
  const npvAt = (rate: number) => flows.reduce((s, cf, i) => s + cf / Math.pow(1 + rate, i + 1), 0);
  let lo = -0.99;
  let hi = 1;
  let fLo = npvAt(lo);
  let fHi = npvAt(hi);
  // Expand the upper bound for very profitable projects.
  for (let k = 0; k < 20 && fLo * fHi > 0; k++) {
    hi *= 2;
    fHi = npvAt(hi);
  }
  if (fLo * fHi > 0) return null;
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    const fMid = npvAt(mid);
    if (Math.abs(fMid) < 1e-6) return mid;
    if (fLo * fMid < 0) {
      hi = mid;
      fHi = fMid;
    } else {
      lo = mid;
      fLo = fMid;
    }
  }
  return (lo + hi) / 2;
}

export interface Scenario {
  id: "pessimistic" | "base" | "optimistic";
  label: string;
  arpu: number;
  cac: number;
  churn: number;
  organic: number;
  launchDelay: number;
}

export const SCENARIOS: Scenario[] = [
  { id: "pessimistic", label: "Пессимистичный", arpu: 0.85, cac: 1.3, churn: 1.3, organic: 0.6, launchDelay: 2 },
  { id: "base", label: "Базовый", arpu: 1, cac: 1, churn: 1, organic: 1, launchDelay: 0 },
  { id: "optimistic", label: "Оптимистичный", arpu: 1.1, cac: 0.8, churn: 0.8, organic: 1.4, launchDelay: 0 },
];

export function applyScenario(a: FinanceAssumptions, s: Scenario): FinanceAssumptions {
  return {
    ...a,
    arpu: a.arpu * s.arpu,
    cac: a.cac * s.cac,
    monthlyChurn: Math.min(1, a.monthlyChurn * s.churn),
    organicStart: a.organicStart * s.organic,
    launchMonth: a.launchMonth + s.launchDelay,
  };
}

/** Monthly burn of fixed costs (team + opex) at a given month — useful for runway math. */
export function fixedCostsAt(a: FinanceAssumptions, month: number): number {
  const payroll = a.team
    .filter((m) => month >= m.startMonth)
    .reduce((s, m) => s + m.salary * m.count * (1 + a.payrollTax), 0);
  const opex = a.costs
    .filter((c) => month >= c.startMonth)
    .reduce((s, c) => s + c.monthly * Math.pow(1 + c.growthPerYear, (month - c.startMonth) / 12), 0);
  return payroll + opex;
}
