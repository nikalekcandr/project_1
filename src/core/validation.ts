import type { CriterionAnswer, CriterionId, EvidenceLevel, Hypothesis, ValidationAnswers } from "./types";

export type DimensionId = "problem" | "market" | "solution" | "economics" | "execution";

export interface Criterion {
  id: CriterionId;
  dimension: DimensionId;
  name: string;
  question: string;
  weight: number;
  anchors: [string, string, string]; // descriptions for scores 1, 3, 5
  advice: string;
  /** Score at or below which the criterion becomes a red flag. */
  redFlagAt?: number;
  redFlag?: string;
}

export const DIMENSIONS: Record<DimensionId, string> = {
  problem: "Проблема",
  market: "Рынок",
  solution: "Решение",
  economics: "Экономика",
  execution: "Исполнение",
};

export const CRITERIA: Criterion[] = [
  {
    id: "problem_pain",
    dimension: "problem",
    name: "Острота проблемы",
    question: "Насколько болезненна проблема для клиента? Это «таблетка» или «витамин»?",
    weight: 3,
    anchors: [
      "Приятно было бы решить, но можно жить и так",
      "Заметное неудобство, клиенты ищут решения",
      "Острая боль: клиенты теряют деньги/время и уже платят за обходные решения",
    ],
    advice:
      "Проведите 10–15 проблемных интервью. Ищите людей, которые уже тратят деньги или время на обходные решения — это главный признак боли.",
    redFlagAt: 2,
    redFlag: "Проблема недостаточно острая — продукт рискует стать «витамином», за который не платят",
  },
  {
    id: "problem_frequency",
    dimension: "problem",
    name: "Частота проблемы",
    question: "Как часто клиент сталкивается с проблемой?",
    weight: 1.5,
    anchors: ["Раз в несколько лет", "Несколько раз в год", "Каждую неделю или каждый день"],
    advice:
      "Редкие проблемы дают дорогое привлечение и низкое удержание. Подумайте о смежных частых задачах клиента, которые можно добавить в продукт.",
  },
  {
    id: "willingness_to_pay",
    dimension: "problem",
    name: "Готовность платить",
    question: "Готовы ли клиенты платить за решение и есть ли у них бюджет?",
    weight: 2.5,
    anchors: [
      "Ожидают бесплатного решения",
      "Готовы платить, если цена невысокая",
      "Уже платят за альтернативы и готовы платить больше за лучшее решение",
    ],
    advice: "Проверьте готовность платить действием, а не словами: предоплата, предзаказ, LOI или платный пилот.",
    redFlagAt: 2,
    redFlag: "Нет подтверждённой готовности платить — выручка под вопросом",
  },
  {
    id: "market_size",
    dimension: "market",
    name: "Размер рынка",
    question: "Достаточно ли велик доступный рынок (SAM) для вашей цели?",
    weight: 2,
    anchors: ["Узкая ниша, SAM < 100 млн ₽", "SAM 1–5 млрд ₽", "Большой рынок, SAM > 30 млрд ₽"],
    advice: "Посчитайте рынок снизу вверх (число клиентов × чек × частота). Если ниша мала, продумайте путь расширения в смежные сегменты.",
    redFlagAt: 1,
    redFlag: "Рынок слишком мал, чтобы построить устойчивый бизнес",
  },
  {
    id: "market_growth",
    dimension: "market",
    name: "Рост рынка и тайминг",
    question: "Растёт ли рынок? Почему именно сейчас подходящее время?",
    weight: 1.5,
    anchors: ["Рынок стагнирует или сокращается", "Стабильный рост", "Быстрый рост, есть явный триггер «почему сейчас»"],
    advice: "Сформулируйте «почему сейчас»: какое изменение (технология, закон, поведение) открыло окно возможностей.",
  },
  {
    id: "competition",
    dimension: "market",
    name: "Конкурентная среда",
    question: "Насколько сложно выиграть у конкурентов? (5 — конкуренция слабая)",
    weight: 1.5,
    anchors: [
      "Сильные игроки с огромными ресурсами",
      "Конкуренты есть, но с заметными слабостями",
      "Конкуренты слабые или решают задачу плохо",
    ],
    advice:
      "Соберите отзывы о конкурентах и найдите повторяющиеся жалобы клиентов — это ваша точка входа. Фокус на нише, где лидеры слабы.",
  },
  {
    id: "differentiation",
    dimension: "solution",
    name: "Уникальность и защита",
    question: "Чем решение принципиально лучше альтернатив и что сложно скопировать?",
    weight: 2,
    anchors: [
      "Похоже на существующие решения",
      "Заметно лучше по одному важному параметру",
      "В 10 раз лучше + защитный ров (данные, сеть, технологии)",
    ],
    advice:
      "Ищите «несправедливое преимущество»: эксклюзивный доступ, данные, сетевой эффект, экспертиза команды. Улучшение должно быть кратным, а не на 10%.",
  },
  {
    id: "unit_economics",
    dimension: "economics",
    name: "Юнит-экономика",
    question: "Сходится ли экономика одного клиента (LTV/CAC, маржа, окупаемость)?",
    weight: 2,
    anchors: ["LTV < CAC", "LTV/CAC ≈ 2, окупаемость > года", "LTV/CAC ≥ 3, окупаемость < 12 мес."],
    advice:
      "Посчитайте юнит-экономику во вкладке «Юнит-экономика». Рычаги: цена, удержание, маржинальность, дешёвые каналы (реферальные, SEO).",
    redFlagAt: 1,
    redFlag: "Экономика клиента не сходится — каждый новый клиент увеличивает убыток",
  },
  {
    id: "capital_intensity",
    dimension: "economics",
    name: "Капиталоёмкость",
    question: "Сколько денег нужно до первой выручки и до безубыточности? (5 — мало)",
    weight: 1,
    anchors: ["Десятки миллионов до первых продаж", "Несколько миллионов", "Можно стартовать почти без вложений"],
    advice: "Найдите способ получить первые деньги до больших вложений: предпродажи, консьерж-MVP, аренда вместо покупки.",
  },
  {
    id: "go_to_market",
    dimension: "execution",
    name: "Каналы привлечения",
    question: "Понятно ли, где и как дёшево находить клиентов?",
    weight: 2,
    anchors: ["Непонятно, где искать клиентов", "Есть гипотезы каналов, не проверены", "Проверенный канал с понятной стоимостью клиента"],
    advice: "Протестируйте 3–5 каналов малыми бюджетами. Для B2B — составьте список первых 50 компаний и выйдите на них лично.",
  },
  {
    id: "founder_fit",
    dimension: "execution",
    name: "Команда и экспертиза",
    question: "Есть ли у команды нужный опыт, связи и мотивация?",
    weight: 2,
    anchors: ["Нет опыта в отрасли и ключевых навыков", "Часть компетенций есть", "Глубокая экспертиза, связи в отрасли, полная команда"],
    advice: "Закройте недостающие компетенции сооснователем или советником. Отраслевая экспертиза и связи часто важнее технологий.",
    redFlagAt: 1,
    redFlag: "У команды нет ключевых компетенций для исполнения",
  },
  {
    id: "mvp_feasibility",
    dimension: "solution",
    name: "Простота MVP",
    question: "Насколько быстро и дёшево можно сделать первую версию?",
    weight: 1.5,
    anchors: ["Больше года разработки и большая команда", "2–4 месяца", "MVP за 2–4 недели (no-code, консьерж)"],
    advice: "Урежьте MVP до одного ключевого сценария. Проверьте, нельзя ли сначала оказать ценность вручную.",
  },
  {
    id: "scalability",
    dimension: "solution",
    name: "Масштабируемость",
    question: "Может ли бизнес расти без пропорционального роста затрат?",
    weight: 1.5,
    anchors: ["Рост только пропорционально найму", "Частично автоматизируется", "Рост почти без роста затрат (софт, сеть)"],
    advice: "Ищите, какие части процесса можно стандартизировать и автоматизировать, а какие — передать партнёрам или самим клиентам.",
  },
  {
    id: "regulatory_risk",
    dimension: "execution",
    name: "Регуляторные риски",
    question: "Насколько бизнес зависит от лицензий, законов и согласований? (5 — риски низкие)",
    weight: 1,
    anchors: ["Нужны лицензии, высокий риск запретов", "Есть требования, но они понятны", "Регулирование практически отсутствует"],
    advice: "Проконсультируйтесь с профильным юристом до запуска. Ищите модель, которая обходит лицензируемую часть через партнёров.",
  },
];

export const EVIDENCE: Record<EvidenceLevel, { label: string; weight: number; hint: string }> = {
  guess: { label: "Предположение", weight: 0.2, hint: "Наше мнение, ничем не подтверждено" },
  research: { label: "Исследование", weight: 0.6, hint: "Открытые данные, отчёты, интервью" },
  data: { label: "Подтверждено", weight: 1, hint: "Реальное поведение: продажи, предоплаты, метрики" },
};

export type Verdict = "go" | "promising" | "pivot" | "stop" | "incomplete";

export const VERDICTS: Record<Verdict, { label: string; description: string; tone: "good" | "ok" | "warn" | "bad" | "muted" }> = {
  go: {
    label: "GO — сильная идея",
    description: "Идея выглядит сильной. Переходите к экспериментам с реальными деньгами: предпродажи, платный пилот, MVP.",
    tone: "good",
  },
  promising: {
    label: "Перспективно — доработать",
    description: "Есть потенциал, но слабые места нужно усилить до серьёзных вложений. Сфокусируйтесь на рекомендациях ниже.",
    tone: "ok",
  },
  pivot: {
    label: "Нужен пивот",
    description: "В текущем виде идея рискованна. Рассмотрите смену сегмента, модели монетизации или формата решения.",
    tone: "warn",
  },
  stop: {
    label: "Стоп — не вкладываться",
    description: "Слишком много фундаментальных проблем. Лучше вернуться к генерации идей или радикально переосмыслить концепцию.",
    tone: "bad",
  },
  incomplete: {
    label: "Недостаточно данных",
    description: "Оцените хотя бы 10 критериев, чтобы получить вывод.",
    tone: "muted",
  },
};

export interface CriterionResult {
  criterion: Criterion;
  answer?: CriterionAnswer;
  effectiveEvidence: EvidenceLevel;
  normalized: number; // 0..1
}

export interface ValidationResult {
  score: number; // 0..100
  confidence: number; // 0..1
  answered: number;
  total: number;
  verdict: Verdict;
  dimensions: { id: DimensionId; label: string; score: number }[];
  redFlags: string[];
  strengths: Criterion[];
  weaknesses: { criterion: Criterion; gap: number }[];
  riskiestAssumptions: Criterion[];
  results: CriterionResult[];
}

export function evaluateValidation(answers: ValidationAnswers, hypotheses: Hypothesis[] = []): ValidationResult {
  const validatedFor = new Set(hypotheses.filter((h) => h.status === "validated" && h.criterionId).map((h) => h.criterionId));
  const invalidated = hypotheses.filter((h) => h.status === "invalidated");

  const results: CriterionResult[] = CRITERIA.map((criterion) => {
    const answer = answers[criterion.id];
    const evidence: EvidenceLevel = validatedFor.has(criterion.id) ? "data" : (answer?.evidence ?? "guess");
    return {
      criterion,
      answer,
      effectiveEvidence: evidence,
      normalized: answer ? (answer.score - 1) / 4 : 0,
    };
  });

  const answeredResults = results.filter((r) => r.answer);
  const weightSum = answeredResults.reduce((s, r) => s + r.criterion.weight, 0);
  const score = weightSum ? (answeredResults.reduce((s, r) => s + r.normalized * r.criterion.weight, 0) / weightSum) * 100 : 0;
  const confidence = weightSum
    ? answeredResults.reduce((s, r) => s + EVIDENCE[r.effectiveEvidence].weight * r.criterion.weight, 0) / weightSum
    : 0;

  const dimensions = (Object.keys(DIMENSIONS) as DimensionId[]).map((id) => {
    const rs = answeredResults.filter((r) => r.criterion.dimension === id);
    const w = rs.reduce((s, r) => s + r.criterion.weight, 0);
    return {
      id,
      label: DIMENSIONS[id],
      score: w ? (rs.reduce((s, r) => s + r.normalized * r.criterion.weight, 0) / w) * 100 : 0,
    };
  });

  const redFlags: string[] = [];
  for (const r of answeredResults) {
    if (r.criterion.redFlagAt != null && r.answer!.score <= r.criterion.redFlagAt && r.criterion.redFlag) {
      redFlags.push(r.criterion.redFlag);
    }
  }
  for (const h of invalidated) {
    redFlags.push(`Гипотеза опровергнута: «${h.statement}»`);
  }

  const strengths = answeredResults.filter((r) => r.answer!.score >= 4).map((r) => r.criterion);
  const weaknesses = answeredResults
    .map((r) => ({ criterion: r.criterion, gap: (1 - r.normalized) * r.criterion.weight }))
    .filter((w) => w.gap > 0.5 * w.criterion.weight)
    .sort((a, b) => b.gap - a.gap);

  // High-weight criteria that look good on paper but rest on guesses are the riskiest assumptions.
  const riskiestAssumptions = answeredResults
    .filter((r) => r.effectiveEvidence === "guess" && r.answer!.score >= 3)
    .sort((a, b) => b.criterion.weight - a.criterion.weight)
    .slice(0, 4)
    .map((r) => r.criterion);

  let verdict: Verdict;
  const criticalFlags = redFlags.length;
  if (answeredResults.length < 10) verdict = "incomplete";
  else if (score < 40 || criticalFlags >= 3) verdict = "stop";
  else if (score < 55 || criticalFlags >= 2) verdict = "pivot";
  else if (score < 72 || criticalFlags >= 1) verdict = "promising";
  else verdict = "go";

  return {
    score,
    confidence,
    answered: answeredResults.length,
    total: CRITERIA.length,
    verdict,
    dimensions,
    redFlags,
    strengths,
    weaknesses,
    riskiestAssumptions,
    results,
  };
}

/** Maps a market size (SAM, in currency units) to a 1..5 score for the market_size criterion. */
export function marketSizeToScore(sam: number): number {
  if (sam >= 30e9) return 5;
  if (sam >= 5e9) return 4;
  if (sam >= 1e9) return 3;
  if (sam >= 1e8) return 2;
  return 1;
}

/** Maps LTV/CAC to a 1..5 score for the unit_economics criterion. */
export function ltvCacToScore(ratio: number): number {
  if (!Number.isFinite(ratio)) return 5;
  if (ratio >= 4) return 5;
  if (ratio >= 3) return 4;
  if (ratio >= 2) return 3;
  if (ratio >= 1) return 2;
  return 1;
}
