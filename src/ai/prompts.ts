import type { ProjectAnalysis } from "../core/analysis";
import { LEAN_BLOCKS } from "../core/canvas";
import { fmtMoney, fmtNumber, fmtPercent } from "../core/format";
import { BUSINESS_MODELS, getModel } from "../core/knowledge/businessModels";
import { INDUSTRIES, getIndustry } from "../core/knowledge/industries";
import { EXPERIMENTS, HYPOTHESIS_TYPES, RISK_CATEGORIES, SEGMENTS, SKILLS } from "../core/knowledge/library";
import type { FounderProfile, Project } from "../core/types";
import { CRITERIA, VERDICTS } from "../core/validation";

export const SYSTEM_BASE = `Ты — BizForge AI, опытный предприниматель, венчурный аналитик и бизнес-консультант.
Ты помогаешь основателям генерировать, проверять и упаковывать бизнес-идеи.

Принципы:
- Пиши по-русски, ясно и по делу, без воды и общих фраз.
- Будь честным: если идея слабая или цифры нереалистичны — скажи прямо и объясни почему.
- Опирайся на данные проекта, которые тебе передали. Если данных не хватает — назови допущение явно.
- Не выдумывай точную статистику и названия компаний как факты. Оценки помечай как оценки.
- Предлагай конкретные проверяемые шаги: что сделать, за сколько дней, какой результат считать успехом.`;

export function projectContext(p: Project, a: ProjectAnalysis): string {
  const money = (v: number) => fmtMoney(v, p.currency);
  const industry = getIndustry(p.idea.industryId);
  const model = getModel(p.idea.modelId);
  const lines: string[] = [
    `# Проект: ${p.idea.title || p.name}`,
    `Описание: ${p.idea.oneLiner || "—"}`,
    `Проблема: ${p.idea.problem || "—"}`,
    `Решение: ${p.idea.solution || "—"}`,
    `Аудитория: ${p.idea.audience || "—"} (${SEGMENTS[p.idea.segment]})`,
    `Отрасль: ${industry?.name ?? "—"}; бизнес-модель: ${model?.name ?? "—"}; стадия: ${p.idea.stage}`,
    "",
    "## Lean Canvas",
    ...LEAN_BLOCKS.filter((b) => p.lean[b.id]?.trim()).map((b) => `- ${b.title}: ${p.lean[b.id]!.replace(/\n/g, "; ")}`),
    "",
    `## Оценка идеи: ${Math.round(a.validation.score)}/100, вердикт «${VERDICTS[a.validation.verdict].label}», уверенность ${fmtPercent(a.validation.confidence)}`,
    ...a.validation.results
      .filter((r) => r.answer)
      .map((r) => `- ${r.criterion.name}: ${r.answer!.score}/5 (${r.effectiveEvidence})${r.answer!.note ? ` — ${r.answer!.note}` : ""}`),
    ...(a.validation.redFlags.length ? ["Красные флаги: " + a.validation.redFlags.join("; ")] : []),
    "",
    "## Рынок",
    `TAM ${money(a.market.topDown.tam)}, SAM ${money(a.market.topDown.sam)} / ${money(a.market.bottomUp.sam)} (сверху вниз / снизу вверх), SOM ${money(a.market.topDown.som)} / ${money(a.market.bottomUp.som)}`,
    `Конкуренты: ${p.competitors.map((c) => `${c.name} (${c.kind}; ${c.price})`).join("; ") || "не указаны"}`,
    "",
    "## Юнит-экономика",
    `ARPU ${money(a.unit.arpu)}/мес, маржа ${fmtPercent(p.unit.grossMargin)}, отток ${fmtPercent(p.unit.monthlyChurn, 1)}/мес, CAC ${money(a.unit.cac)}, LTV ${money(a.unit.ltv)}, LTV/CAC ${fmtNumber(a.unit.ltvToCac, 1)}, окупаемость ${fmtNumber(a.unit.paybackMonths, 1)} мес.`,
    "",
    "## Финансовая модель",
    `Горизонт ${p.finance.horizonMonths} мес., запуск на ${p.finance.launchMonth}-м месяце. Выручка по годам: ${a.finance.years.map((y) => money(y.revenue)).join(" / ")}. EBITDA по годам: ${a.finance.years.map((y) => money(y.ebitda)).join(" / ")}.`,
    `Безубыточность: ${a.finance.breakEvenMonth ? `${a.finance.breakEvenMonth}-й месяц` : "не достигается"}. Пиковая потребность в деньгах ${money(a.finance.fundingNeed)}. Команда: ${p.finance.team.map((t) => `${t.role}×${t.count}`).join(", ") || "—"}.`,
    "",
    `## Риски: ${p.risks.map((r) => `${r.title} (${r.probability}×${r.impact})`).join("; ") || "—"}`,
    `## Гипотезы: ${p.hypotheses.map((h) => `«${h.statement}» — ${h.status}${h.result ? `: ${h.result}` : ""}`).join("; ") || "—"}`,
  ];
  return lines.join("\n");
}

const str = (description: string) => ({ type: "string", description });
const int = (description: string) => ({ type: "integer", description });
const obj = (properties: Record<string, unknown>) => ({
  type: "object",
  properties,
  required: Object.keys(properties),
  additionalProperties: false,
});

/* ---------- Idea generation ---------- */

export const IDEAS_SCHEMA = obj({
  ideas: {
    type: "array",
    items: obj({
      title: str("Короткое название идеи (до 60 символов)"),
      oneLiner: str("Описание в одном-двух предложениях: что, для кого, как зарабатывает"),
      problem: str("Конкретная проблема клиента"),
      solution: str("Как продукт решает проблему"),
      audience: str("Целевая аудитория"),
      segment: { type: "string", enum: ["b2c", "b2b", "b2g", "b2b2c"] },
      industryId: { type: "string", enum: INDUSTRIES.map((i) => i.id) },
      modelId: { type: "string", enum: BUSINESS_MODELS.map((m) => m.id) },
      whyNow: str("Почему эта идея актуальна именно сейчас"),
      firstStep: str("Первый шаг проверки идеи за 1–2 недели"),
    }),
  },
});

export function ideasPrompt(profile: FounderProfile, brief: string, count: number): string {
  return [
    `Сгенерируй ${count} сильных и непохожих друг на друга бизнес-идей.`,
    "",
    "Профиль основателя:",
    `- Навыки: ${profile.skills.map((s) => SKILLS[s]).join(", ") || "не указаны"}`,
    `- Бюджет на старт: ${fmtMoney(profile.budget)}`,
    `- Время: ${profile.hoursPerWeek} ч/нед.`,
    `- Интересные отрасли: ${profile.interests.map((i) => getIndustry(i)?.name).filter(Boolean).join(", ") || "любые"}`,
    `- Предпочтительные сегменты: ${profile.preferredSegments.map((s) => SEGMENTS[s]).join(", ") || "любые"}`,
    `- Отношение к риску: ${profile.riskTolerance}`,
    "",
    brief.trim() ? `Пожелания основателя: ${brief.trim()}` : "",
    "",
    "Требования: идеи должны решать реальную острую проблему, подходить под бюджет и навыки основателя, иметь понятную монетизацию и быструю проверку. Избегай банальных идей вроде «ещё одна доставка еды». industryId и modelId выбирай из допустимых значений.",
  ].join("\n");
}

/* ---------- Critique ---------- */

export const CRITIQUE_PROMPT = `Выступи «адвокатом дьявола» и проведи жёсткий, но конструктивный разбор проекта.

Структура ответа (Markdown):
## Главный вердикт
Одним абзацем: стоит ли продолжать и при каких условиях.
## 5 причин, почему проект может провалиться
Нумерованный список, для каждой — почему это вероятно и как это проверить.
## Скрытые допущения
Что основатель считает очевидным, но это не доказано.
## Что проверить в первую очередь
3 эксперимента на ближайшие 2–4 недели с критериями успеха.
## Как усилить идею
3–5 конкретных изменений: сегмент, монетизация, позиционирование, каналы.`;

/* ---------- Validation scores ---------- */

export const VALIDATION_SCHEMA = obj({
  scores: {
    type: "array",
    items: obj({
      criterion: { type: "string", enum: CRITERIA.map((c) => c.id) },
      score: int("Оценка от 1 до 5"),
      rationale: str("Обоснование оценки в 1–2 предложениях"),
    }),
  },
});

export const VALIDATION_PROMPT = `Оцени идею по каждому из критериев по шкале 1–5 и кратко обоснуй оценку.
Критерии и смысл оценок:
${CRITERIA.map((c) => `- ${c.id} «${c.name}»: ${c.question} 1 = ${c.anchors[0]}; 3 = ${c.anchors[1]}; 5 = ${c.anchors[2]}`).join("\n")}
Будь строгим и реалистичным: 5 — только при сильных аргументах.`;

/* ---------- Lean canvas ---------- */

export const LEAN_SCHEMA = obj(Object.fromEntries(LEAN_BLOCKS.map((b) => [b.id, str(`${b.title}: ${b.hint}`)])));

export const LEAN_PROMPT = `Заполни Lean Canvas для этого проекта. Каждый блок — 1–4 коротких пункта через перенос строки, конкретно и без воды.
В «Потоках доходов» укажи цены. В «Ключевых метриках» обязательно укажи метрику удержания. «Скрытое преимущество» — только то, что сложно скопировать.`;

/* ---------- Risks ---------- */

export const RISKS_SCHEMA = obj({
  risks: {
    type: "array",
    items: obj({
      title: str("Название риска"),
      category: { type: "string", enum: Object.keys(RISK_CATEGORIES) },
      probability: int("Вероятность от 1 до 5"),
      impact: int("Влияние от 1 до 5"),
      mitigation: str("Конкретные меры снижения риска"),
    }),
  },
});

export const RISKS_PROMPT = `Определи 6–8 самых значимых рисков проекта, которых ещё нет в списке. Для каждого оцени вероятность и влияние (1–5) и предложи конкретные меры снижения.`;

/* ---------- Hypotheses ---------- */

export const HYPOTHESES_SCHEMA = obj({
  hypotheses: {
    type: "array",
    items: obj({
      statement: str("Проверяемая гипотеза в формате «Мы верим, что…»"),
      type: { type: "string", enum: Object.keys(HYPOTHESIS_TYPES) },
      impact: int("Влияние на успех от 1 до 10"),
      confidence: int("Насколько мы уверены, что гипотеза верна, от 1 до 10"),
      ease: int("Простота проверки от 1 до 10"),
      experimentId: { type: "string", enum: EXPERIMENTS.map((e) => e.id) },
      successMetric: str("Измеримый критерий успеха с числом"),
    }),
  },
});

export const HYPOTHESES_PROMPT = `Сформулируй 5 самых рискованных гипотез проекта, от которых зависит его успех, и подбери для каждой эксперимент.
Доступные эксперименты: ${EXPERIMENTS.map((e) => `${e.id} — ${e.name}`).join("; ")}.
Критерий успеха должен быть числовым и проверяемым.`;

/* ---------- Competitors ---------- */

export const COMPETITORS_SCHEMA = obj({
  competitors: {
    type: "array",
    items: obj({
      name: str("Название или тип конкурента"),
      kind: { type: "string", enum: ["direct", "indirect", "substitute"] },
      price: str("Ценовой уровень"),
      strengths: str("Сильные стороны"),
      weaknesses: str("Слабые стороны"),
      x: int("Позиция на карте по оси X от 0 до 10"),
      y: int("Позиция на карте по оси Y от 0 до 10"),
    }),
  },
});

export function competitorsPrompt(xLabel: string, yLabel: string): string {
  return `Составь список из 5–7 конкурентов и альтернатив: прямые конкуренты, косвенные и заменители (включая «ничего не делать» или ручной способ).
Если не уверен в существовании конкретной компании, называй тип решения, а не выдуманный бренд.
Для карты позиционирования используй оси: X — «${xLabel.replace(" →", "")}», Y — «${yLabel.replace(" →", "")}» (0–10).`;
}

/* ---------- Market ---------- */

export const MARKET_SCHEMA = obj({
  geography: str("География рынка"),
  totalCustomers: int("Общее число потенциальных клиентов в географии"),
  annualSpendPerCustomer: int("Средние годовые расходы клиента на решение задачи, в валюте проекта"),
  segmentShare: { type: "number", description: "Доля целевого сегмента от 0 до 1" },
  obtainableShare: { type: "number", description: "Реалистичная доля рынка через 3–5 лет, от 0 до 1" },
  targetCustomers: int("Число клиентов в целевом сегменте"),
  pricePerPurchase: int("Цена одной покупки"),
  purchasesPerYear: { type: "number", description: "Покупок в год на клиента" },
  reachShare: { type: "number", description: "Доля целевых клиентов, которых можно охватить каналами, от 0 до 1" },
  conversionShare: { type: "number", description: "Доля охваченных, кто купит, от 0 до 1" },
  rationale: str("Откуда взяты оценки, допущения и что проверить (Markdown, 3–6 пунктов)"),
});

export const MARKET_PROMPT = `Оцени объём рынка для проекта двумя способами: сверху вниз и снизу вверх. Используй правдоподобные оценки на основе общедоступных знаний о рынке и явно перечисли допущения. Будь консервативен: доля SOM для нового игрока обычно 1–5%.`;

/* ---------- Plan & pitch ---------- */

export function planSectionPrompt(title: string, draft: string): string {
  return `Перепиши раздел бизнес-плана «${title}» так, чтобы он убеждал инвестора: ясная структура, конкретика, цифры из проекта. Сохрани все числа из черновика, ничего не выдумывай. Таблицы можно сохранить. Ответ — только текст раздела в Markdown без заголовка раздела.

Черновик раздела:
${draft}`;
}

export const PITCH_PROMPT = `Подготовь материалы для питча проекта (Markdown):
## Питч за 60 секунд
Текст для устного выступления (120–160 слов): проблема → решение → рынок → бизнес-модель → тяга/доказательства → запрос.
## Структура питч-дека на 10 слайдов
Для каждого слайда: заголовок и 2–3 ключевых тезиса с цифрами проекта.
## Сложные вопросы инвесторов
7 вопросов, которые наверняка зададут, и короткие сильные ответы.`;

export const ADVISOR_PROMPT = `Ты отвечаешь на вопросы основателя об этом проекте. Используй контекст проекта. Отвечай конкретно и с цифрами; если вопрос требует данных, которых нет, — предложи, как их получить.`;
