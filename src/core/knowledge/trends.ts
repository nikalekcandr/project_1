import type { SkillId } from "../types";

export interface Trend {
  id: string;
  name: string;
  emoji: string;
  description: string;
  momentum: number; // 1..5
  /** Prefix for generated titles, e.g. "ИИ-ассистент". */
  titlePrefix: string;
  /** Solution templates; {job} is an infinitive phrase ("удерживать клиентов"). */
  solutionTemplates: string[];
  skills: SkillId[];
  /** Industries where the trend is especially relevant (soft boost). */
  boosts: string[];
  /** Business models that naturally fit the trend. */
  models: string[];
}

export const TRENDS: Trend[] = [
  {
    id: "ai_agents",
    name: "ИИ-агенты и генеративный ИИ",
    emoji: "🤖",
    description: "Большие языковые модели берут на себя рутину: тексты, анализ, коммуникацию и целые рабочие процессы.",
    momentum: 5,
    titlePrefix: "ИИ-ассистент",
    solutionTemplates: [
      "ИИ-ассистент, который помогает {job}",
      "ИИ-агент, который берёт на себя рутину и помогает {job}",
      "сервис на базе генеративного ИИ, который за несколько кликов помогает {job}",
    ],
    skills: ["tech", "product"],
    boosts: ["education", "legal", "marketing", "smb", "health", "hr"],
    models: ["saas", "freemium", "pay_per_use", "productized"],
  },
  {
    id: "subscription",
    name: "Подписочная экономика",
    emoji: "🔁",
    description: "Потребители и бизнес переходят от разовых покупок к подпискам на товары и сервисы.",
    momentum: 4,
    titlePrefix: "Подписка",
    solutionTemplates: [
      "сервис по подписке, который помогает {job}",
      "ежемесячная подписка «всё включено», которая помогает {job}",
    ],
    skills: ["marketing", "ops"],
    boosts: ["food", "pets", "beauty", "fitness", "kids"],
    models: ["saas", "razor_blades", "productized", "community"],
  },
  {
    id: "marketplaces",
    name: "Рост маркетплейсов",
    emoji: "📦",
    description: "Доля продаж через маркетплейсы быстро растёт, вокруг них формируется экосистема сервисов для селлеров.",
    momentum: 4,
    titlePrefix: "Сервис для селлеров",
    solutionTemplates: [
      "сервис-надстройка над маркетплейсами, который помогает {job}",
      "платформа с выходом на маркетплейсы, которая помогает {job}",
    ],
    skills: ["ops", "marketing"],
    boosts: ["retail", "manufacturing", "agro", "logistics"],
    models: ["saas", "productized", "lead_gen", "service"],
  },
  {
    id: "creator_economy",
    name: "Экономика креаторов и соло-предпринимателей",
    emoji: "🎙️",
    description: "Миллионы людей работают на себя: фрилансеры, эксперты, блогеры. Им нужны простые инструменты бизнеса.",
    momentum: 4,
    titlePrefix: "Инструмент для соло-предпринимателей",
    solutionTemplates: [
      "простой инструмент для фрилансеров и экспертов, который помогает {job}",
      "платформа для независимых специалистов, которая помогает {job}",
    ],
    skills: ["product", "marketing", "content"],
    boosts: ["media", "beauty", "fitness", "education", "finance"],
    models: ["saas", "freemium", "community", "marketplace"],
  },
  {
    id: "remote",
    name: "Удалённая и гибридная работа",
    emoji: "🏡",
    description: "Распределённые команды требуют новых инструментов коммуникации, контроля и культуры.",
    momentum: 3,
    titlePrefix: "Онлайн-сервис",
    solutionTemplates: [
      "онлайн-сервис для распределённых команд, который помогает {job}",
      "удалённый сервис без офлайн-визитов, который помогает {job}",
    ],
    skills: ["tech", "product"],
    boosts: ["hr", "legal", "mental", "smb"],
    models: ["saas", "marketplace", "productized"],
  },
  {
    id: "aging",
    name: "Стареющее население (silver economy)",
    emoji: "🧓",
    description: "Доля людей старше 60 растёт: растёт спрос на заботу, здоровье, досуг и безопасность пожилых.",
    momentum: 4,
    titlePrefix: "Сервис silver economy",
    solutionTemplates: [
      "сервис для пожилых и их семей, который помогает {job}",
      "простое решение с заботой о старшем поколении, которое помогает {job}",
    ],
    skills: ["ops", "domain"],
    boosts: ["silver", "health", "finance", "travel"],
    models: ["service", "marketplace", "productized", "saas"],
  },
  {
    id: "preventive_health",
    name: "ЗОЖ и превентивная медицина",
    emoji: "🥗",
    description: "Люди инвестируют в здоровье заранее: трекинг, чекапы, питание, сон и спорт.",
    momentum: 4,
    titlePrefix: "Health-сервис",
    solutionTemplates: [
      "персональный health-сервис, который помогает {job}",
      "сервис на основе данных носимых устройств, который помогает {job}",
    ],
    skills: ["domain", "content", "tech"],
    boosts: ["health", "fitness", "food", "mental", "silver"],
    models: ["freemium", "saas", "d2c", "community"],
  },
  {
    id: "sustainability",
    name: "Устойчивое развитие и экономика замкнутого цикла",
    emoji: "🌱",
    description: "Ресейл, ремонт, переработка и аренда вместо покупки становятся нормой.",
    momentum: 3,
    titlePrefix: "Эко-сервис",
    solutionTemplates: [
      "сервис экономики замкнутого цикла, который помогает {job}",
      "решение в логике экономики замкнутого цикла, которое помогает {job}",
    ],
    skills: ["ops", "marketing"],
    boosts: ["eco", "retail", "food", "construction", "manufacturing"],
    models: ["marketplace", "rental", "d2c", "service"],
  },
  {
    id: "localization",
    name: "Импортозамещение и локализация",
    emoji: "🏗️",
    description: "Уход зарубежных игроков открывает ниши для локальных продуктов, ПО и производств.",
    momentum: 4,
    titlePrefix: "Локальная альтернатива",
    solutionTemplates: [
      "локальная альтернатива ушедшим зарубежным сервисам, которая помогает {job}",
      "отечественное решение без зависимости от иностранных поставщиков, которое помогает {job}",
    ],
    skills: ["tech", "sales"],
    boosts: ["manufacturing", "smb", "marketing", "hr", "retail"],
    models: ["saas", "d2c", "b2b2c", "productized"],
  },
  {
    id: "nocode",
    name: "Автоматизация и no-code",
    emoji: "⚙️",
    description: "Малый бизнес массово автоматизирует процессы без программистов.",
    momentum: 4,
    titlePrefix: "Автоматизация",
    solutionTemplates: [
      "готовая автоматизация «из коробки», которая помогает {job}",
      "no-code-конструктор, который помогает {job} без программистов",
    ],
    skills: ["tech", "product", "ops"],
    boosts: ["smb", "retail", "beauty", "food", "logistics"],
    models: ["saas", "freemium", "productized"],
  },
  {
    id: "microlearning",
    name: "Микрообучение",
    emoji: "📱",
    description: "Обучение короткими порциями в смартфоне вытесняет длинные курсы.",
    momentum: 3,
    titlePrefix: "Микрокурс",
    solutionTemplates: [
      "приложение микрообучения по 10 минут в день, которое помогает {job}",
      "интерактивный тренажёр, который помогает {job}",
    ],
    skills: ["content", "product"],
    boosts: ["education", "hr", "silver", "finance"],
    models: ["freemium", "courses", "saas", "b2b2c"],
  },
  {
    id: "personalization",
    name: "Гиперперсонализация",
    emoji: "🎯",
    description: "Клиенты ждут продуктов и рекомендаций, подобранных лично под них.",
    momentum: 4,
    titlePrefix: "Персональный сервис",
    solutionTemplates: [
      "персонализированный сервис, который на основе данных клиента помогает {job}",
      "сервис персонального подбора, который помогает {job}",
    ],
    skills: ["tech", "marketing"],
    boosts: ["beauty", "food", "fitness", "retail", "travel"],
    models: ["d2c", "saas", "freemium", "razor_blades"],
  },
  {
    id: "hyperlocal",
    name: "Гиперлокальные сообщества",
    emoji: "📍",
    description: "Сервисы уровня района и дома: соседи, локальные мастера, магазины у дома.",
    momentum: 3,
    titlePrefix: "Сервис для соседей",
    solutionTemplates: [
      "районный сервис с опорой на соседей и локальный бизнес, который помогает {job}",
      "гиперлокальная платформа, которая помогает {job}",
    ],
    skills: ["marketing", "ops"],
    boosts: ["construction", "kids", "pets", "retail", "realestate"],
    models: ["marketplace", "community", "lead_gen"],
  },
  {
    id: "mental_wellbeing",
    name: "Ментальное здоровье",
    emoji: "🫶",
    description: "Забота о психике перестала быть табу, спрос на поддержку растёт и в B2C, и в B2B.",
    momentum: 4,
    titlePrefix: "Wellbeing-сервис",
    solutionTemplates: [
      "сервис заботы о ментальном здоровье, который помогает {job}",
      "wellbeing-программа, которая помогает {job}",
    ],
    skills: ["content", "domain"],
    boosts: ["mental", "hr", "health", "kids"],
    models: ["freemium", "saas", "marketplace", "b2b2c"],
  },
  {
    id: "experience",
    name: "Экономика впечатлений",
    emoji: "🎟️",
    description: "Люди тратят на впечатления больше, чем на вещи: события, путешествия, хобби.",
    momentum: 3,
    titlePrefix: "Сервис впечатлений",
    solutionTemplates: [
      "сервис впечатлений, который помогает {job}",
      "платформа событий и хобби, которая помогает {job}",
    ],
    skills: ["marketing", "content", "ops"],
    boosts: ["travel", "media", "food", "silver"],
    models: ["marketplace", "community", "service"],
  },
  {
    id: "data_security",
    name: "Кибербезопасность и защита данных",
    emoji: "🛡️",
    description: "Утечки и мошенничество растут — бизнес и люди готовы платить за защиту.",
    momentum: 4,
    titlePrefix: "Защитный сервис",
    solutionTemplates: [
      "сервис защиты от мошенничества и утечек, который помогает {job}",
      "решение с защитой данных по умолчанию, которое помогает {job}",
    ],
    skills: ["tech", "domain"],
    boosts: ["finance", "silver", "smb", "legal"],
    models: ["saas", "b2b2c", "freemium", "pay_per_use"],
  },
];

export function getTrend(id: string): Trend | undefined {
  return TRENDS.find((t) => t.id === id);
}
