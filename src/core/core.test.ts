import { describe, expect, it } from "vitest";
import { analyzeProject } from "./analysis";
import { buildBusinessPlan, buildSection, fundingAsk, PLAN_SECTIONS } from "./businessPlan";
import { analyzeLean, leanToBmc } from "./canvas";
import { priorityScore, recommendExperiments, interviewScript } from "./experiments";
import { createProject, demoProject, projectFromIdea } from "./factory";
import { applyScenario, computeFinance, irr, SCENARIOS } from "./finance";
import { fmtMoney, fmtMonths, niceCeil, plural, slugify } from "./format";
import { generateIdeas, quickScore, scamperIdeas } from "./generator";
import { getIndustry, INDUSTRIES } from "./knowledge/industries";
import { BUSINESS_MODELS, getModel } from "./knowledge/businessModels";
import { computeMarket } from "./market";
import { histogram, percentile, runMonteCarlo } from "./monteCarlo";
import { createRng, triangular } from "./random";
import { riskLevel, summarizeRisks, suggestSwot } from "./risks";
import type { FinanceAssumptions, FounderProfile, UnitEconomicsInput } from "./types";
import { computeUnitEconomics, sensitivity } from "./unitEconomics";
import { CRITERIA, evaluateValidation, ltvCacToScore, marketSizeToScore } from "./validation";

const baseFinance = (over: Partial<FinanceAssumptions> = {}): FinanceAssumptions => ({
  horizonMonths: 24,
  launchMonth: 1,
  startingCash: 0,
  funding: [],
  arpu: 100,
  priceGrowthPerYear: 0,
  grossMargin: 1,
  monthlyChurn: 0,
  cac: 0,
  cacGrowthPerYear: 0,
  marketingStart: 0,
  marketingGrowth: 0,
  marketingMax: 0,
  organicStart: 10,
  organicGrowth: 0,
  referralRate: 0,
  initialCustomers: 0,
  team: [],
  payrollTax: 0,
  costs: [],
  capex: [],
  taxMode: "none",
  taxRate: 0,
  discountRateYear: 0,
  exitMultiple: 0,
  ...over,
});

describe("random", () => {
  it("is deterministic per seed", () => {
    const a = createRng(7);
    const b = createRng(7);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });
  it("triangular stays within bounds", () => {
    const rng = createRng(1);
    for (let i = 0; i < 1000; i++) {
      const v = triangular(rng, 2, 3, 10);
      expect(v).toBeGreaterThanOrEqual(2);
      expect(v).toBeLessThanOrEqual(10);
    }
  });
});

describe("format", () => {
  it("formats money compactly", () => {
    expect(fmtMoney(1_250_000)).toBe("1,25 млн ₽");
    expect(fmtMoney(-3_000_000_000, "USD")).toBe("−3 млрд $");
    expect(fmtMoney(950)).toBe("950 ₽");
  });
  it("pluralizes Russian words", () => {
    expect(plural(1, "месяц", "месяца", "месяцев")).toBe("месяц");
    expect(plural(3, "месяц", "месяца", "месяцев")).toBe("месяца");
    expect(plural(11, "месяц", "месяца", "месяцев")).toBe("месяцев");
    expect(fmtMonths(22)).toBe("22 месяца");
  });
  it("builds ASCII file names", () => {
    expect(slugify("Бизнес-план «ФитПульс» 2026")).toBe("biznes-plan-fitpuls-2026");
    expect(slugify("!!!")).toBe("bizforge");
  });
  it("rounds funding asks to nice numbers", () => {
    expect(niceCeil(1_234_567)).toBe(1_300_000);
    expect(niceCeil(0)).toBe(0);
  });
});

describe("idea generator", () => {
  it("generates the requested number of unique, scored ideas deterministically", () => {
    const a = generateIdeas({ method: "mix", count: 12, seed: 123 });
    const b = generateIdeas({ method: "mix", count: 12, seed: 123 });
    expect(a).toHaveLength(12);
    expect(a.map((i) => i.title)).toEqual(b.map((i) => i.title));
    expect(new Set(a.map((i) => i.title)).size).toBe(12);
    for (const idea of a) {
      expect(idea.quickScore).toBeGreaterThanOrEqual(0);
      expect(idea.quickScore).toBeLessThanOrEqual(100);
      expect(idea.title.length).toBeGreaterThan(5);
      expect(idea.oneLiner).toMatch(/\.$/);
      expect(idea.oneLiner).not.toContain("{job}");
    }
    // Sorted by score, best first.
    expect(a[0].quickScore! >= a[a.length - 1].quickScore!).toBe(true);
  });

  it("respects industry and segment filters", () => {
    const ideas = generateIdeas({ method: "trend_industry", count: 5, seed: 5, industries: ["pets"], segments: ["b2c"] });
    expect(ideas.length).toBeGreaterThan(0);
    for (const i of ideas) {
      expect(i.industryId).toBe("pets");
      expect(i.segment).toBe("b2c");
    }
  });

  it("rewards founder fit in the quick score", () => {
    const industry = getIndustry("education");
    const model = getModel("courses");
    const weak: FounderProfile = {
      skills: [],
      budget: 10_000,
      hoursPerWeek: 10,
      interests: [],
      riskTolerance: "low",
      preferredSegments: ["b2b"],
    };
    const strong: FounderProfile = {
      skills: ["content", "product", "marketing", "domain"],
      budget: 5_000_000,
      hoursPerWeek: 40,
      interests: ["education"],
      riskTolerance: "high",
      preferredSegments: ["b2c"],
    };
    expect(quickScore(industry, model, undefined, "b2c", strong).score).toBeGreaterThan(
      quickScore(industry, model, undefined, "b2c", weak).score,
    );
  });

  it("knowledge base is consistent", () => {
    for (const ind of INDUSTRIES) {
      expect(ind.problems.length).toBeGreaterThanOrEqual(3);
      for (const p of ind.problems) expect(p.job).not.toMatch(/^[А-ЯA-Z]/);
    }
    for (const m of BUSINESS_MODELS) {
      expect(m.defaults.grossMargin).toBeGreaterThan(0);
      expect(m.defaults.grossMargin).toBeLessThanOrEqual(1);
    }
  });

  it("produces SCAMPER prompts for all 7 techniques", () => {
    const res = scamperIdeas("кофейня");
    expect(res).toHaveLength(7);
    expect(res[0].ideas.join(" ").toLowerCase()).toContain("кофейня");
  });
});

describe("validation", () => {
  it("scores all-fives as 100 and verdict GO", () => {
    const answers = Object.fromEntries(CRITERIA.map((c) => [c.id, { score: 5, evidence: "data" as const }]));
    const r = evaluateValidation(answers);
    expect(r.score).toBeCloseTo(100);
    expect(r.confidence).toBeCloseTo(1);
    expect(r.verdict).toBe("go");
    expect(r.redFlags).toHaveLength(0);
  });

  it("raises red flags and stops weak ideas", () => {
    const answers = Object.fromEntries(CRITERIA.map((c) => [c.id, { score: 1, evidence: "guess" as const }]));
    const r = evaluateValidation(answers);
    expect(r.score).toBe(0);
    expect(r.verdict).toBe("stop");
    expect(r.redFlags.length).toBeGreaterThanOrEqual(3);
  });

  it("is incomplete with fewer than 10 answers", () => {
    expect(evaluateValidation({ problem_pain: { score: 5, evidence: "data" } }).verdict).toBe("incomplete");
  });

  it("upgrades evidence when a linked hypothesis is validated", () => {
    const answers = { problem_pain: { score: 4, evidence: "guess" as const } };
    const r = evaluateValidation(answers, [
      {
        id: "h",
        statement: "x",
        type: "problem",
        criterionId: "problem_pain",
        impact: 5,
        confidence: 5,
        ease: 5,
        successMetric: "",
        status: "validated",
        result: "",
      },
    ]);
    expect(r.results.find((x) => x.criterion.id === "problem_pain")?.effectiveEvidence).toBe("data");
    expect(r.confidence).toBeCloseTo(1);
  });

  it("maps computed metrics to criterion scores", () => {
    expect(marketSizeToScore(50e9)).toBe(5);
    expect(marketSizeToScore(5e7)).toBe(1);
    expect(ltvCacToScore(3.5)).toBe(4);
    expect(ltvCacToScore(0.5)).toBe(1);
  });
});

describe("unit economics", () => {
  const input: UnitEconomicsInput = {
    avgCheck: 1000,
    purchasesPerMonth: 1,
    grossMargin: 0.8,
    monthlyChurn: 0.05,
    cacMode: "direct",
    cac: 4000,
    costPerLead: 500,
    leadToCustomer: 0.1,
    fixedCostsMonthly: 80_000,
    discountRateYear: 0,
  };

  it("computes LTV, LTV/CAC and payback", () => {
    const r = computeUnitEconomics(input);
    expect(r.arpu).toBe(1000);
    expect(r.contribution).toBe(800);
    expect(r.lifetimeMonths).toBeCloseTo(20);
    expect(r.ltv).toBeCloseTo(16000);
    expect(r.ltvToCac).toBeCloseTo(4);
    expect(r.paybackMonths).toBeCloseTo(5);
    expect(r.breakEvenCustomers).toBeCloseTo(100);
    expect(r.health.ltvToCac).toBe("good");
    // Undiscounted geometric LTV ≈ contribution / churn.
    expect(r.ltvDiscounted).toBeCloseTo(16000, -2);
  });

  it("derives CAC from the funnel", () => {
    expect(computeUnitEconomics({ ...input, cacMode: "funnel" }).cac).toBeCloseTo(5000);
  });

  it("ranks sensitivity drivers by impact", () => {
    const rows = sensitivity(input);
    expect(rows).toHaveLength(5);
    for (let i = 1; i < rows.length; i++) expect(rows[i - 1].range).toBeGreaterThanOrEqual(rows[i].range);
  });
});

describe("market sizing", () => {
  it("computes TAM/SAM/SOM both ways and flags aggressive SOM", () => {
    const r = computeMarket({
      geography: "РФ",
      topDown: { totalCustomers: 1000, annualSpendPerCustomer: 10_000, segmentShare: 0.5, obtainableShare: 0.2 },
      bottomUp: { targetCustomers: 500, pricePerPurchase: 1000, purchasesPerYear: 10, reachShare: 0.5, conversionShare: 0.1 },
    });
    expect(r.topDown.tam).toBe(10_000_000);
    expect(r.topDown.sam).toBe(5_000_000);
    expect(r.topDown.som).toBe(1_000_000);
    expect(r.bottomUp.sam).toBe(5_000_000);
    expect(r.bottomUp.customers).toBe(25);
    expect(r.bottomUp.som).toBe(250_000);
    expect(r.samMismatch).toBeCloseTo(1);
    expect(r.warnings.some((w) => w.includes("агрессивно"))).toBe(true);
  });
});

describe("financial model", () => {
  it("accumulates customers and revenue linearly with constant organic inflow", () => {
    const r = computeFinance(baseFinance());
    expect(r.rows).toHaveLength(24);
    expect(r.rows[0].activeCustomers).toBe(10);
    expect(r.rows[11].activeCustomers).toBe(120);
    expect(r.years[0].revenue).toBe((100 * 10 * (12 * 13)) / 2);
    expect(r.breakEvenMonth).toBe(1);
    expect(r.fundingNeed).toBe(0);
  });

  it("treats churn = 100% as one-time purchases", () => {
    const r = computeFinance(baseFinance({ monthlyChurn: 1 }));
    expect(r.rows[5].activeCustomers).toBe(10);
    expect(r.rows[5].revenue).toBe(1000);
  });

  it("computes funding need, gap and runway", () => {
    const r = computeFinance(
      baseFinance({
        startingCash: 10_000,
        costs: [{ id: "c", name: "Rent", monthly: 5000, startMonth: 1, growthPerYear: 0 }],
        organicStart: 2,
      }),
    );
    // Month t revenue = 200t, EBITDA = 200t − 5000 → positive from month 25 (beyond horizon).
    expect(r.breakEvenMonth).toBeNull();
    expect(r.fundingNeed).toBeGreaterThan(0);
    expect(r.fundingGap).toBeGreaterThan(0);
    expect(r.runwayMonths).not.toBeNull();
    expect(r.rows[0].cash).toBe(10_000 + 200 - 5000);
  });

  it("delays revenue until launch and pays salaries with payroll tax", () => {
    const r = computeFinance(
      baseFinance({ launchMonth: 4, team: [{ id: "t", role: "Dev", salary: 1000, count: 2, startMonth: 1 }], payrollTax: 0.3 }),
    );
    expect(r.rows[2].revenue).toBe(0);
    expect(r.rows[3].revenue).toBe(1000);
    expect(r.rows[0].payroll).toBeCloseTo(2600);
    expect(r.rows[0].headcount).toBe(2);
  });

  it("applies profit tax with loss carry-forward", () => {
    const r = computeFinance(
      baseFinance({
        horizonMonths: 3,
        organicStart: 0,
        initialCustomers: 0,
        taxMode: "profit",
        taxRate: 0.2,
        capex: [],
        costs: [{ id: "c", name: "x", monthly: 1000, startMonth: 1, growthPerYear: 0 }],
        funding: [],
      }),
    );
    expect(r.rows.every((x) => x.tax === 0)).toBe(true);
  });

  it("depreciates capex and records the cash outflow once", () => {
    const r = computeFinance(baseFinance({ capex: [{ id: "k", name: "PC", amount: 1200, month: 1, depreciationMonths: 12 }] }));
    expect(r.rows[0].capex).toBe(1200);
    expect(r.rows[1].capex).toBe(0);
    expect(r.rows[0].depreciation).toBe(100);
    expect(r.rows[12].depreciation).toBe(0);
  });

  it("orders scenarios: pessimistic ≤ base ≤ optimistic revenue", () => {
    const a = demoProject().finance;
    const rev = SCENARIOS.map((s) => computeFinance(applyScenario(a, s)).totalRevenue);
    expect(rev[0]).toBeLessThan(rev[1]);
    expect(rev[1]).toBeLessThan(rev[2]);
  });

  it("solves IRR", () => {
    expect(irr([-100, 110])).toBeCloseTo(0.1, 6);
    expect(irr([100, 100])).toBeNull();
  });
});

describe("monte carlo", () => {
  it("is deterministic and produces ordered percentile bands", () => {
    const base = demoProject();
    const cfg = { ...base.monteCarlo, runs: 300 };
    const a = runMonteCarlo(base.finance, cfg);
    const b = runMonteCarlo(base.finance, cfg);
    expect(a.npv.p50).toBe(b.npv.p50);
    expect(a.months).toHaveLength(base.finance.horizonMonths);
    a.months.forEach((_, i) => {
      expect(a.cash.p10[i]).toBeLessThanOrEqual(a.cash.p50[i]);
      expect(a.cash.p50[i]).toBeLessThanOrEqual(a.cash.p90[i]);
    });
    expect(a.probBreakEven).toBeGreaterThanOrEqual(0);
    expect(a.probBreakEven).toBeLessThanOrEqual(1);
    expect(a.fundingNeed.p10).toBeLessThanOrEqual(a.fundingNeed.p90);
  });

  it("computes percentiles and histograms", () => {
    expect(percentile([1, 2, 3, 4, 5], 0.5)).toBe(3);
    const h = histogram([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5);
    expect(h).toHaveLength(5);
    expect(h.reduce((s, b) => s + b.count, 0)).toBe(10);
  });
});

describe("project analysis & plan", () => {
  it("analyzes the demo project end-to-end", () => {
    const p = demoProject();
    const a = analyzeProject(p);
    expect(a.validation.verdict).not.toBe("incomplete");
    expect(a.readiness.score).toBeGreaterThan(50);
    expect(a.readiness.score).toBeLessThanOrEqual(100);
    expect(a.lean.completeness).toBeGreaterThan(0.9);
    expect(a.checks.length).toBeGreaterThan(0);
  });

  it("detects ARPU mismatch between unit economics and the financial model", () => {
    const p = demoProject();
    p.finance.arpu = p.finance.arpu * 3;
    expect(analyzeProject(p).checks.some((c) => c.id === "arpu")).toBe(true);
  });

  it("creates a project from a generated idea with prefilled modules", () => {
    const [idea] = generateIdeas({ method: "trend_industry", count: 1, seed: 9 });
    const p = projectFromIdea(idea);
    expect(p.idea.title).toBe(idea.title);
    expect(Object.keys(p.validation).length).toBeGreaterThan(0);
    expect(p.lean.problem).toBe(idea.problem);
    expect(p.hypotheses.length).toBe(3);
    expect(p.finance.arpu).toBeGreaterThan(0);
  });

  it("builds a business plan with all sections and honours overrides", () => {
    const p = demoProject();
    const a = analyzeProject(p);
    const md = buildBusinessPlan({ project: p, analysis: a });
    for (const s of PLAN_SECTIONS) expect(md).toContain(s.title);
    expect(md).not.toContain("undefined");
    expect(md).not.toContain("NaN");
    p.plan.overrides.summary = "Свой текст резюме";
    expect(buildSection("summary", { project: p, analysis: a })).toBe("Свой текст резюме");
  });

  it("derives funding ask from the model when not set", () => {
    const p = createProject({ title: "Тест" });
    const a = analyzeProject(p);
    expect(fundingAsk(p, a)).toBeGreaterThanOrEqual(0);
  });
});

describe("canvas, risks, experiments", () => {
  it("finds canvas issues", () => {
    const r = analyzeLean({ problem: "Долго", unfairAdvantage: "Высокое качество и низкая цена услуг" });
    expect(r.issues.length).toBeGreaterThan(0);
    expect(leanToBmc({ uniqueValueProposition: "A", solution: "B" }).valuePropositions).toBe("A\nB");
  });

  it("classifies risks", () => {
    expect(riskLevel(25)).toBe("critical");
    expect(riskLevel(4)).toBe("low");
    const s = summarizeRisks(demoProject().risks);
    expect(s.total).toBe(6);
  });

  it("suggests SWOT from analysis", () => {
    const p = demoProject();
    const a = analyzeProject(p);
    const swot = suggestSwot(p, a.validation, a.unit, a.market);
    expect(swot.strengths.length).toBeGreaterThan(0);
    expect(swot.threats.length).toBeGreaterThan(0);
  });

  it("prioritises risky high-impact hypotheses", () => {
    expect(priorityScore({ impact: 10, confidence: 1, ease: 10 })).toBe(100);
    expect(priorityScore({ impact: 10, confidence: 10, ease: 10 })).toBe(10);
    expect(recommendExperiments("wtp")[0].evidence).toBeGreaterThanOrEqual(4);
    expect(interviewScript({ audience: "владельцы кафе", problem: "списания" }).problem[0]).toContain("списания");
  });
});
