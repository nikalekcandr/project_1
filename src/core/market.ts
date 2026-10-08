import type { MarketSizingInput } from "./types";

export interface MarketTriple {
  tam: number;
  sam: number;
  som: number;
}

export interface MarketResult {
  topDown: MarketTriple;
  bottomUp: MarketTriple & { customers: number };
  /** Ratio between the larger and the smaller SAM estimate (1 = perfect agreement). */
  samMismatch: number;
  warnings: string[];
  insights: string[];
}

export function computeMarket(input: MarketSizingInput): MarketResult {
  const td = input.topDown;
  const tdTam = td.totalCustomers * td.annualSpendPerCustomer;
  const tdSam = tdTam * td.segmentShare;
  const tdSom = tdSam * td.obtainableShare;

  const bu = input.bottomUp;
  const annualPerCustomer = bu.pricePerPurchase * bu.purchasesPerYear;
  const buSam = bu.targetCustomers * annualPerCustomer;
  const reached = bu.targetCustomers * bu.reachShare;
  const customers = reached * bu.conversionShare;
  const buSom = customers * annualPerCustomer;
  // Bottom-up TAM is not directly observable; reuse the top-down TAM when available.
  const buTam = Math.max(tdTam, buSam);

  const samMismatch = tdSam > 0 && buSam > 0 ? Math.max(tdSam, buSam) / Math.min(tdSam, buSam) : Number.NaN;

  const warnings: string[] = [];
  const insights: string[] = [];
  if (td.obtainableShare > 0.1) {
    warnings.push(
      `Доля SOM ${(td.obtainableShare * 100).toFixed(0)}% от SAM — очень агрессивно. Новые игроки редко занимают больше 1–5% рынка за 3–5 лет.`,
    );
  }
  if (Number.isFinite(samMismatch) && samMismatch > 3) {
    warnings.push(
      `Оценки SAM «сверху вниз» и «снизу вверх» расходятся в ${samMismatch.toFixed(1)} раза. Перепроверьте число клиентов и средний чек.`,
    );
  } else if (Number.isFinite(samMismatch)) {
    insights.push("Оценки «сверху вниз» и «снизу вверх» согласуются — это повышает доверие к расчёту.");
  }
  if (bu.conversionShare > 0.2) {
    warnings.push("Конверсия охваченных клиентов выше 20% — нереалистично для большинства рынков.");
  }
  if (tdSom > 0 && buSom > 0) {
    insights.push(
      `Реалистичная цель по выручке (SOM): ${buSom < tdSom ? "консервативная оценка — «снизу вверх»" : "консервативная оценка — «сверху вниз»"}.`,
    );
  }

  return {
    topDown: { tam: tdTam, sam: tdSam, som: tdSom },
    bottomUp: { tam: buTam, sam: buSam, som: buSom, customers },
    samMismatch,
    warnings,
    insights,
  };
}

/** Conservative SOM used for cross-checks with the financial model. */
export function conservativeSom(result: MarketResult): number {
  const values = [result.topDown.som, result.bottomUp.som].filter((v) => v > 0);
  return values.length ? Math.min(...values) : 0;
}

export function conservativeSam(result: MarketResult): number {
  const values = [result.topDown.sam, result.bottomUp.sam].filter((v) => v > 0);
  return values.length ? Math.min(...values) : 0;
}
