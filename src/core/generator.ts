import { capitalize, clamp } from "./format";
import { BUSINESS_MODELS, getModel, type BusinessModelPattern } from "./knowledge/businessModels";
import { INDUSTRIES, getIndustry, type Industry, type IndustryProblem } from "./knowledge/industries";
import { ANALOGIES, SCAMPER, SKILLS } from "./knowledge/library";
import { TRENDS, getTrend, type Trend } from "./knowledge/trends";
import { createRng, pick, type Rng } from "./random";
import type { FounderProfile, GenerationMethod, Idea, Segment, SkillId } from "./types";

export type GeneratorMethod = Exclude<GenerationMethod, "scamper" | "ai"> | "mix";

export interface GeneratorOptions {
  method: GeneratorMethod;
  count: number;
  seed: number;
  industries?: string[];
  trends?: string[];
  models?: string[];
  segments?: Segment[];
  profile?: FounderProfile;
}

interface SolutionFormat {
  label: string;
  template: string;
  models: string[];
  segments: Segment[];
}

const SOLUTION_FORMATS: SolutionFormat[] = [
  { label: "Сервис «под ключ»", template: "сервис «под ключ», который полностью берёт на себя задачу — {job}", models: ["service", "productized"], segments: ["b2b", "b2c", "b2b2c"] },
  { label: "Онлайн-платформа", template: "онлайн-платформа, которая помогает {job}", models: ["saas", "freemium", "pay_per_use"], segments: ["b2b", "b2c", "b2b2c"] },
  { label: "Маркетплейс", template: "маркетплейс проверенных исполнителей, который помогает {job}", models: ["marketplace", "lead_gen"], segments: ["b2b", "b2c"] },
  { label: "Мобильное приложение", template: "мобильное приложение, которое помогает {job}", models: ["freemium", "saas"], segments: ["b2c"] },
  { label: "Продуктовый бренд", template: "продуктовый бренд с готовыми наборами, которые помогают {job}", models: ["d2c", "razor_blades"], segments: ["b2c"] },
  { label: "Программа обучения", template: "практическая программа, которая учит {job}", models: ["courses", "community"], segments: ["b2c", "b2b"] },
];

const CAPITAL_BUDGET: Record<number, number> = { 1: 100_000, 2: 300_000, 3: 1_000_000, 4: 3_000_000, 5: 10_000_000 };

/** Rough capital needed to reach first revenue, by capital-intensity level 1..5. */
export function capitalNeeded(level: number): number {
  return CAPITAL_BUDGET[clamp(Math.round(level), 1, 5)];
}

export interface QuickScoreResult {
  score: number;
  notes: string[];
  parts: { market: number; competition: number; model: number; feasibility: number; regulation: number; founderFit: number };
}

/** Heuristic pre-score (0..100) of an idea from the knowledge base and the founder profile. */
export function quickScore(
  industry: Industry | undefined,
  model: BusinessModelPattern | undefined,
  trend: Trend | undefined,
  segment: Segment,
  profile?: FounderProfile,
): QuickScoreResult {
  const notes: string[] = [];
  const norm = (v: number) => (clamp(v, 1, 5) - 1) / 4;

  const growth = industry?.growth ?? 3;
  const momentum = trend?.momentum ?? 3;
  const market = norm((growth + momentum) / 2);
  if (growth >= 4) notes.push("➕ Растущая отрасль");
  if (trend && trend.momentum >= 4) notes.push(`➕ Сильный тренд: ${trend.name}`);

  const competition = norm(6 - (industry?.competition ?? 3));
  if ((industry?.competition ?? 0) >= 5) notes.push("➖ Очень высокая конкуренция — нужна сильная дифференциация");

  const modelScore = model ? norm((model.scalability + model.speedToRevenue) / 2) : 0.5;
  if (model && model.scalability >= 5) notes.push("➕ Хорошо масштабируемая модель");
  if (model && model.speedToRevenue >= 4) notes.push("➕ Быстрые первые деньги");

  const capitalLevel = Math.max(industry?.capital ?? 3, model?.capital ?? 3);
  let feasibility = norm(6 - capitalLevel);
  if (profile) {
    const need = capitalNeeded(capitalLevel);
    if (profile.budget < need * 0.5) {
      feasibility *= 0.4;
      notes.push("➖ Потребуется заметно больше капитала, чем ваш бюджет");
    } else if (profile.budget >= need) {
      feasibility = Math.min(1, feasibility + 0.25);
      notes.push("➕ Старт укладывается в ваш бюджет");
    }
  }

  const regulation = norm(6 - (industry?.regulation ?? 3));
  if ((industry?.regulation ?? 0) >= 5) notes.push("➖ Жёсткое регулирование отрасли");

  let founderFit = 0.5;
  if (profile) {
    const required = new Set<SkillId>([...(industry?.skills ?? []), ...(model?.skills ?? []), ...(trend?.skills ?? [])]);
    const have = [...required].filter((s) => profile.skills.includes(s));
    const coverage = required.size ? have.length / required.size : 0.5;
    founderFit = coverage * 0.7;
    if (industry && profile.interests.includes(industry.id)) {
      founderFit += 0.2;
      notes.push("➕ Отрасль совпадает с вашими интересами");
    }
    if (profile.preferredSegments.length === 0 || profile.preferredSegments.includes(segment)) founderFit += 0.1;
    founderFit = clamp(founderFit, 0, 1);
    const missing = [...required].filter((s) => !profile.skills.includes(s)).map((s) => SKILLS[s].toLowerCase());
    if (missing.length) notes.push(`⚠️ Не хватает компетенций: ${missing.slice(0, 3).join(", ")}`);
    else notes.push("➕ Ваши навыки покрывают все ключевые компетенции");
  }

  const parts = { market, competition, model: modelScore, feasibility, regulation, founderFit };
  const score =
    market * 25 + competition * 10 + modelScore * 20 + feasibility * 15 + regulation * 10 + founderFit * 20;
  return { score: Math.round(score), notes, parts };
}

function weightedPick<T>(rng: Rng, items: readonly T[], weight: (item: T) => number): T {
  const weights = items.map((i) => Math.max(0, weight(i)));
  const total = weights.reduce((a, b) => a + b, 0);
  if (total <= 0) return pick(rng, items);
  let r = rng() * total;
  for (let i = 0; i < items.length; i++) {
    r -= weights[i];
    if (r <= 0) return items[i];
  }
  return items[items.length - 1];
}

function fillJob(template: string, problem: IndustryProblem): string {
  return template.replaceAll("{job}", problem.job);
}

const PHYSICAL_MODELS = new Set(["d2c", "razor_blades", "rental"]);

function compatibleModels(segment: Segment, allowed?: string[], industry?: Industry): BusinessModelPattern[] {
  const pool = BUSINESS_MODELS.filter(
    (m) => (!allowed?.length || allowed.includes(m.id)) && (industry?.physical !== false || !PHYSICAL_MODELS.has(m.id)),
  );
  const fit = pool.filter((m) => m.segments.includes(segment) || (segment === "b2b2c" && m.segments.includes("b2b")));
  return fit.length ? fit : pool.length ? pool : BUSINESS_MODELS;
}

interface Draft {
  key: string;
  title: string;
  solution: string;
  industry: Industry;
  problem: IndustryProblem;
  model: BusinessModelPattern;
  trend?: Trend;
  method: Exclude<GeneratorMethod, "mix">;
  tags: string[];
}

function draftTrendIndustry(rng: Rng, industries: Industry[], opts: GeneratorOptions): Draft {
  const industry = pick(rng, industries);
  const problem = pick(rng, industry.problems);
  const trendPool = TRENDS.filter((t) => !opts.trends?.length || opts.trends.includes(t.id));
  const pool = trendPool.length ? trendPool : TRENDS;
  // Mostly trends that genuinely fit the industry; occasionally a wild card for unexpected combinations.
  const fitting = pool.filter((t) => t.boosts.includes(industry.id));
  const trend = weightedPick(rng, fitting.length && rng() < 0.85 ? fitting : pool, (t) => t.momentum);
  const compatible = compatibleModels(problem.segment, opts.models, industry);
  const affine = compatible.filter((m) => trend.models.includes(m.id));
  const model = pick(rng, affine.length ? affine : compatible);
  const solution = fillJob(pick(rng, trend.solutionTemplates), problem);
  return {
    key: `ti:${industry.id}:${problem.name}:${trend.id}`,
    title: `${trend.titlePrefix}: ${problem.name}`,
    solution,
    industry,
    problem,
    model,
    trend,
    method: "trend_industry",
    tags: [industry.name, trend.name, model.name],
  };
}

function draftTransplant(rng: Rng, industries: Industry[], opts: GeneratorOptions): Draft {
  const industry = pick(rng, industries);
  const problem = pick(rng, industry.problems);
  const analogies = ANALOGIES.filter((a) => !opts.models?.length || opts.models.includes(a.modelId));
  const analogy = pick(rng, analogies.length ? analogies : ANALOGIES);
  const model = getModel(analogy.modelId) ?? pick(rng, compatibleModels(problem.segment, opts.models, industry));
  return {
    key: `mt:${industry.id}:${problem.name}:${analogy.name}`,
    title: `«${analogy.name} ${industry.forShort}»: ${problem.name}`,
    solution: `сервис по модели ${analogy.name} — ${analogy.essence}, — который помогает ${problem.job}`,
    industry,
    problem,
    model,
    method: "model_transplant",
    tags: [industry.name, `Модель ${analogy.name}`, model.name],
  };
}

function draftProblemFirst(rng: Rng, industries: Industry[], opts: GeneratorOptions): Draft {
  const industry = pick(rng, industries);
  const problem = pick(rng, industry.problems);
  const compatible = compatibleModels(problem.segment, opts.models, industry);
  const formats = SOLUTION_FORMATS.filter(
    (f) => f.segments.includes(problem.segment) && f.models.some((m) => compatible.some((cm) => cm.id === m)),
  );
  const format = pick(rng, formats.length ? formats : SOLUTION_FORMATS);
  const fitting = compatible.filter((m) => format.models.includes(m.id));
  const model = pick(rng, fitting.length ? fitting : compatible);
  return {
    key: `pf:${industry.id}:${problem.name}:${format.label}`,
    title: `${format.label}: ${problem.name}`,
    solution: fillJob(format.template, problem),
    industry,
    problem,
    model,
    method: "problem_first",
    tags: [industry.name, format.label, model.name],
  };
}

export function generateIdeas(opts: GeneratorOptions): Idea[] {
  const rng = createRng(opts.seed);
  let industries = INDUSTRIES.filter((i) => !opts.industries?.length || opts.industries.includes(i.id));
  if (!industries.length) industries = INDUSTRIES;
  if (opts.segments?.length) {
    const bySegment = industries
      .map((i) => ({ ...i, problems: i.problems.filter((p) => opts.segments!.includes(p.segment)) }))
      .filter((i) => i.problems.length > 0);
    if (bySegment.length) industries = bySegment;
  }

  const methods: Exclude<GeneratorMethod, "mix">[] = ["trend_industry", "model_transplant", "problem_first"];
  const seen = new Set<string>();
  const ideas: Idea[] = [];
  const maxAttempts = opts.count * 25;
  for (let attempt = 0; attempt < maxAttempts && ideas.length < opts.count; attempt++) {
    const method = opts.method === "mix" ? pick(rng, methods) : opts.method;
    const draft =
      method === "trend_industry"
        ? draftTrendIndustry(rng, industries, opts)
        : method === "model_transplant"
          ? draftTransplant(rng, industries, opts)
          : draftProblemFirst(rng, industries, opts);
    if (seen.has(draft.key)) continue;
    seen.add(draft.key);
    const qs = quickScore(draft.industry, draft.model, draft.trend, draft.problem.segment, opts.profile);
    ideas.push({
      id: `idea_${opts.seed.toString(36)}_${ideas.length}`,
      title: capitalize(draft.title),
      oneLiner: `${capitalize(draft.solution)}. ${draft.model.offer}`,
      problem: draft.problem.problem,
      solution: capitalize(draft.solution),
      audience: capitalize(draft.problem.audience),
      segment: draft.problem.segment,
      industryId: draft.industry.id,
      modelId: draft.model.id,
      trendIds: draft.trend ? [draft.trend.id] : [],
      method: draft.method,
      quickScore: qs.score,
      scoreNotes: qs.notes,
      tags: draft.tags,
      createdAt: Date.now(),
    });
  }
  return ideas.sort((a, b) => (b.quickScore ?? 0) - (a.quickScore ?? 0));
}

export interface ScamperResult {
  key: string;
  name: string;
  question: string;
  ideas: string[];
}

export function scamperIdeas(base: string): ScamperResult[] {
  const subject = base.trim() || "ваш бизнес";
  return SCAMPER.map((t) => ({
    key: t.key,
    name: t.name,
    question: t.question,
    ideas: t.templates.map((tpl) => capitalize(tpl.replaceAll("{base}", subject))),
  }));
}

/** Re-scores an existing idea (e.g. after the founder profile changed). */
export function rescoreIdea(idea: Idea, profile?: FounderProfile): Idea {
  const qs = quickScore(
    getIndustry(idea.industryId),
    getModel(idea.modelId),
    idea.trendIds?.length ? getTrend(idea.trendIds[0]) : undefined,
    idea.segment,
    profile,
  );
  return { ...idea, quickScore: qs.score, scoreNotes: qs.notes };
}
