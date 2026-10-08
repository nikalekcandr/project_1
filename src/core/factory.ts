import { recommendExperiments, hypothesisTemplate } from "./experiments";
import { getModel, type BusinessModelPattern } from "./knowledge/businessModels";
import { getIndustry } from "./knowledge/industries";
import { DEFAULT_MC_PARAMS } from "./monteCarlo";
import { newId } from "./random";
import type {
  FinanceAssumptions,
  Hypothesis,
  HypothesisType,
  Idea,
  MarketSizingInput,
  Project,
  ProjectIdea,
  Risk,
  RiskCategory,
  UnitEconomicsInput,
  ValidationAnswers,
} from "./types";

export function emptyIdea(): ProjectIdea {
  return { title: "", oneLiner: "", problem: "", solution: "", audience: "", segment: "b2c", stage: "idea" };
}

export function defaultMarket(): MarketSizingInput {
  return {
    geography: "Россия",
    topDown: { totalCustomers: 0, annualSpendPerCustomer: 0, segmentShare: 0.2, obtainableShare: 0.03 },
    bottomUp: { targetCustomers: 0, pricePerPurchase: 0, purchasesPerYear: 12, reachShare: 0.3, conversionShare: 0.05 },
  };
}

export function defaultUnit(model?: BusinessModelPattern): UnitEconomicsInput {
  const d = model?.defaults ?? { avgCheck: 1990, purchasesPerMonth: 1, grossMargin: 0.6, monthlyChurn: 0.06, cacMonthsOfRevenue: 3 };
  const arpu = d.avgCheck * d.purchasesPerMonth;
  const cac = Math.round(arpu * d.cacMonthsOfRevenue);
  return {
    avgCheck: d.avgCheck,
    purchasesPerMonth: d.purchasesPerMonth,
    grossMargin: d.grossMargin,
    monthlyChurn: d.monthlyChurn,
    cacMode: "direct",
    cac,
    costPerLead: Math.round(cac * 0.1),
    leadToCustomer: 0.1,
    fixedCostsMonthly: 400_000,
    discountRateYear: 0.25,
  };
}

export function defaultFinance(unit: UnitEconomicsInput): FinanceAssumptions {
  const launchMonth = 3;
  return {
    horizonMonths: 36,
    launchMonth,
    startingCash: 1_500_000,
    funding: [],
    arpu: Math.round(unit.avgCheck * unit.purchasesPerMonth),
    priceGrowthPerYear: 0.07,
    grossMargin: unit.grossMargin,
    monthlyChurn: unit.monthlyChurn,
    cac: Math.round(unit.cacMode === "funnel" && unit.leadToCustomer > 0 ? unit.costPerLead / unit.leadToCustomer : unit.cac),
    cacGrowthPerYear: 0.1,
    marketingStart: 60_000,
    marketingGrowth: 0.1,
    marketingMax: 700_000,
    organicStart: 5,
    organicGrowth: 0.06,
    referralRate: 0.01,
    initialCustomers: 0,
    team: [
      { id: newId("tm"), role: "Основатель (CEO)", salary: 100_000, count: 1, startMonth: 1 },
      { id: newId("tm"), role: "Продукт и разработка", salary: 160_000, count: 1, startMonth: 1 },
      { id: newId("tm"), role: "Продажи и маркетинг", salary: 110_000, count: 1, startMonth: launchMonth + 2 },
    ],
    payrollTax: 0.3,
    costs: [
      { id: newId("cost"), name: "Аренда / коворкинг", monthly: 35_000, startMonth: 1, growthPerYear: 0.08 },
      { id: newId("cost"), name: "ПО, сервисы, хостинг", monthly: 20_000, startMonth: 1, growthPerYear: 0.15 },
      { id: newId("cost"), name: "Бухгалтерия и юрист", monthly: 20_000, startMonth: 1, growthPerYear: 0.05 },
    ],
    capex: [{ id: newId("capex"), name: "Разработка MVP / оборудование", amount: 300_000, month: 1, depreciationMonths: 24 }],
    taxMode: "revenue",
    taxRate: 0.06,
    discountRateYear: 0.25,
    exitMultiple: 4,
  };
}

function riskCategory(text: string): RiskCategory {
  const t = text.toLowerCase();
  if (/конкурент|копир|демпинг/.test(t)) return "competition";
  if (/капитал|деньг|кассов|запас|раунд|субсид/.test(t)) return "finance";
  if (/юрид|регулят|лиценз|закон/.test(t)) return "legal";
  if (/отток|продукт|качеств|функц/.test(t)) return "product";
  if (/людей|команд|найм|исполнител/.test(t)) return "team";
  if (/спрос|цикл|сезон|аудитори|рынок|рекламн/.test(t)) return "market";
  return "operations";
}

function initialHypotheses(idea: ProjectIdea): Hypothesis[] {
  const plan: { type: HypothesisType; impact: number; confidence: number; ease: number; metric: string }[] = [
    { type: "problem", impact: 10, confidence: 4, ease: 8, metric: "≥ 7 из 10 респондентов подтверждают проблему и уже тратят на неё ресурсы" },
    { type: "wtp", impact: 9, confidence: 3, ease: 6, metric: "≥ 10 предоплат / ≥ 3 LOI" },
    { type: "channel", impact: 8, confidence: 3, ease: 6, metric: "CAC в тестовом канале ≤ целевого" },
  ];
  return plan.map((h) => ({
    id: newId("hyp"),
    statement: hypothesisTemplate(h.type, idea),
    type: h.type,
    criterionId: h.type === "problem" ? "problem_pain" : h.type === "wtp" ? "willingness_to_pay" : "go_to_market",
    impact: h.impact,
    confidence: h.confidence,
    ease: h.ease,
    experimentId: recommendExperiments(h.type, 1)[0]?.id,
    successMetric: h.metric,
    status: "untested",
    result: "",
  }));
}

export function createProject(idea: Partial<ProjectIdea> & { title: string }, name?: string): Project {
  const model = getModel(idea.modelId);
  const industry = getIndustry(idea.industryId);
  const fullIdea: ProjectIdea = { ...emptyIdea(), ...idea };
  const unit = defaultUnit(model);
  const finance = defaultFinance(unit);

  const validation: ValidationAnswers = {};
  const note = "Предзаполнено из базы знаний — уточните";
  if (industry) {
    validation.market_growth = { score: industry.growth, evidence: "guess", note };
    validation.competition = { score: 6 - industry.competition, evidence: "guess", note };
    validation.regulatory_risk = { score: 6 - industry.regulation, evidence: "guess", note };
  }
  if (model) {
    validation.scalability = { score: model.scalability, evidence: "guess", note };
    validation.capital_intensity = {
      score: 6 - Math.max(model.capital, industry?.capital ?? model.capital),
      evidence: "guess",
      note,
    };
  }

  const risks: Risk[] = [
    ...(model?.risks ?? []).map((title) => ({
      id: newId("risk"),
      title,
      category: riskCategory(title),
      probability: 3,
      impact: 3,
      mitigation: "",
    })),
    { id: newId("risk"), title: "Спрос ниже ожидаемого", category: "market", probability: 3, impact: 5, mitigation: "Предпродажи и smoke-тесты до разработки" },
    { id: newId("risk"), title: "Кассовый разрыв", category: "finance", probability: 3, impact: 5, mitigation: "Ежемесячный прогноз движения денег, резерв на 3–6 месяцев" },
  ];

  const now = Date.now();
  return {
    id: newId("prj"),
    name: name ?? fullIdea.title,
    createdAt: now,
    updatedAt: now,
    currency: "RUB",
    idea: fullIdea,
    validation,
    lean: {
      problem: fullIdea.problem,
      customerSegments: fullIdea.audience,
      uniqueValueProposition: fullIdea.oneLiner,
      solution: fullIdea.solution,
      ...(model?.lean ?? {}),
    },
    bmc: {
      valuePropositions: fullIdea.oneLiner,
      customerSegments: fullIdea.audience,
      channels: model?.lean.channels,
      revenueStreams: model?.lean.revenueStreams,
      costStructure: model?.lean.costStructure,
      ...(model?.bmc ?? {}),
    },
    market: defaultMarket(),
    competitors: [],
    positioning: { xLabel: "Цена →", yLabel: "Глубина решения →", selfX: 5, selfY: 7 },
    unit,
    finance,
    monteCarlo: { runs: 2000, seed: 42, params: DEFAULT_MC_PARAMS.map((p) => ({ ...p })) },
    risks,
    swot: { strengths: [], weaknesses: [], opportunities: [], threats: [] },
    hypotheses: fullIdea.problem ? initialHypotheses(fullIdea) : [],
    plan: {
      fundingAsk: null,
      useOfFunds: { product: 0.35, marketing: 0.35, team: 0.2, reserve: 0.1 },
      milestones: [
        { id: newId("ms"), title: "Запуск MVP", month: finance.launchMonth, metric: "Первые 10 платящих клиентов" },
        { id: newId("ms"), title: "Подтверждение юнит-экономики", month: finance.launchMonth + 4, metric: "LTV/CAC ≥ 3 на первой когорте" },
        { id: newId("ms"), title: "Масштабирование каналов", month: finance.launchMonth + 9, metric: "2 канала с окупаемым CAC" },
      ],
      overrides: {},
    },
    ai: {},
  };
}

export function projectFromIdea(idea: Idea): Project {
  return createProject({
    title: idea.title,
    oneLiner: idea.oneLiner,
    problem: idea.problem,
    solution: idea.solution,
    audience: idea.audience,
    segment: idea.segment,
    industryId: idea.industryId,
    modelId: idea.modelId,
    stage: "idea",
  });
}

/** A fully filled example project so every module shows something meaningful on first launch. */
export function demoProject(): Project {
  const p = createProject(
    {
      title: "ФитПульс — ИИ-удержание клиентов фитнес-клубов",
      oneLiner:
        "ИИ-ассистент, который предсказывает, кто из клиентов фитнес-клуба скоро перестанет ходить, и автоматически возвращает их персональными предложениями — по подписке от 4 900 ₽/мес.",
      problem:
        "Большинство клиентов фитнес-клубов перестают ходить через 2–3 месяца после покупки абонемента и не продлевают его. Клубы узнают об этом слишком поздно и тратят деньги на привлечение новых клиентов вместо удержания текущих.",
      solution:
        "Сервис подключается к CRM клуба, анализирует посещения и активность, за 2–3 недели до ухода выявляет клиентов в зоне риска и запускает персональные цепочки: сообщение от тренера, бонусную тренировку, заморозку абонемента.",
      audience: "Независимые фитнес-клубы и студии на 300–3000 клиентов",
      segment: "b2b",
      industryId: "fitness",
      modelId: "saas",
      stage: "validation",
    },
    "ФитПульс (демо)",
  );

  p.validation = {
    problem_pain: { score: 4, evidence: "research", note: "Отток — главная головная боль владельцев клубов по интервью" },
    problem_frequency: { score: 5, evidence: "research", note: "Клиенты уходят каждый месяц" },
    willingness_to_pay: { score: 3, evidence: "guess", note: "Клубы платят за CRM, но бюджеты ограничены" },
    market_size: { score: 2, evidence: "research", note: "Около 6 000 независимых клубов и студий в целевом сегменте" },
    market_growth: { score: 3, evidence: "research" },
    competition: { score: 3, evidence: "research", note: "CRM есть, но аналитики оттока почти нет" },
    differentiation: { score: 4, evidence: "guess", note: "Предиктивная модель на данных посещений" },
    unit_economics: { score: 4, evidence: "guess" },
    go_to_market: { score: 3, evidence: "guess", note: "Партнёрство с CRM-системами + отраслевые конференции" },
    founder_fit: { score: 4, evidence: "data", note: "Основатель 6 лет управлял сетью клубов" },
    mvp_feasibility: { score: 4, evidence: "research", note: "MVP на выгрузках из CRM за 6 недель" },
    scalability: { score: 5, evidence: "research" },
    regulatory_risk: { score: 4, evidence: "research", note: "Нужно соблюдать 152-ФЗ о персональных данных" },
    capital_intensity: { score: 4, evidence: "research" },
  };

  p.lean = {
    problem:
      "1. Клиенты бросают клуб через 2–3 месяца\n2. Клуб не видит, кто собирается уйти\n3. Привлечение нового клиента в 5–7 раз дороже удержания",
    existingAlternatives: "Ручной обзвон администраторами, отчёты в CRM, скидки на продление «всем подряд»",
    solution:
      "1. Прогноз риска ухода по каждому клиенту\n2. Автоматические персональные цепочки возврата\n3. Дашборд удержания для владельца",
    keyMetrics: "Удержание клиентов клуба на 3-й месяц, число «спасённых» абонементов, MRR, отток клубов, LTV/CAC",
    uniqueValueProposition: "Возвращаем каждого пятого клиента, который собирался уйти, — без лишней работы администраторов",
    unfairAdvantage: "Отраслевая экспертиза основателя и связи с владельцами клубов; данные о посещениях накапливаются и улучшают модель",
    channels: "Партнёрство с CRM для фитнеса, отраслевые конференции, прямые продажи владельцам, кейсы и вебинары",
    customerSegments: "Независимые фитнес-клубы и студии на 300–3000 клиентов",
    earlyAdopters: "Владельцы клубов, у которых отток уже превышает 10% в месяц и есть CRM с историей посещений",
    costStructure: "Разработка и ML, продажи, сервера, интеграции с CRM",
    revenueStreams: "Подписка 4 900 ₽/мес (до 1000 клиентов), 9 900 ₽/мес (до 3000), бонус за «спасённые» абонементы",
  };
  p.bmc = {
    keyPartners: "CRM-системы для фитнеса, сервисы рассылок и мессенджеров, отраслевые ассоциации",
    keyActivities: "Разработка предиктивной модели, интеграции, онбординг клубов",
    keyResources: "ML-модель и накопленные данные, команда, интеграции",
    valuePropositions: "Рост удержания клиентов клуба и выручки от продлений без дополнительной нагрузки на персонал",
    customerRelationships: "Онбординг под ключ, ежемесячный отчёт об удержании, customer success",
    channels: "Партнёрства с CRM, прямые продажи, отраслевые мероприятия",
    customerSegments: "Независимые фитнес-клубы и студии",
    costStructure: "ФОТ разработки и продаж, инфраструктура, маркетинг",
    revenueStreams: "Ежемесячная подписка по тарифам, success fee за возвращённых клиентов",
  };

  p.market = {
    geography: "Россия",
    topDown: { totalCustomers: 9000, annualSpendPerCustomer: 150_000, segmentShare: 0.55, obtainableShare: 0.06 },
    bottomUp: { targetCustomers: 6000, pricePerPurchase: 5900, purchasesPerYear: 12, reachShare: 0.6, conversionShare: 0.17 },
  };
  p.competitors = [
    { id: newId("cmp"), name: "Отраслевые CRM для фитнеса", kind: "direct", price: "3–15 тыс. ₽/мес", strengths: "Уже стоят в клубах, учёт абонементов", weaknesses: "Нет прогноза оттока, только отчёты", x: 6, y: 4 },
    { id: newId("cmp"), name: "Универсальные CRM", kind: "indirect", price: "2–10 тыс. ₽/мес", strengths: "Гибкие воронки и рассылки", weaknesses: "Не знают специфику фитнеса, нужна настройка", x: 5, y: 3 },
    { id: newId("cmp"), name: "Ручной обзвон администраторами", kind: "substitute", price: "Время персонала", strengths: "Бесплатно, личный контакт", weaknesses: "Бессистемно, звонят слишком поздно", x: 1, y: 2 },
    { id: newId("cmp"), name: "Маркетинговые агентства", kind: "indirect", price: "от 50 тыс. ₽/мес", strengths: "Креатив, рекламные кампании", weaknesses: "Фокус на привлечении, а не удержании; дорого", x: 9, y: 5 },
  ];
  p.positioning = { xLabel: "Цена →", yLabel: "Глубина аналитики удержания →", selfX: 4, selfY: 9 };

  p.unit = {
    avgCheck: 5900,
    purchasesPerMonth: 1,
    grossMargin: 0.82,
    monthlyChurn: 0.035,
    cacMode: "funnel",
    cac: 18_000,
    costPerLead: 2_500,
    leadToCustomer: 0.15,
    fixedCostsMonthly: 520_000,
    discountRateYear: 0.25,
  };
  p.finance = {
    ...defaultFinance(p.unit),
    arpu: 5900,
    cac: 16_700,
    startingCash: 2_500_000,
    funding: [
      { id: newId("fund"), label: "Пре-сид раунд", amount: 8_000_000, month: 4 },
      { id: newId("fund"), label: "Посевной раунд", amount: 10_000_000, month: 12 },
    ],
    marketingStart: 80_000,
    marketingGrowth: 0.1,
    marketingMax: 450_000,
    organicStart: 4,
    organicGrowth: 0.05,
    referralRate: 0.008,
    initialCustomers: 5,
    team: [
      { id: newId("tm"), role: "Основатель (CEO)", salary: 120_000, count: 1, startMonth: 1 },
      { id: newId("tm"), role: "Fullstack-разработчик", salary: 220_000, count: 1, startMonth: 1 },
      { id: newId("tm"), role: "ML-инженер", salary: 250_000, count: 1, startMonth: 4 },
      { id: newId("tm"), role: "Менеджер по продажам", salary: 90_000, count: 2, startMonth: 6 },
      { id: newId("tm"), role: "Customer success", salary: 80_000, count: 1, startMonth: 9 },
    ],
  };

  p.risks = [
    { id: newId("risk"), title: "Клубы не готовы платить за удержание", category: "market", probability: 3, impact: 5, mitigation: "Платные пилоты с оплатой за результат; кейсы с ROI" },
    { id: newId("risk"), title: "Сложные интеграции с разными CRM", category: "tech", probability: 4, impact: 3, mitigation: "Начать с 2 самых популярных CRM, загрузка выгрузок как запасной вариант" },
    { id: newId("risk"), title: "CRM-системы сделают аналогичную функцию", category: "competition", probability: 3, impact: 4, mitigation: "Партнёрство вместо конкуренции; фокус на качестве модели и данных" },
    { id: newId("risk"), title: "Длинный цикл продажи сетям", category: "market", probability: 3, impact: 3, mitigation: "Фокус на независимых клубах, где решение принимает владелец" },
    { id: newId("risk"), title: "Нарушение требований 152-ФЗ", category: "legal", probability: 2, impact: 4, mitigation: "Обезличивание данных, хранение в РФ, договор поручения обработки" },
    { id: newId("risk"), title: "Кассовый разрыв до раунда", category: "finance", probability: 3, impact: 5, mitigation: "Годовая предоплата со скидкой, резерв на 4 месяца" },
  ];
  p.swot = {
    strengths: ["Отраслевая экспертиза основателя", "Масштабируемая SaaS-модель с высокой маржой", "Измеримый ROI для клиента"],
    weaknesses: ["Небольшой рынок в одной стране", "Зависимость от интеграций с CRM", "Нет подтверждённой готовности платить"],
    opportunities: ["Рост рынка boutique-студий", "Выход в смежные ниши: йога, танцы, бассейны", "Тренд на ИИ в малом бизнесе"],
    threats: ["CRM-системы добавят похожую функцию", "Рост стоимости привлечения клиентов", "Экономический спад ударит по клубам"],
  };
  p.hypotheses = [
    {
      id: newId("hyp"),
      statement: "Владельцы независимых клубов считают отток клиентов одной из трёх главных проблем и уже тратят на удержание деньги",
      type: "problem",
      criterionId: "problem_pain",
      impact: 10,
      confidence: 7,
      ease: 9,
      experimentId: "interviews",
      successMetric: "≥ 7 из 10 владельцев называют отток топ-3 проблемой",
      status: "validated",
      result: "8 из 12 владельцев назвали отток главной проблемой; 5 уже платят агентствам за реактивацию",
    },
    {
      id: newId("hyp"),
      statement: "Клубы готовы платить 4 900–9 900 ₽/мес за сервис, если он вернёт хотя бы 10 клиентов в месяц",
      type: "wtp",
      criterionId: "willingness_to_pay",
      impact: 9,
      confidence: 4,
      ease: 6,
      experimentId: "presale",
      successMetric: "≥ 5 клубов вносят предоплату за 3 месяца",
      status: "running",
      result: "",
    },
    {
      id: newId("hyp"),
      statement: "Через партнёрство с CRM можно привлекать клубы со стоимостью ниже 20 000 ₽",
      type: "channel",
      criterionId: "go_to_market",
      impact: 8,
      confidence: 3,
      ease: 5,
      experimentId: "ads_test",
      successMetric: "CAC через партнёра ≤ 20 000 ₽",
      status: "untested",
      result: "",
    },
    {
      id: newId("hyp"),
      statement: "Не менее 30% клиентов «в зоне риска» возвращаются после персональной цепочки",
      type: "solution",
      criterionId: "differentiation",
      impact: 9,
      confidence: 4,
      ease: 4,
      experimentId: "concierge",
      successMetric: "≥ 30% возврата в пилотных клубах",
      status: "untested",
      result: "",
    },
  ];
  p.plan.fundingAsk = 18_000_000;
  return p;
}
