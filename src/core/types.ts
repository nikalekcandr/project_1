import type { CurrencyCode } from "./format";

export type Segment = "b2c" | "b2b" | "b2g" | "b2b2c";

export type GenerationMethod =
  | "trend_industry"
  | "model_transplant"
  | "problem_first"
  | "scamper"
  | "ai";

export interface Idea {
  id: string;
  title: string;
  oneLiner: string;
  problem: string;
  solution: string;
  audience: string;
  segment: Segment;
  industryId?: string;
  modelId?: string;
  trendIds?: string[];
  method: GenerationMethod | "manual";
  quickScore?: number;
  scoreNotes?: string[];
  tags?: string[];
  favorite?: boolean;
  createdAt: number;
}

export interface FounderProfile {
  skills: SkillId[];
  budget: number;
  hoursPerWeek: number;
  interests: string[];
  riskTolerance: "low" | "medium" | "high";
  preferredSegments: Segment[];
}

export type SkillId = "tech" | "product" | "sales" | "marketing" | "design" | "ops" | "finance" | "domain" | "content";

/* ---------- Validation ---------- */

export type CriterionId =
  | "problem_pain"
  | "problem_frequency"
  | "willingness_to_pay"
  | "market_size"
  | "market_growth"
  | "competition"
  | "differentiation"
  | "unit_economics"
  | "go_to_market"
  | "founder_fit"
  | "mvp_feasibility"
  | "scalability"
  | "regulatory_risk"
  | "capital_intensity";

export type EvidenceLevel = "guess" | "research" | "data";

export interface CriterionAnswer {
  score: number; // 1..5
  evidence: EvidenceLevel;
  note?: string;
}

export type ValidationAnswers = Partial<Record<CriterionId, CriterionAnswer>>;

/* ---------- Canvases ---------- */

export type LeanBlockId =
  | "problem"
  | "customerSegments"
  | "uniqueValueProposition"
  | "solution"
  | "channels"
  | "revenueStreams"
  | "costStructure"
  | "keyMetrics"
  | "unfairAdvantage"
  | "existingAlternatives"
  | "earlyAdopters";

export type BmcBlockId =
  | "keyPartners"
  | "keyActivities"
  | "keyResources"
  | "valuePropositions"
  | "customerRelationships"
  | "channels"
  | "customerSegments"
  | "costStructure"
  | "revenueStreams";

export type CanvasData<K extends string> = Partial<Record<K, string>>;

/* ---------- Market ---------- */

export interface MarketSizingInput {
  geography: string;
  topDown: {
    totalCustomers: number; // all potential buyers in the geography
    annualSpendPerCustomer: number;
    segmentShare: number; // 0..1 — share that fits the target segment (SAM)
    obtainableShare: number; // 0..1 — share realistically captured in 3–5 years (SOM)
  };
  bottomUp: {
    targetCustomers: number; // concrete reachable customers in target segment
    pricePerPurchase: number;
    purchasesPerYear: number;
    reachShare: number; // 0..1 — share your channels can reach
    conversionShare: number; // 0..1 — share of reached that buys
  };
}

export interface Competitor {
  id: string;
  name: string;
  kind: "direct" | "indirect" | "substitute";
  price: string;
  strengths: string;
  weaknesses: string;
  x: number; // positioning map 0..10
  y: number;
}

export interface PositioningAxes {
  xLabel: string;
  yLabel: string;
  selfX: number;
  selfY: number;
}

/* ---------- Unit economics ---------- */

export interface UnitEconomicsInput {
  avgCheck: number;
  purchasesPerMonth: number;
  grossMargin: number; // 0..1
  monthlyChurn: number; // 0..1
  cacMode: "direct" | "funnel";
  cac: number;
  costPerLead: number;
  leadToCustomer: number; // 0..1
  fixedCostsMonthly: number;
  discountRateYear: number; // 0..1
}

/* ---------- Financial model ---------- */

export interface TeamMember {
  id: string;
  role: string;
  salary: number; // monthly gross salary
  count: number;
  startMonth: number;
}

export interface CostLine {
  id: string;
  name: string;
  monthly: number;
  startMonth: number;
  growthPerYear: number; // 0..1
}

export interface CapexItem {
  id: string;
  name: string;
  amount: number;
  month: number;
  depreciationMonths: number;
}

export interface FundingEvent {
  id: string;
  label: string;
  amount: number;
  month: number;
}

export type TaxMode = "revenue" | "profit" | "none";

export interface FinanceAssumptions {
  horizonMonths: number;
  launchMonth: number;
  startingCash: number;
  funding: FundingEvent[];
  arpu: number; // monthly revenue per active customer
  priceGrowthPerYear: number;
  grossMargin: number;
  monthlyChurn: number;
  cac: number;
  cacGrowthPerYear: number;
  marketingStart: number;
  marketingGrowth: number; // monthly growth of the budget, 0..1
  marketingMax: number;
  organicStart: number; // organic new customers per month at launch
  organicGrowth: number; // monthly growth of organic inflow, 0..1
  referralRate: number; // new customers per active customer per month (virality), 0..1
  initialCustomers: number;
  team: TeamMember[];
  payrollTax: number; // employer contributions, 0..1
  costs: CostLine[];
  capex: CapexItem[];
  taxMode: TaxMode;
  taxRate: number;
  discountRateYear: number;
  /** Terminal value = trailing-12-month EBITDA × multiple (for NPV/IRR). 0 disables it. */
  exitMultiple: number;
}

export interface MonteCarloParam {
  key: MonteCarloKey;
  enabled: boolean;
  min: number; // multipliers of the base value (1 = base)
  mode: number;
  max: number;
}

export type MonteCarloKey =
  | "arpu"
  | "cac"
  | "monthlyChurn"
  | "grossMargin"
  | "organicStart"
  | "marketingStart"
  | "fixedCosts"
  | "launchDelay";

export interface MonteCarloConfig {
  runs: number;
  seed: number;
  params: MonteCarloParam[];
}

/* ---------- Risks & SWOT ---------- */

export type RiskCategory = "market" | "product" | "team" | "finance" | "legal" | "operations" | "tech" | "competition";

export interface Risk {
  id: string;
  title: string;
  category: RiskCategory;
  probability: number; // 1..5
  impact: number; // 1..5
  mitigation: string;
}

export interface Swot {
  strengths: string[];
  weaknesses: string[];
  opportunities: string[];
  threats: string[];
}

/* ---------- Hypotheses & experiments ---------- */

export type HypothesisType = "problem" | "segment" | "solution" | "wtp" | "channel" | "retention" | "operations";
export type HypothesisStatus = "untested" | "running" | "validated" | "invalidated";

export interface Hypothesis {
  id: string;
  statement: string;
  type: HypothesisType;
  criterionId?: CriterionId;
  impact: number; // 1..10
  confidence: number; // 1..10 — how sure we are it's TRUE (low = risky)
  ease: number; // 1..10
  experimentId?: string;
  successMetric: string;
  status: HypothesisStatus;
  result: string;
}

/* ---------- Plan ---------- */

export interface Milestone {
  id: string;
  title: string;
  month: number;
  metric: string;
}

export interface PlanSettings {
  fundingAsk: number | null; // null → derived from the model
  useOfFunds: { product: number; marketing: number; team: number; reserve: number };
  milestones: Milestone[];
  overrides: Partial<Record<PlanSectionId, string>>;
}

export type PlanSectionId =
  | "summary"
  | "problemSolution"
  | "market"
  | "competition"
  | "model"
  | "marketing"
  | "operations"
  | "finance"
  | "risks"
  | "roadmap"
  | "investment";

/* ---------- Project ---------- */

export interface ProjectIdea {
  title: string;
  oneLiner: string;
  problem: string;
  solution: string;
  audience: string;
  segment: Segment;
  industryId?: string;
  modelId?: string;
  stage: "idea" | "validation" | "mvp" | "launched";
}

export interface Project {
  id: string;
  name: string;
  createdAt: number;
  updatedAt: number;
  currency: CurrencyCode;
  idea: ProjectIdea;
  validation: ValidationAnswers;
  lean: CanvasData<LeanBlockId>;
  bmc: CanvasData<BmcBlockId>;
  market: MarketSizingInput;
  competitors: Competitor[];
  positioning: PositioningAxes;
  unit: UnitEconomicsInput;
  finance: FinanceAssumptions;
  monteCarlo: MonteCarloConfig;
  risks: Risk[];
  swot: Swot;
  hypotheses: Hypothesis[];
  plan: PlanSettings;
  ai: Partial<Record<string, string>>;
}
