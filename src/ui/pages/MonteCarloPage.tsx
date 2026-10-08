import { useEffect, useState } from "react";
import { fmtMonths, fmtNumber, fmtPercent } from "../../core/format";
import { MC_PARAMS, histogram, runMonteCarlo, type MonteCarloResult } from "../../core/monteCarlo";
import type { MonteCarloParam } from "../../core/types";
import { BarChart, LineChart } from "../components/charts";
import { Card, NumberField, PageHeader, Select, Stat } from "../components/ui";
import { useProject } from "../hooks";

/** Lets the "Считаем…" state paint before the (synchronous) simulation blocks the main thread. */
const nextFrame = () => new Promise<void>((r) => requestAnimationFrame(() => setTimeout(r, 0)));

export function MonteCarloPage() {
  const { project: p, analysis: a, update, money } = useProject();
  const cfg = p.monteCarlo;
  const [result, setResult] = useState<MonteCarloResult | null>(null);
  const [running, setRunning] = useState(false);
  const [stale, setStale] = useState(false);

  const run = async () => {
    setRunning(true);
    await nextFrame();
    setResult(runMonteCarlo(p.finance, cfg));
    setRunning(false);
    setStale(false);
  };

  // Run once on open; later runs are explicit so typing in the inputs stays responsive.
  useEffect(() => {
    void run();
  }, []);

  const setParam = (key: MonteCarloParam["key"], patch: Partial<MonteCarloParam>) => {
    update((d) => {
      d.monteCarlo.params = d.monteCarlo.params.map((x) => (x.key === key ? { ...x, ...patch } : x));
    });
    setStale(true);
  };

  const fundingBins = result ? histogram(result.fundingNeed.values, 24) : [];
  const npvBins = result ? histogram(result.npv.values, 24) : [];
  const binLabel = (b: { x0: number; x1: number }) => `${money(b.x0)} … ${money(b.x1)}`;

  return (
    <>
      <PageHeader
        title="Анализ рисков: Монте-Карло"
        subtitle="Вместо одного «идеального» прогноза — тысячи сценариев со случайными отклонениями ключевых параметров. Так видно не только «что будет», но и насколько это вероятно."
        actions={
          <button className="btn primary" onClick={run} disabled={running}>
            {running ? <span className="spinner" /> : "▶"} {stale ? "Пересчитать" : "Запустить"}
          </button>
        }
      />

      {result ? (
        <div className="stack" style={{ opacity: running ? 0.6 : 1, transition: "opacity .2s" }}>
          <Card>
            <div className="grid grid-4">
              <Stat
                label="Вероятность выйти в безубыточность"
                tone={result.probBreakEven >= 0.7 ? "good" : result.probBreakEven >= 0.4 ? "warn" : "bad"}
                value={fmtPercent(result.probBreakEven)}
                sub={`за ${p.finance.horizonMonths} мес. · медиана: ${result.breakEvenP50 ? fmtMonths(result.breakEvenP50) : "не достигается"}`}
              />
              <Stat
                label="Вероятность, что денег хватит"
                tone={result.probFullyFunded >= 0.7 ? "good" : result.probFullyFunded >= 0.4 ? "warn" : "bad"}
                value={fmtPercent(result.probFullyFunded)}
                sub="с учётом стартового капитала и раундов"
              />
              <Stat
                label="Потребность в деньгах"
                value={money(result.fundingNeed.p50)}
                sub={`P90 (с запасом): ${money(result.fundingNeed.p90)}`}
              />
              <Stat
                label="Вероятность NPV > 0"
                tone={result.npv.probPositive >= 0.6 ? "good" : result.npv.probPositive >= 0.4 ? "warn" : "bad"}
                value={fmtPercent(result.npv.probPositive)}
                sub={`медиана NPV: ${money(result.npv.p50)}`}
              />
            </div>
            <div className="callout ok mt-16 small">
              <b>Как читать:</b> базовый план требует {money(a.finance.fundingNeed)}, а с учётом неопределённости в 9 из 10 сценариев
              хватит {money(result.fundingNeed.p90)}. Закладывайте в раунд сумму ближе к P90 — это ваш запас прочности.
              {a.finance.npv > result.npv.p50 && " Базовый сценарий оптимистичнее медианы симуляции — допущения финмодели стоит перепроверить."}
            </div>
          </Card>

          <Card title="Веер сценариев: остаток денег" subtitle={`Полоса — от P10 до P90 из ${fmtNumber(result.runs)} прогонов; линия — медиана. Пунктир — базовый план.`}>
            <LineChart
              ariaLabel="Распределение остатка денег по месяцам"
              labels={result.months}
              xTitle={(m) => `Месяц ${m}`}
              format={(v) => money(v)}
              bands={[{ name: "P10–P90", lower: result.cash.p10, upper: result.cash.p90, color: "var(--s1)" }]}
              series={[
                { name: "Медиана (P50)", values: result.cash.p50, color: "var(--s1)" },
                { name: "Базовый план", values: a.finance.rows.map((r) => r.cash), color: "var(--s2)", dashed: true },
              ]}
              height={300}
            />
          </Card>

          <div className="grid grid-2">
            <Card title="Сколько денег понадобится" subtitle="Распределение пиковой потребности в деньгах">
              <BarChart
                ariaLabel="Гистограмма потребности в деньгах"
                categories={fundingBins.map(binLabel)}
                series={[{ name: "Сценариев", values: fundingBins.map((b) => b.count), color: "var(--s1)" }]}
                format={(v) => `${fmtNumber(v)} сценариев`}
                gap={0}
                xNumeric={fundingBins.length ? { min: fundingBins[0].x0, max: fundingBins[fundingBins.length - 1].x1 } : undefined}
                vLines={[
                  { value: result.fundingNeed.p50, label: "P50" },
                  { value: result.fundingNeed.p90, label: "P90" },
                ]}
              />
            </Card>
            <Card title="Распределение NPV" subtitle="Справа от нуля — сценарии, где проект создаёт стоимость">
              <BarChart
                ariaLabel="Гистограмма NPV"
                categories={npvBins.map(binLabel)}
                series={[{ name: "Сценариев", values: npvBins.map((b) => b.count), color: "var(--s3)" }]}
                format={(v) => `${fmtNumber(v)} сценариев`}
                gap={0}
                xNumeric={npvBins.length ? { min: npvBins[0].x0, max: npvBins[npvBins.length - 1].x1 } : undefined}
                vLines={[
                  { value: 0, label: "0" },
                  { value: result.npv.p50, label: "P50" },
                ]}
              />
            </Card>
          </div>

          <Card title="Итоги симуляции">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Метрика</th>
                    <th className="num">P10 (плохой исход)</th>
                    <th className="num">P50 (медиана)</th>
                    <th className="num">P90 (хороший исход)</th>
                    <th className="num">Базовый план</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Выручка за период</td>
                    <td className="num">{money(result.totalRevenue.p10)}</td>
                    <td className="num">{money(result.totalRevenue.p50)}</td>
                    <td className="num">{money(result.totalRevenue.p90)}</td>
                    <td className="num">{money(a.finance.totalRevenue)}</td>
                  </tr>
                  <tr>
                    <td>MRR на конец периода</td>
                    <td className="num">{money(result.endMrr.p10)}</td>
                    <td className="num">{money(result.endMrr.p50)}</td>
                    <td className="num">{money(result.endMrr.p90)}</td>
                    <td className="num">{money(a.finance.endMrr)}</td>
                  </tr>
                  <tr>
                    <td>Потребность в деньгах</td>
                    <td className="num">{money(result.fundingNeed.p90)}</td>
                    <td className="num">{money(result.fundingNeed.p50)}</td>
                    <td className="num">{money(result.fundingNeed.p10)}</td>
                    <td className="num">{money(a.finance.fundingNeed)}</td>
                  </tr>
                  <tr>
                    <td>NPV</td>
                    <td className="num">{money(result.npv.p10)}</td>
                    <td className="num">{money(result.npv.p50)}</td>
                    <td className="num">{money(result.npv.p90)}</td>
                    <td className="num">{money(a.finance.npv)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      ) : (
        <Card>
          <div className="row text-2">
            <span className="spinner" /> Считаем сценарии…
          </div>
        </Card>
      )}

      <Card
        title="Неопределённость допущений"
        subtitle="Треугольное распределение: минимум, наиболее вероятное и максимальное значение. Для множителей 1 = значение из финмодели."
        className="mt-16"
      >
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Учитывать</th>
                <th>Параметр</th>
                <th className="num">Минимум</th>
                <th className="num">Наиболее вероятно</th>
                <th className="num">Максимум</th>
              </tr>
            </thead>
            <tbody>
              {cfg.params.map((prm) => (
                <tr key={prm.key} style={{ opacity: prm.enabled ? 1 : 0.55 }}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Учитывать: ${MC_PARAMS[prm.key].label}`}
                      checked={prm.enabled}
                      onChange={(e) => setParam(prm.key, { enabled: e.target.checked })}
                    />
                  </td>
                  <td>
                    {MC_PARAMS[prm.key].label}
                    <div className="tiny muted">{MC_PARAMS[prm.key].hint}</div>
                  </td>
                  {(["min", "mode", "max"] as const).map((k) => (
                    <td key={k} style={{ minWidth: 110 }}>
                      <NumberField
                        ariaLabel={`${MC_PARAMS[prm.key].label}: ${k}`}
                        value={prm[k]}
                        min={0}
                        digits={2}
                        suffix={MC_PARAMS[prm.key].unit}
                        onChange={(v) => setParam(prm.key, { [k]: v })}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row mt-16" style={{ alignItems: "flex-start" }}>
          <div style={{ width: 200 }}>
            <Select
              label="Число прогонов"
              value={String(cfg.runs)}
              onChange={(v) => {
                update((d) => void (d.monteCarlo.runs = Number(v)));
                setStale(true);
              }}
              options={[500, 1000, 2000, 5000].map((n) => ({ value: String(n), label: fmtNumber(n) }))}
            />
          </div>
          <div style={{ width: 160 }}>
            <NumberField
              label="Seed"
              value={cfg.seed}
              digits={0}
              hint="Одинаковый seed — одинаковый результат"
              onChange={(v) => {
                update((d) => void (d.monteCarlo.seed = Math.round(v)));
                setStale(true);
              }}
            />
          </div>
        </div>
      </Card>
    </>
  );
}
