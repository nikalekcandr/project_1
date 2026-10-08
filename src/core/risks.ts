import { getIndustry } from "./knowledge/industries";
import { TRENDS } from "./knowledge/trends";
import type { MarketResult } from "./market";
import type { UnitEconomicsResult } from "./unitEconomics";
import { CRITERIA, type ValidationResult } from "./validation";
import type { Project, Risk, Swot } from "./types";

export type RiskLevel = "critical" | "high" | "medium" | "low";

export function riskScore(r: Pick<Risk, "probability" | "impact">): number {
  return r.probability * r.impact;
}

export function riskLevel(score: number): RiskLevel {
  if (score >= 15) return "critical";
  if (score >= 10) return "high";
  if (score >= 5) return "medium";
  return "low";
}

export const RISK_LEVEL_LABELS: Record<RiskLevel, string> = {
  critical: "Критический",
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
};

export interface RiskSummary {
  total: number;
  byLevel: Record<RiskLevel, number>;
  exposure: number; // 0..1 — average normalized risk score
  top: Risk[];
  unmitigated: Risk[];
}

export function summarizeRisks(risks: Risk[]): RiskSummary {
  const byLevel: Record<RiskLevel, number> = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const r of risks) byLevel[riskLevel(riskScore(r))]++;
  const exposure = risks.length ? risks.reduce((s, r) => s + riskScore(r) / 25, 0) / risks.length : 0;
  const sorted = [...risks].sort((a, b) => riskScore(b) - riskScore(a));
  return {
    total: risks.length,
    byLevel,
    exposure,
    top: sorted.slice(0, 5),
    unmitigated: sorted.filter((r) => riskScore(r) >= 10 && r.mitigation.trim().length < 5),
  };
}

/** Suggests SWOT items from other modules so the founder doesn't start from a blank page. */
export function suggestSwot(
  project: Project,
  validation: ValidationResult,
  unit: UnitEconomicsResult,
  market: MarketResult,
): Swot {
  const strengths: string[] = [];
  const weaknesses: string[] = [];
  const opportunities: string[] = [];
  const threats: string[] = [];

  for (const r of validation.results) {
    if (!r.answer) continue;
    if (r.answer.score >= 4) strengths.push(`${r.criterion.name}: ${r.criterion.anchors[2].toLowerCase()}`);
    if (r.answer.score <= 2) weaknesses.push(`${r.criterion.name}: ${r.criterion.anchors[0].toLowerCase()}`);
  }
  if (unit.ltvToCac >= 3) strengths.push(`Сильная юнит-экономика: LTV/CAC = ${unit.ltvToCac.toFixed(1)}`);
  else if (unit.ltvToCac < 1.5) weaknesses.push(`Слабая юнит-экономика: LTV/CAC = ${unit.ltvToCac.toFixed(1)}`);

  const industry = getIndustry(project.idea.industryId);
  if (industry) {
    if (industry.growth >= 4) opportunities.push(`Отрасль «${industry.name}» быстро растёт`);
    if (industry.competition >= 4) threats.push(`Высокая конкуренция в отрасли «${industry.name}»`);
    if (industry.regulation >= 4) threats.push("Ужесточение регулирования отрасли");
    for (const t of TRENDS.filter((t) => t.boosts.includes(industry.id)).slice(0, 3)) {
      opportunities.push(`Тренд: ${t.name.toLowerCase()}`);
    }
  }
  if (market.bottomUp.sam > 0 && market.bottomUp.som / market.bottomUp.sam < 0.05) {
    opportunities.push("Большой незанятый рынок: целевая доля меньше 5% SAM");
  }
  const competition = validation.results.find((r) => r.criterion.id === "competition");
  if (competition?.answer && competition.answer.score <= 2) threats.push("Сильные конкуренты с большими ресурсами");
  threats.push("Рост стоимости рекламы и привлечения клиентов");

  const unique = (xs: string[]) => [...new Set(xs)].slice(0, 6);
  return {
    strengths: unique(strengths),
    weaknesses: unique(weaknesses),
    opportunities: unique(opportunities),
    threats: unique(threats),
  };
}

export const CRITERION_NAMES = Object.fromEntries(CRITERIA.map((c) => [c.id, c.name])) as Record<string, string>;
