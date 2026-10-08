import { useMemo } from "react";
import { fmtMonths, fmtNumber, fmtPercent } from "../../core/format";
import { sensitivity } from "../../core/unitEconomics";
import { LineChart, TornadoChart } from "../components/charts";
import { Card, NumberField, PageHeader, Stat, Tabs, toast, toneOf } from "../components/ui";
import { useProject } from "../hooks";

export function UnitPage() {
  const { project: p, analysis: a, update, money } = useProject();
  const u = p.unit;
  const r = a.unit;
  const tornado = useMemo(() => sensitivity(u), [u]);

  const curve = useMemo(() => {
    const horizon = Math.min(60, Math.max(12, Math.ceil(Math.min(r.lifetimeMonths, 60) * 1.5)));
    const values: number[] = [];
    let cum = -r.cac;
    let survival = 1;
    for (let t = 0; t <= horizon; t++) {
      values.push(cum);
      cum += r.contribution * survival;
      survival *= 1 - Math.min(1, u.monthlyChurn);
    }
    return values;
  }, [r, u.monthlyChurn]);
  const paybackIndex = curve.findIndex((v) => v >= 0);

  const syncToFinance = () => {
    update((d) => {
      d.finance.arpu = Math.round(r.arpu);
      d.finance.grossMargin = u.grossMargin;
      d.finance.monthlyChurn = u.monthlyChurn;
      d.finance.cac = Math.round(r.cac);
    });
    toast("ARPU, маржа, отток и CAC перенесены в финансовую модель");
  };

  return (
    <>
      <PageHeader
        title="Юнит-экономика"
        subtitle="Сколько приносит один клиент и сколько стоит его привлечь. Если экономика одного клиента не сходится, масштабирование только увеличит убытки."
        actions={
          <button className="btn primary" onClick={syncToFinance}>
            → Перенести в финмодель
          </button>
        }
      />

      <div className="grid grid-side">
        <div className="stack">
          <Card>
            <div className="grid grid-4">
              <Stat
                label="LTV / CAC"
                tone={toneOf(r.health.ltvToCac)}
                value={Number.isFinite(r.ltvToCac) ? fmtNumber(r.ltvToCac, 1) : "∞"}
                sub="цель ≥ 3"
              />
              <Stat
                label="Окупаемость клиента"
                tone={toneOf(r.health.payback)}
                value={fmtMonths(r.paybackMonths, true)}
                sub="цель ≤ 12 мес."
              />
              <Stat label="LTV" value={money(r.ltv)} sub={`дисконт.: ${money(r.ltvDiscounted)}`} />
              <Stat label="CAC" value={money(r.cac)} sub={u.cacMode === "funnel" ? "из воронки" : "прямой ввод"} />
              <Stat label="ARPU в месяц" value={money(r.arpu)} />
              <Stat label="Валовая прибыль с клиента" value={money(r.contribution)} sub="в месяц" />
              <Stat label="Срок жизни клиента" tone={toneOf(r.health.churn)} value={fmtMonths(r.lifetimeMonths)} />
              <Stat
                label="Прибыль с клиента"
                tone={r.profitPerCustomer > 0 ? "good" : "bad"}
                value={money(r.profitPerCustomer)}
                sub="LTV − CAC"
              />
            </div>
            <div className={`callout mt-16 ${r.ltvToCac >= 3 && r.paybackMonths <= 18 ? "good" : r.ltvToCac >= 1.5 ? "warn" : "bad"}`}>
              {r.verdict}
            </div>
          </Card>

          <Card
            title="Экономика одного клиента во времени"
            subtitle="Накопленная валовая прибыль с клиента за вычетом CAC с учётом оттока. Пересечение нуля — момент окупаемости."
          >
            <LineChart
              ariaLabel="Накопленная прибыль с одного клиента"
              labels={curve.map((_, i) => i)}
              xTitle={(m) => `Месяц ${m}`}
              format={(v) => money(v, false)}
              series={[{ name: "Накопленная прибыль с клиента", values: curve, color: "var(--s1)", area: true }]}
              markers={paybackIndex > 0 ? [{ index: paybackIndex, label: `окупаемость: ${paybackIndex} мес.` }] : []}
              height={240}
            />
          </Card>

          <Card
            title="Что сильнее всего влияет на прибыль с клиента"
            subtitle="Каждый параметр меняем на ±20% и смотрим, как меняется LTV − CAC. Верхний рычаг — главный."
          >
            <TornadoChart
              ariaLabel="Анализ чувствительности юнит-экономики"
              rows={tornado}
              base={r.profitPerCustomer}
              format={(v) => money(v)}
              lowLabel="Ухудшение на 20%"
              highLabel="Улучшение на 20%"
            />
          </Card>
        </div>

        <div className="stack">
          <Card title="Доход с клиента">
            <div className="stack" style={{ gap: 12 }}>
              <NumberField
                label="Средний чек"
                kind="money"
                value={u.avgCheck}
                min={0}
                onChange={(v) => update((d) => void (d.unit.avgCheck = v))}
              />
              <NumberField
                label="Покупок в месяц"
                value={u.purchasesPerMonth}
                min={0}
                hint="Для подписки — 1. Для разовой покупки раз в полгода — 0,17."
                onChange={(v) => update((d) => void (d.unit.purchasesPerMonth = v))}
              />
              <NumberField
                label="Валовая маржа"
                kind="percent"
                value={u.grossMargin}
                min={0}
                max={1}
                hint="Доля выручки после прямых затрат на клиента"
                onChange={(v) => update((d) => void (d.unit.grossMargin = v))}
              />
              <NumberField
                label="Отток в месяц"
                kind="percent"
                value={u.monthlyChurn}
                min={0}
                max={1}
                hint={`Средний срок жизни клиента — ${fmtMonths(r.lifetimeMonths)}. Для разовых покупок без повторов — 100%.`}
                onChange={(v) => update((d) => void (d.unit.monthlyChurn = v))}
              />
            </div>
          </Card>
          <Card title="Стоимость привлечения">
            <Tabs
              tabs={[
                { id: "direct", label: "CAC напрямую" },
                { id: "funnel", label: "Через воронку" },
              ]}
              value={u.cacMode}
              onChange={(mode) => update((d) => void (d.unit.cacMode = mode))}
            />
            {u.cacMode === "direct" ? (
              <NumberField
                label="CAC — стоимость привлечения клиента"
                kind="money"
                value={u.cac}
                min={0}
                onChange={(v) => update((d) => void (d.unit.cac = v))}
              />
            ) : (
              <div className="stack" style={{ gap: 12 }}>
                <NumberField
                  label="Стоимость лида (заявки)"
                  kind="money"
                  value={u.costPerLead}
                  min={0}
                  onChange={(v) => update((d) => void (d.unit.costPerLead = v))}
                />
                <NumberField
                  label="Конверсия лида в клиента"
                  kind="percent"
                  value={u.leadToCustomer}
                  min={0}
                  max={1}
                  onChange={(v) => update((d) => void (d.unit.leadToCustomer = v))}
                />
                <div className="small text-2">
                  CAC = {money(u.costPerLead, false)} ÷ {fmtPercent(u.leadToCustomer, 1)} = <b>{money(r.cac, false)}</b>
                </div>
              </div>
            )}
          </Card>
          <Card title="Точка безубыточности">
            <div className="stack" style={{ gap: 12 }}>
              <NumberField
                label="Постоянные расходы в месяц"
                kind="money"
                value={u.fixedCostsMonthly}
                min={0}
                onChange={(v) => update((d) => void (d.unit.fixedCostsMonthly = v))}
              />
              <NumberField
                label="Ставка дисконтирования (год)"
                kind="percent"
                value={u.discountRateYear}
                min={0}
                max={1}
                onChange={(v) => update((d) => void (d.unit.discountRateYear = v))}
              />
              <Stat
                label="Активных клиентов для безубыточности"
                value={Number.isFinite(r.breakEvenCustomers) ? fmtNumber(Math.ceil(r.breakEvenCustomers)) : "∞"}
                sub="постоянные расходы ÷ валовая прибыль с клиента"
              />
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
