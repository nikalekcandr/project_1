import { useMemo, useState } from "react";
import { quickScore, rescoreIdea } from "../../core/generator";
import { BUSINESS_MODELS, getModel } from "../../core/knowledge/businessModels";
import { INDUSTRIES, getIndustry } from "../../core/knowledge/industries";
import { SEGMENTS } from "../../core/knowledge/library";
import { getTrend } from "../../core/knowledge/trends";
import { newId } from "../../core/random";
import type { Idea, Segment } from "../../core/types";
import { actions, useStore } from "../../state/store";
import { Card, Empty, Modal, PageHeader, Select, TextArea, TextField, toast } from "../components/ui";
import { navigate } from "../router";
import { IdeaCard } from "./GeneratorPage";

type Sort = "score" | "new" | "title";

const PART_LABELS: Record<string, string> = {
  market: "Рынок и тренд",
  competition: "Конкуренция",
  model: "Бизнес-модель",
  feasibility: "Реализуемость",
  regulation: "Регуляторика",
  founderFit: "Соответствие профилю",
};

export function IdeasPage() {
  const ideas = useStore((s) => s.ideas);
  const profile = useStore((s) => s.profile);
  const [sort, setSort] = useState<Sort>("score");
  const [query, setQuery] = useState("");
  const [onlyFav, setOnlyFav] = useState(false);
  const [compare, setCompare] = useState<string[]>([]);
  const [showCompare, setShowCompare] = useState(false);
  const [adding, setAdding] = useState(false);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = ideas.filter(
      (i) => (!onlyFav || i.favorite) && (!q || `${i.title} ${i.oneLiner} ${i.problem}`.toLowerCase().includes(q)),
    );
    return [...filtered].sort((a, b) =>
      sort === "score"
        ? (b.quickScore ?? 0) - (a.quickScore ?? 0)
        : sort === "new"
          ? b.createdAt - a.createdAt
          : a.title.localeCompare(b.title, "ru"),
    );
  }, [ideas, sort, query, onlyFav]);

  const compared = ideas.filter((i) => compare.includes(i.id));

  return (
    <>
      <PageHeader
        title="Банк идей"
        subtitle="Сохранённые идеи: сравнивайте, отбирайте лучшие и превращайте их в проекты для глубокой проверки."
        actions={
          <>
            <button className="btn" onClick={() => setAdding(true)}>
              ＋ Своя идея
            </button>
            <button
              className="btn"
              disabled={!ideas.length}
              onClick={() => {
                ideas.forEach((i) => actions.updateIdea(i.id, rescoreIdea(i, profile)));
                toast("Оценки пересчитаны под текущий профиль");
              }}
            >
              ↻ Пересчитать оценки
            </button>
            <button className="btn primary" disabled={compare.length < 2} onClick={() => setShowCompare(true)}>
              Сравнить ({compare.length})
            </button>
          </>
        }
      />

      {ideas.length === 0 ? (
        <Card>
          <Empty icon="🗂️" title="Банк идей пуст">
            <p className="text-2">Сгенерируйте идеи и сохраните понравившиеся — или добавьте свою.</p>
            <div className="row" style={{ justifyContent: "center" }}>
              <button className="btn primary" onClick={() => navigate("generator")}>
                💡 К генератору
              </button>
              <button className="btn" onClick={() => setAdding(true)}>
                ＋ Своя идея
              </button>
            </div>
          </Empty>
        </Card>
      ) : (
        <>
          <div className="row mb-8" style={{ marginBottom: 16 }}>
            <div style={{ flex: "1 1 240px" }}>
              <TextField value={query} onChange={setQuery} placeholder="Поиск по идеям…" />
            </div>
            <Select
              value={sort}
              onChange={setSort}
              options={[
                { value: "score", label: "По оценке" },
                { value: "new", label: "Сначала новые" },
                { value: "title", label: "По названию" },
              ]}
            />
            <label className="checkbox">
              <input type="checkbox" checked={onlyFav} onChange={(e) => setOnlyFav(e.target.checked)} /> Только избранные
            </label>
          </div>
          <div className="grid grid-auto">
            {list.map((idea) => (
              <IdeaCard
                key={idea.id}
                idea={idea}
                extra={
                  <div className="row">
                    <button
                      className="btn sm ghost"
                      aria-pressed={!!idea.favorite}
                      onClick={() => actions.updateIdea(idea.id, { favorite: !idea.favorite })}
                    >
                      {idea.favorite ? "★ Избранное" : "☆ В избранное"}
                    </button>
                    <label className="checkbox small">
                      <input
                        type="checkbox"
                        checked={compare.includes(idea.id)}
                        onChange={(e) => setCompare(e.target.checked ? [...compare, idea.id] : compare.filter((c) => c !== idea.id))}
                      />
                      Сравнить
                    </label>
                    <button className="btn sm ghost danger" onClick={() => actions.removeIdea(idea.id)}>
                      Удалить
                    </button>
                  </div>
                }
              />
            ))}
          </div>
        </>
      )}

      {showCompare && (
        <Modal title="Сравнение идей" onClose={() => setShowCompare(false)} wide>
          <CompareTable ideas={compared} />
        </Modal>
      )}
      {adding && <AddIdeaModal onClose={() => setAdding(false)} />}
    </>
  );
}

function CompareTable(props: { ideas: Idea[] }) {
  const profile = useStore((s) => s.profile);
  const rows = props.ideas.map((i) => ({
    idea: i,
    qs: quickScore(
      getIndustry(i.industryId),
      getModel(i.modelId),
      i.trendIds?.length ? getTrend(i.trendIds[0]) : undefined,
      i.segment,
      profile,
    ),
  }));
  const keys = Object.keys(PART_LABELS) as (keyof (typeof rows)[number]["qs"]["parts"])[];
  const best = (k: (typeof keys)[number]) => Math.max(...rows.map((r) => r.qs.parts[k]));
  const bestTotal = Math.max(...rows.map((r) => r.qs.score));
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Критерий</th>
            {rows.map((r) => (
              <th key={r.idea.id} style={{ whiteSpace: "normal", minWidth: 160 }}>
                {r.idea.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td>{PART_LABELS[k]}</td>
              {rows.map((r) => (
                <td key={r.idea.id} className="num" style={{ fontWeight: r.qs.parts[k] === best(k) ? 700 : 400 }}>
                  {Math.round(r.qs.parts[k] * 100)}
                  {r.qs.parts[k] === best(k) && rows.length > 1 ? " ★" : ""}
                </td>
              ))}
            </tr>
          ))}
          <tr className="strong">
            <td>Итоговая оценка</td>
            {rows.map((r) => (
              <td key={r.idea.id} className="num">
                {r.qs.score}
                {r.qs.score === bestTotal ? " 🏆" : ""}
              </td>
            ))}
          </tr>
          <tr>
            <td>Отрасль</td>
            {rows.map((r) => (
              <td key={r.idea.id}>{getIndustry(r.idea.industryId)?.name ?? "—"}</td>
            ))}
          </tr>
          <tr>
            <td>Модель</td>
            {rows.map((r) => (
              <td key={r.idea.id}>{getModel(r.idea.modelId)?.name ?? "—"}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function AddIdeaModal(props: { onClose: () => void }) {
  const profile = useStore((s) => s.profile);
  const [draft, setDraft] = useState({
    title: "",
    oneLiner: "",
    problem: "",
    solution: "",
    audience: "",
    segment: "b2c" as Segment,
    industryId: "",
    modelId: "",
  });
  const set = (patch: Partial<typeof draft>) => setDraft((d) => ({ ...d, ...patch }));
  return (
    <Modal title="Новая идея" onClose={props.onClose}>
      <div className="stack" style={{ gap: 12 }}>
        <TextField label="Название" value={draft.title} onChange={(title) => set({ title })} placeholder="Коротко и ёмко" />
        <TextArea label="Суть в одном предложении" value={draft.oneLiner} onChange={(oneLiner) => set({ oneLiner })} rows={2} />
        <TextArea label="Проблема клиента" value={draft.problem} onChange={(problem) => set({ problem })} rows={2} />
        <TextArea label="Решение" value={draft.solution} onChange={(solution) => set({ solution })} rows={2} />
        <TextField label="Целевая аудитория" value={draft.audience} onChange={(audience) => set({ audience })} />
        <div className="grid grid-3">
          <Select
            label="Сегмент"
            value={draft.segment}
            onChange={(segment) => set({ segment })}
            options={(Object.keys(SEGMENTS) as Segment[]).map((s) => ({ value: s, label: SEGMENTS[s] }))}
          />
          <Select
            label="Отрасль"
            value={draft.industryId}
            onChange={(industryId) => set({ industryId })}
            options={[{ value: "", label: "— не выбрана —" }, ...INDUSTRIES.map((i) => ({ value: i.id, label: i.name }))]}
          />
          <Select
            label="Бизнес-модель"
            value={draft.modelId}
            onChange={(modelId) => set({ modelId })}
            options={[{ value: "", label: "— не выбрана —" }, ...BUSINESS_MODELS.map((m) => ({ value: m.id, label: m.name }))]}
          />
        </div>
        <div className="row">
          <button
            className="btn primary"
            disabled={!draft.title.trim()}
            onClick={() => {
              const idea: Idea = rescoreIdea(
                {
                  ...draft,
                  industryId: draft.industryId || undefined,
                  modelId: draft.modelId || undefined,
                  id: newId("idea"),
                  method: "manual",
                  createdAt: Date.now(),
                },
                profile,
              );
              actions.saveIdeas([idea]);
              toast("Идея добавлена");
              props.onClose();
            }}
          >
            Сохранить
          </button>
          <button className="btn ghost" onClick={props.onClose}>
            Отмена
          </button>
        </div>
      </div>
    </Modal>
  );
}
