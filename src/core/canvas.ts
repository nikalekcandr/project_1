import type { BmcBlockId, CanvasData, LeanBlockId } from "./types";

export interface CanvasBlock<K extends string> {
  id: K;
  title: string;
  hint: string;
  placeholder: string;
  /** CSS grid area name used by the canvas layout. */
  area: string;
  weight: number;
}

export const LEAN_BLOCKS: CanvasBlock<LeanBlockId>[] = [
  { id: "problem", area: "problem", weight: 3, title: "Проблема", hint: "1–3 главные проблемы клиента", placeholder: "Какие 3 главные проблемы вы решаете?" },
  { id: "existingAlternatives", area: "alternatives", weight: 1, title: "Существующие альтернативы", hint: "Как клиенты решают проблему сейчас", placeholder: "Excel, фрилансеры, конкуренты, «ничего не делать»…" },
  { id: "solution", area: "solution", weight: 2, title: "Решение", hint: "Ключевые функции под каждую проблему", placeholder: "Топ-3 функции, которые решают проблемы" },
  { id: "keyMetrics", area: "metrics", weight: 1, title: "Ключевые метрики", hint: "Что измеряем, чтобы понять, что бизнес работает", placeholder: "Активация, удержание, выручка, LTV/CAC…" },
  { id: "uniqueValueProposition", area: "uvp", weight: 3, title: "Уникальное ценностное предложение", hint: "Одно ясное сообщение, почему вы другие и почему стоит купить", placeholder: "Результат для клиента + чем вы отличаетесь" },
  { id: "unfairAdvantage", area: "advantage", weight: 1, title: "Скрытое преимущество", hint: "То, что нельзя легко купить или скопировать", placeholder: "Экспертиза, данные, сообщество, эксклюзивные партнёры…" },
  { id: "channels", area: "channels", weight: 2, title: "Каналы", hint: "Путь к клиентам", placeholder: "SEO, реклама, партнёры, прямые продажи…" },
  { id: "customerSegments", area: "segments", weight: 3, title: "Сегменты клиентов", hint: "Целевые клиенты и пользователи", placeholder: "Кто ваши клиенты? Чем сегменты отличаются?" },
  { id: "earlyAdopters", area: "early", weight: 1, title: "Ранние последователи", hint: "Характеристики идеального первого клиента", placeholder: "У кого проблема острее всего прямо сейчас?" },
  { id: "costStructure", area: "costs", weight: 2, title: "Структура расходов", hint: "Привлечение, разработка, команда, хостинг…", placeholder: "Основные статьи расходов" },
  { id: "revenueStreams", area: "revenue", weight: 2, title: "Потоки доходов", hint: "Модель дохода, LTV, выручка, маржа", placeholder: "За что и сколько платит клиент" },
];

export const BMC_BLOCKS: CanvasBlock<BmcBlockId>[] = [
  { id: "keyPartners", area: "partners", weight: 1, title: "Ключевые партнёры", hint: "Поставщики и партнёры, без которых модель не работает", placeholder: "Кто ваши ключевые партнёры и поставщики?" },
  { id: "keyActivities", area: "activities", weight: 2, title: "Ключевые виды деятельности", hint: "Самое важное, что делает компания", placeholder: "Производство, платформа, решение проблем…" },
  { id: "keyResources", area: "resources", weight: 1, title: "Ключевые ресурсы", hint: "Активы: люди, технологии, бренд, финансы", placeholder: "Без каких ресурсов не создать ценность?" },
  { id: "valuePropositions", area: "value", weight: 3, title: "Ценностные предложения", hint: "Какую проблему решаем и какую ценность даём", placeholder: "Какую ценность получает клиент?" },
  { id: "customerRelationships", area: "relationships", weight: 1, title: "Отношения с клиентами", hint: "Как привлекаем, удерживаем, растим клиентов", placeholder: "Персональная помощь, самообслуживание, сообщество…" },
  { id: "channels", area: "channels", weight: 2, title: "Каналы", hint: "Как доносим ценность и доставляем продукт", placeholder: "Через какие каналы клиенты хотят взаимодействовать?" },
  { id: "customerSegments", area: "segments", weight: 3, title: "Потребительские сегменты", hint: "Для кого создаём ценность", placeholder: "Кто наши самые важные клиенты?" },
  { id: "costStructure", area: "costs", weight: 2, title: "Структура издержек", hint: "Самые значимые затраты модели", placeholder: "Какие ресурсы и действия самые дорогие?" },
  { id: "revenueStreams", area: "revenue", weight: 2, title: "Потоки поступления доходов", hint: "За что и как платят клиенты", placeholder: "За что клиенты готовы платить и как?" },
];

export interface CanvasReport {
  completeness: number; // 0..1 weighted
  filled: number;
  total: number;
  issues: string[];
}

const words = (text: string | undefined) => (text ?? "").trim().split(/\s+/).filter(Boolean).length;

function blockQuality(text: string | undefined): number {
  const n = words(text);
  if (n === 0) return 0;
  if (n < 4) return 0.5;
  return 1;
}

export function analyzeLean(data: CanvasData<LeanBlockId>): CanvasReport {
  const issues: string[] = [];
  const totalWeight = LEAN_BLOCKS.reduce((s, b) => s + b.weight, 0);
  const completeness = LEAN_BLOCKS.reduce((s, b) => s + b.weight * blockQuality(data[b.id]), 0) / totalWeight;
  const filled = LEAN_BLOCKS.filter((b) => words(data[b.id]) > 0).length;

  for (const b of LEAN_BLOCKS) {
    const n = words(data[b.id]);
    if (n > 0 && n < 4) issues.push(`Блок «${b.title}» заполнен слишком кратко — добавьте конкретики.`);
  }
  if (words(data.problem) && !words(data.existingAlternatives)) {
    issues.push("Укажите существующие альтернативы: как клиенты решают проблему сейчас? Это ваши настоящие конкуренты.");
  }
  if (words(data.customerSegments) && !words(data.earlyAdopters)) {
    issues.push("Опишите ранних последователей — первых клиентов, у которых проблема острее всего.");
  }
  if (words(data.uniqueValueProposition) > 30) {
    issues.push("УТП длиннее 30 слов. Хорошее ценностное предложение помещается в одно предложение.");
  }
  if (words(data.revenueStreams) && !/\d/.test(data.revenueStreams ?? "")) {
    issues.push("В потоках доходов нет цифр. Укажите цену или средний чек.");
  }
  if (words(data.keyMetrics) && !/(удерж|отток|churn|retention|LTV|повтор)/i.test(data.keyMetrics ?? "")) {
    issues.push("Среди ключевых метрик нет удержания (retention/отток) — это главный индикатор ценности продукта.");
  }
  if (words(data.unfairAdvantage) && /(качеств|цена|дешев|команд[аы]? профессионал|клиентоориентир)/i.test(data.unfairAdvantage ?? "")) {
    issues.push("«Качество», «низкая цена» и «клиентоориентированность» — не скрытое преимущество: их легко скопировать.");
  }
  return { completeness, filled, total: LEAN_BLOCKS.length, issues };
}

export function analyzeBmc(data: CanvasData<BmcBlockId>): CanvasReport {
  const issues: string[] = [];
  const totalWeight = BMC_BLOCKS.reduce((s, b) => s + b.weight, 0);
  const completeness = BMC_BLOCKS.reduce((s, b) => s + b.weight * blockQuality(data[b.id]), 0) / totalWeight;
  const filled = BMC_BLOCKS.filter((b) => words(data[b.id]) > 0).length;
  if (words(data.valuePropositions) && !words(data.customerSegments)) {
    issues.push("Ценностное предложение есть, а сегментов нет: для кого эта ценность?");
  }
  if (words(data.customerSegments) && !words(data.channels)) {
    issues.push("Сегменты описаны, но не указано, через какие каналы вы до них доберётесь.");
  }
  if (words(data.revenueStreams) && !words(data.costStructure)) {
    issues.push("Опишите структуру издержек — без неё нельзя проверить маржинальность модели.");
  }
  if (words(data.keyActivities) && !words(data.keyResources)) {
    issues.push("Ключевые виды деятельности требуют ресурсов — заполните блок «Ключевые ресурсы».");
  }
  return { completeness, filled, total: BMC_BLOCKS.length, issues };
}

/** Lean → BMC mapping to bootstrap one canvas from the other. */
export function leanToBmc(lean: CanvasData<LeanBlockId>): CanvasData<BmcBlockId> {
  return {
    valuePropositions: [lean.uniqueValueProposition, lean.solution].filter(Boolean).join("\n"),
    customerSegments: [lean.customerSegments, lean.earlyAdopters && `Ранние последователи: ${lean.earlyAdopters}`]
      .filter(Boolean)
      .join("\n"),
    channels: lean.channels,
    revenueStreams: lean.revenueStreams,
    costStructure: lean.costStructure,
    keyResources: lean.unfairAdvantage,
  };
}
