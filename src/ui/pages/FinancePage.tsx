import { useMemo, useState } from "react";
import { SCENARIOS, applyScenario, computeFinance } from "../../core/finance";
import { fmtMonths, fmtNumber, fmtPercent, slugify } from "../../core/format";
import { newId } from "../../core/random";
import type { CapexItem, CostLine, FinanceAssumptions, FundingEvent, TaxMode, TeamMember } from "../../core/types";
import { BarChart, LineChart } from "../components/charts";
import { EditableTable } from "../components/EditableTable";
import { Card, NumberField, PageHeader, Select, Stat, Tabs, downloadFile } from "../components/ui";
import { useProject } from "../hooks";

type Tab = "assumptions" | "reports" | "scenarios";

const TAX_PRESETS: { id: string; label: string; mode: TaxMode; rate: number }[] = [
  { id: "usn6", label: "УСН «Доходы» 6%", mode: "revenue", rate: 0.06 },
  { id: "usn15", label: "УСН «Доходы − расходы» 15%", mode: "profit", rate: 0.15 },
  { id: "osno", label: "Налог на прибыль 25%", mode: "profit", rate: 0.25 },
  { id: "none", label: "Без налогов", mode: "none", rate: 0 },
  { id: "custom", label: "Своя ставка", mode: "profit", rate: 0.2 },
];

export function FinancePage() {
  const { project: p, analysis: a, update, money } = useProject();
  const [tab, setTab] = useState<Tab>("assumptions");
  const f = p.finance;
  const fin = a.finance;
  const set = <K extends keyof FinanceAssumptions>(key: K, value: FinanceAssumptions[K]) => update((d) => void (d.finance[key] = value));

  const scenarios = useMemo(() => SCENARIOS.map((s) => ({ s, r: computeFinance(applyScenario(f, s)) })), [f]);
  const taxPreset = TAX_PRESETS.find((t) => t.mode === f.taxMode && Math.abs(t.rate - f.taxRate) < 1e-9)?.id ?? "custom";
  const months = fin.rows.map((r) => r.month);
  const lastYear = fin.years[fin.years.length - 1];

  const exportCsv = () => {
    const header = [
      "Месяц",
      "Новых клиентов",
      "Активных клиентов",
      "Выручка",
      "Себестоимость",
      "Валовая прибыль",
      "Маркетинг",
      "ФОТ",
      "Прочие расходы",
      "EBITDA",
      "Амортизация",
      "Налоги",
      "Чистая прибыль",
      "Капвложения",
      "Финансирование",
      "Свободный денежный поток",
      "Остаток денег",
    ];
    const rows = fin.rows.map((r) =>
      [
        r.month,
        r.newCustomers,
        r.activeCustomers,
        r.revenue,
        r.cogs,
        r.grossProfit,
        r.marketing,
        r.payroll,
        r.opex,
        r.ebitda,
        r.depreciation,
        r.tax,
        r.netIncome,
        r.capex,
        r.funding,
        r.freeCashFlow,
        r.cash,
      ]
        .map((v) => (typeof v === "number" ? v.toFixed(2).replace(".", ",") : v))
        .join(";"),
    );
    downloadFile(`financial-model-${slugify(p.name)}.csv`, "﻿" + [header.join(";"), ...rows].join("\n"), "text/csv");
  };

  return (
    <>
      <PageHeader
        title="Финансовая модель"
        subtitle="Помесячная модель: клиенты → выручка → расходы → прибыль → деньги. Показывает, когда бизнес выйдет в плюс и сколько денег нужно до этого момента."
        actions={
          <button className="btn" onClick={exportCsv}>
            ⬇ CSV для Excel
          </button>
        }
      />

      <Card>
        <div className="grid grid-4">
          <Stat
            label="Операционная безубыточность"
            tone={fin.breakEvenMonth ? "good" : "bad"}
            value={fin.breakEvenMonth ? `${fin.breakEvenMonth}-й мес.` : "нет"}
            sub="EBITDA ≥ 0 три месяца подряд"
          />
          <Stat
            label="Пиковая потребность в деньгах"
            value={money(fin.fundingNeed)}
            sub={`мин. остаток ${money(fin.minCash)} (мес. ${fin.minCashMonth})`}
          />
          <Stat
            label="Хватит ли денег"
            tone={fin.fundingGap > 0 ? "bad" : "good"}
            value={fin.fundingGap > 0 ? `дефицит ${money(fin.fundingGap)}` : "хватает"}
            sub={fin.runwayMonths !== null ? `деньги кончатся на ${fin.runwayMonths + 1}-м мес.` : "с учётом раундов"}
          />
          <Stat
            label={`Выручка, год ${lastYear?.year ?? "—"}`}
            value={money(lastYear?.revenue ?? 0)}
            sub={`MRR в конце: ${money(fin.endMrr)}`}
          />
          <Stat
            label="NPV"
            tone={fin.npv > 0 ? "good" : "bad"}
            value={money(fin.npv)}
            sub={`ставка ${fmtPercent(f.discountRateYear)}, с терминальной стоимостью`}
          />
          <Stat label="IRR (годовая)" value={fin.irrAnnual === null ? "—" : fmtPercent(fin.irrAnnual)} />
          <Stat label="Окупаемость вложений" value={fin.paybackMonth ? `${fin.paybackMonth}-й мес.` : "за горизонтом"} />
          <Stat
            label="Клиентов в конце"
            value={fmtNumber(fin.endCustomers)}
            sub={`команда: ${fin.rows[fin.rows.length - 1]?.headcount ?? 0} чел.`}
          />
        </div>
      </Card>

      <div className="mt-16">
        <Tabs
          tabs={[
            { id: "assumptions", label: "Допущения" },
            { id: "reports", label: "Отчёты и графики" },
            { id: "scenarios", label: "Сценарии" },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>

      {tab === "assumptions" && (
        <div className="stack">
          <div className="grid grid-3">
            <Card title="Общие">
              <div className="stack" style={{ gap: 12 }}>
                <Select
                  label="Горизонт планирования"
                  value={String(f.horizonMonths)}
                  onChange={(v) => set("horizonMonths", Number(v))}
                  options={[24, 36, 48, 60].map((n) => ({ value: String(n), label: `${n} месяцев (${n / 12} года)` }))}
                />
                <NumberField
                  label="Месяц запуска продаж"
                  value={f.launchMonth}
                  digits={0}
                  min={1}
                  max={f.horizonMonths}
                  hint="До запуска — только разработка и расходы"
                  onChange={(v) => set("launchMonth", Math.round(v))}
                />
                <NumberField
                  label="Стартовый капитал"
                  kind="money"
                  value={f.startingCash}
                  min={0}
                  hint="Собственные деньги основателей"
                  onChange={(v) => set("startingCash", v)}
                />
              </div>
            </Card>
            <Card title="Выручка">
              <div className="stack" style={{ gap: 12 }}>
                <NumberField label="ARPU — доход с клиента в месяц" kind="money" value={f.arpu} min={0} onChange={(v) => set("arpu", v)} />
                <NumberField
                  label="Рост цен в год"
                  kind="percent"
                  value={f.priceGrowthPerYear}
                  onChange={(v) => set("priceGrowthPerYear", v)}
                />
                <NumberField
                  label="Валовая маржа"
                  kind="percent"
                  value={f.grossMargin}
                  min={0}
                  max={1}
                  onChange={(v) => set("grossMargin", v)}
                />
                <NumberField
                  label="Отток клиентов в месяц"
                  kind="percent"
                  value={f.monthlyChurn}
                  min={0}
                  max={1}
                  hint="100% — разовые продажи без повторов"
                  onChange={(v) => set("monthlyChurn", v)}
                />
              </div>
            </Card>
            <Card title="Привлечение клиентов">
              <div className="stack" style={{ gap: 12 }}>
                <NumberField
                  label="Маркетинг на старте, в месяц"
                  kind="money"
                  value={f.marketingStart}
                  min={0}
                  onChange={(v) => set("marketingStart", v)}
                />
                <div className="grid grid-2" style={{ gap: 10 }}>
                  <NumberField
                    label="Рост бюджета в месяц"
                    kind="percent"
                    value={f.marketingGrowth}
                    min={0}
                    onChange={(v) => set("marketingGrowth", v)}
                  />
                  <NumberField
                    label="Потолок бюджета"
                    kind="money"
                    value={f.marketingMax}
                    min={0}
                    onChange={(v) => set("marketingMax", v)}
                  />
                </div>
                <div className="grid grid-2" style={{ gap: 10 }}>
                  <NumberField label="CAC" kind="money" value={f.cac} min={0} onChange={(v) => set("cac", v)} />
                  <NumberField
                    label="Рост CAC в год"
                    kind="percent"
                    value={f.cacGrowthPerYear}
                    onChange={(v) => set("cacGrowthPerYear", v)}
                  />
                </div>
                <div className="grid grid-2" style={{ gap: 10 }}>
                  <NumberField
                    label="Органика на старте, клиентов/мес"
                    value={f.organicStart}
                    min={0}
                    onChange={(v) => set("organicStart", v)}
                  />
                  <NumberField
                    label="Рост органики в месяц"
                    kind="percent"
                    value={f.organicGrowth}
                    onChange={(v) => set("organicGrowth", v)}
                  />
                </div>
                <div className="grid grid-2" style={{ gap: 10 }}>
                  <NumberField
                    label="Рекомендации"
                    kind="percent"
                    value={f.referralRate}
                    min={0}
                    max={1}
                    hint="Новых клиентов на одного активного в месяц"
                    onChange={(v) => set("referralRate", v)}
                  />
                  <NumberField
                    label="Клиентов на старте"
                    value={f.initialCustomers}
                    digits={0}
                    min={0}
                    hint="Предзаказы, пилоты"
                    onChange={(v) => set("initialCustomers", v)}
                  />
                </div>
              </div>
            </Card>
          </div>

          <Card title="Команда" subtitle="Зарплата — до вычета налогов; взносы работодателя учитываются отдельно.">
            <EditableTable<TeamMember>
              rows={f.team}
              onChange={(rows) => set("team", rows)}
              newRow={() => ({ id: newId("tm"), role: "", salary: 100_000, count: 1, startMonth: Math.max(1, f.launchMonth) })}
              addLabel="Добавить роль"
              columns={[
                { key: "role", label: "Роль", kind: "text", width: 220, placeholder: "Например: разработчик" },
                { key: "salary", label: "Зарплата в месяц", kind: "money", width: 150, min: 0 },
                { key: "count", label: "Кол-во", kind: "number", width: 90, min: 0 },
                { key: "startMonth", label: "С месяца", kind: "number", width: 100, min: 1 },
              ]}
            />
            <div className="mt-16" style={{ maxWidth: 260 }}>
              <NumberField
                label="Страховые взносы работодателя"
                kind="percent"
                value={f.payrollTax}
                min={0}
                max={1}
                onChange={(v) => set("payrollTax", v)}
              />
            </div>
          </Card>

          <div className="grid grid-2">
            <Card title="Постоянные расходы">
              <EditableTable<CostLine>
                rows={f.costs}
                onChange={(rows) => set("costs", rows)}
                newRow={() => ({ id: newId("cost"), name: "", monthly: 10_000, startMonth: 1, growthPerYear: 0.05 })}
                addLabel="Добавить статью"
                columns={[
                  { key: "name", label: "Статья", kind: "text", width: 180 },
                  { key: "monthly", label: "В месяц", kind: "money", width: 120, min: 0 },
                  { key: "startMonth", label: "С мес.", kind: "number", width: 80, min: 1 },
                  { key: "growthPerYear", label: "Рост/год", kind: "percent", width: 100 },
                ]}
              />
            </Card>
            <Card title="Капитальные вложения" subtitle="Оборудование, разработка, ремонт — с амортизацией.">
              <EditableTable<CapexItem>
                rows={f.capex}
                onChange={(rows) => set("capex", rows)}
                newRow={() => ({ id: newId("capex"), name: "", amount: 100_000, month: 1, depreciationMonths: 24 })}
                addLabel="Добавить вложение"
                columns={[
                  { key: "name", label: "Что", kind: "text", width: 170 },
                  { key: "amount", label: "Сумма", kind: "money", width: 120, min: 0 },
                  { key: "month", label: "Месяц", kind: "number", width: 80, min: 1 },
                  { key: "depreciationMonths", label: "Аморт., мес.", kind: "number", width: 100, min: 1 },
                ]}
              />
            </Card>
          </div>

          <div className="grid grid-2">
            <Card title="Привлечение инвестиций">
              <EditableTable<FundingEvent>
                rows={f.funding}
                onChange={(rows) => set("funding", rows)}
                newRow={() => ({ id: newId("fund"), label: "Раунд", amount: 5_000_000, month: Math.max(1, fin.minCashMonth - 2) })}
                addLabel="Добавить раунд / заём"
                empty="Раундов нет — бизнес живёт на стартовом капитале."
                columns={[
                  { key: "label", label: "Источник", kind: "text", width: 170 },
                  { key: "amount", label: "Сумма", kind: "money", width: 130, min: 0 },
                  { key: "month", label: "Месяц", kind: "number", width: 80, min: 1 },
                ]}
              />
            </Card>
            <Card title="Налоги и оценка">
              <div className="stack" style={{ gap: 12 }}>
                <Select
                  label="Налоговый режим"
                  value={taxPreset}
                  onChange={(id) => {
                    const t = TAX_PRESETS.find((x) => x.id === id)!;
                    update((d) => {
                      d.finance.taxMode = t.mode;
                      d.finance.taxRate = t.rate;
                    });
                  }}
                  options={TAX_PRESETS.map((t) => ({ value: t.id, label: t.label }))}
                />
                {taxPreset === "custom" && (
                  <div className="grid grid-2" style={{ gap: 10 }}>
                    <Select
                      label="База"
                      value={f.taxMode}
                      onChange={(m) => set("taxMode", m)}
                      options={[
                        { value: "profit", label: "Прибыль" },
                        { value: "revenue", label: "Выручка" },
                        { value: "none", label: "Нет" },
                      ]}
                    />
                    <NumberField label="Ставка" kind="percent" value={f.taxRate} min={0} max={1} onChange={(v) => set("taxRate", v)} />
                  </div>
                )}
                <div className="grid grid-2" style={{ gap: 10 }}>
                  <NumberField
                    label="Ставка дисконтирования"
                    kind="percent"
                    value={f.discountRateYear}
                    min={0}
                    max={2}
                    hint="Для NPV; для стартапов 25–50%"
                    onChange={(v) => set("discountRateYear", v)}
                  />
                  <NumberField
                    label="Мультипликатор выхода"
                    value={f.exitMultiple}
                    min={0}
                    max={50}
                    suffix="× EBITDA"
                    hint="Терминальная стоимость; 0 — не учитывать"
                    onChange={(v) => set("exitMultiple", v)}
                  />
                </div>
              </div>
            </Card>
          </div>
        </div>
      )}

      {tab === "reports" && (
        <div className="stack">
          <div className="grid grid-2">
            <Card title="Выручка, расходы и EBITDA" subtitle="По месяцам">
              <LineChart
                ariaLabel="Выручка, расходы и EBITDA по месяцам"
                labels={months}
                xTitle={(m) => `Месяц ${m}`}
                format={(v) => money(v)}
                series={[
                  { name: "Выручка", values: fin.rows.map((r) => r.revenue), color: "var(--s1)" },
                  { name: "Расходы", values: fin.rows.map((r) => r.cogs + r.marketing + r.payroll + r.opex), color: "var(--s2)" },
                  { name: "EBITDA", values: fin.rows.map((r) => r.ebitda), color: "var(--s3)", dashed: true },
                ]}
                markers={fin.breakEvenMonth ? [{ index: fin.breakEvenMonth - 1, label: "безубыточность" }] : []}
              />
            </Card>
            <Card title="Остаток денег на счёте" subtitle="С учётом стартового капитала и раундов">
              <LineChart
                ariaLabel="Остаток денег по месяцам"
                labels={months}
                xTitle={(m) => `Месяц ${m}`}
                format={(v) => money(v)}
                series={[{ name: "Остаток денег", values: fin.rows.map((r) => r.cash), color: "var(--s1)", area: true }]}
                markers={f.funding.map((x) => ({ index: Math.min(fin.rows.length - 1, x.month - 1), label: x.label }))}
              />
            </Card>
            <Card title="Клиенты" subtitle="Активные клиенты на конец месяца">
              <LineChart
                ariaLabel="Активные и новые клиенты по месяцам"
                labels={months}
                xTitle={(m) => `Месяц ${m}`}
                format={(v) => fmtNumber(v)}
                series={[
                  { name: "Активные клиенты", values: fin.rows.map((r) => r.activeCustomers), color: "var(--s1)" },
                  { name: "Новые за месяц", values: fin.rows.map((r) => r.newCustomers), color: "var(--s2)" },
                ]}
              />
            </Card>
            <Card title="Итоги по годам">
              <BarChart
                ariaLabel="Выручка, EBITDA и чистая прибыль по годам"
                categories={fin.years.map((y) => `Год ${y.year}`)}
                series={[
                  { name: "Выручка", values: fin.years.map((y) => y.revenue), color: "var(--s1)" },
                  { name: "EBITDA", values: fin.years.map((y) => y.ebitda), color: "var(--s2)" },
                  { name: "Чистая прибыль", values: fin.years.map((y) => y.netIncome), color: "var(--s3)" },
                ]}
                format={(v) => money(v)}
              />
            </Card>
          </div>

          <Card title="Отчёт о прибылях и убытках и движении денег по годам">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Показатель</th>
                    {fin.years.map((y) => (
                      <th key={y.year} className="num">
                        Год {y.year}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["Выручка", "revenue", true],
                      ["Валовая прибыль", "grossProfit", false],
                      ["Маркетинг", "marketing", false],
                      ["ФОТ с налогами", "payroll", false],
                      ["Прочие расходы", "opex", false],
                      ["EBITDA", "ebitda", true],
                      ["Чистая прибыль", "netIncome", true],
                      ["Свободный денежный поток", "freeCashFlow", false],
                      ["Деньги на конец года", "endCash", true],
                    ] as const
                  ).map(([label, key, strong]) => (
                    <tr key={key} className={strong ? "strong" : ""}>
                      <td>{label}</td>
                      {fin.years.map((y) => (
                        <td key={y.year} className={`num ${y[key] < 0 ? "neg" : ""}`}>
                          {money(y[key], false)}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <td>Клиентов на конец года</td>
                    {fin.years.map((y) => (
                      <td key={y.year} className="num">
                        {fmtNumber(y.endCustomers)}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Рентабельность по EBITDA</td>
                    {fin.years.map((y) => (
                      <td key={y.year} className="num">
                        {y.revenue > 0 ? fmtPercent(y.ebitda / y.revenue) : "—"}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Помесячная таблица">
            <details className="disclosure">
              <summary>Показать все {fin.rows.length} месяцев</summary>
              <div className="table-wrap mt-8" style={{ maxHeight: 520 }}>
                <table className="table">
                  <thead>
                    <tr>
                      {[
                        "Мес.",
                        "Клиенты",
                        "Выручка",
                        "Валовая приб.",
                        "Маркетинг",
                        "ФОТ",
                        "Прочие",
                        "EBITDA",
                        "Чистая приб.",
                        "Поток денег",
                        "Остаток",
                      ].map((h) => (
                        <th key={h} className="num">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {fin.rows.map((r) => (
                      <tr key={r.month}>
                        <td className="num">{r.month}</td>
                        <td className="num">{fmtNumber(r.activeCustomers)}</td>
                        {[
                          r.revenue,
                          r.grossProfit,
                          r.marketing,
                          r.payroll,
                          r.opex,
                          r.ebitda,
                          r.netIncome,
                          r.freeCashFlow + r.funding,
                          r.cash,
                        ].map((v, i) => (
                          <td key={i} className={`num ${v < 0 ? "neg" : ""}`}>
                            {money(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </Card>
        </div>
      )}

      {tab === "scenarios" && (
        <div className="stack">
          <Card
            title="Остаток денег по сценариям"
            subtitle="Пессимистичный: ARPU −15%, CAC +30%, отток +30%, органика −40%, запуск на 2 мес. позже. Оптимистичный: ARPU +10%, CAC −20%, отток −20%, органика +40%."
          >
            <LineChart
              ariaLabel="Остаток денег в трёх сценариях"
              labels={months}
              xTitle={(m) => `Месяц ${m}`}
              format={(v) => money(v)}
              series={scenarios.map(({ s, r }, i) => ({
                name: s.label,
                values: r.rows.map((x) => x.cash),
                color: ["var(--s2)", "var(--s1)", "var(--s3)"][i],
                dashed: s.id !== "base",
              }))}
              height={300}
            />
          </Card>
          <Card title="Сравнение сценариев">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Метрика</th>
                    {scenarios.map(({ s }) => (
                      <th key={s.id} className="num">
                        {s.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Выручка за весь период</td>
                    {scenarios.map(({ s, r }) => (
                      <td key={s.id} className="num">
                        {money(r.totalRevenue)}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Выручка последнего года</td>
                    {scenarios.map(({ s, r }) => (
                      <td key={s.id} className="num">
                        {money(r.years[r.years.length - 1]?.revenue ?? 0)}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Безубыточность</td>
                    {scenarios.map(({ s, r }) => (
                      <td key={s.id} className="num">
                        {r.breakEvenMonth ? fmtMonths(r.breakEvenMonth) : "не достигается"}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Потребность в деньгах</td>
                    {scenarios.map(({ s, r }) => (
                      <td key={s.id} className="num">
                        {money(r.fundingNeed)}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Дефицит при текущем финансировании</td>
                    {scenarios.map(({ s, r }) => (
                      <td key={s.id} className={`num ${r.fundingGap > 0 ? "neg" : ""}`}>
                        {r.fundingGap > 0 ? money(r.fundingGap) : "нет"}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>NPV</td>
                    {scenarios.map(({ s, r }) => (
                      <td key={s.id} className={`num ${r.npv < 0 ? "neg" : ""}`}>
                        {money(r.npv)}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td>Клиентов в конце</td>
                    {scenarios.map(({ s, r }) => (
                      <td key={s.id} className="num">
                        {fmtNumber(r.endCustomers)}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="small text-2 mt-8">
              Хотите увидеть не три сценария, а тысячи? Откройте <a href="#/montecarlo">Монте-Карло</a> — там видно вероятность каждого
              исхода.
            </p>
          </Card>
        </div>
      )}
    </>
  );
}
