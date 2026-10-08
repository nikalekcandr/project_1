import { useMemo, useState } from "react";
import { completeJson } from "../../ai/client";
import { IDEAS_SCHEMA, SYSTEM_BASE, ideasPrompt } from "../../ai/prompts";
import { projectFromIdea } from "../../core/factory";
import { fmtMoney } from "../../core/format";
import { generateIdeas, rescoreIdea, scamperIdeas, type GeneratorMethod } from "../../core/generator";
import { BUSINESS_MODELS, getModel } from "../../core/knowledge/businessModels";
import { INDUSTRIES, getIndustry } from "../../core/knowledge/industries";
import { SEGMENTS, SKILLS } from "../../core/knowledge/library";
import { TRENDS } from "../../core/knowledge/trends";
import { newId } from "../../core/random";
import type { Idea, Segment, SkillId } from "../../core/types";
import { actions, useStore } from "../../state/store";
import { AiButton, useAiTask } from "../components/Ai";
import { Badge, Card, Chips, Empty, Field, NumberField, PageHeader, Select, Tabs, TextArea, TextField, toast } from "../components/ui";
import { navigate } from "../router";

type Mode = GeneratorMethod | "scamper" | "ai";

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "mix", label: "🎲 Микс", hint: "Все методы сразу — максимум разнообразия." },
  { id: "trend_industry", label: "📈 Тренд × отрасль", hint: "Сильный тренд, применённый к реальной проблеме отрасли." },
  { id: "model_transplant", label: "🔁 Перенос модели", hint: "«Uber для…»: проверенная модель известной компании в новой отрасли." },
  { id: "problem_first", label: "🩹 От проблемы", hint: "Начинаем с острой боли клиента и подбираем формат решения." },
  { id: "scamper", label: "🛠️ SCAMPER", hint: "7 приёмов, чтобы переизобрести существующий бизнес." },
  { id: "ai", label: "✨ ИИ-генерация", hint: "Claude придумывает идеи под ваш профиль и пожелания." },
];

export function scoreTone(score = 0) {
  return score >= 65 ? "good" : score >= 50 ? "ok" : score >= 40 ? "warn" : "bad";
}

export function IdeaCard(props: { idea: Idea; saved?: boolean; onSave?: () => void; extra?: React.ReactNode }) {
  const { idea } = props;
  const tone = scoreTone(idea.quickScore);
  const industry = getIndustry(idea.industryId);
  const model = getModel(idea.modelId);
  return (
    <article className="card idea-card">
      {idea.quickScore != null && (
        <div
          className="idea-score"
          title="Экспресс-оценка: рынок, конкуренция, модель, реализуемость, регуляторика и соответствие вашему профилю"
          style={{
            background: `var(--${tone === "good" ? "good" : tone === "ok" ? "accent" : tone === "warn" ? "warn" : "bad"}-soft)`,
            color: `var(--${tone === "good" ? "good" : tone === "ok" ? "accent" : tone === "warn" ? "warn" : "bad"}-text)`,
          }}
        >
          {idea.quickScore}
        </div>
      )}
      <h3>{idea.title}</h3>
      <p className="small text-2" style={{ margin: 0 }}>
        {idea.oneLiner}
      </p>
      <div className="row">
        {industry && <span className="tag">{industry.emoji} {industry.name}</span>}
        {model && <span className="tag">{model.emoji} {model.name}</span>}
        <span className="tag">{SEGMENTS[idea.segment].split(" — ")[0]}</span>
      </div>
      {idea.scoreNotes && idea.scoreNotes.length > 0 && (
        <div className="idea-notes">
          {idea.scoreNotes.slice(0, 4).map((n) => (
            <span key={n}>{n}</span>
          ))}
        </div>
      )}
      {props.extra}
      <div className="idea-actions">
        <button
          className="btn sm primary"
          onClick={() => {
            actions.addProject(projectFromIdea(idea));
            toast(`Проект «${idea.title}» создан`);
            navigate("overview");
          }}
        >
          Проверить идею →
        </button>
        {props.onSave && (
          <button className="btn sm" disabled={props.saved} onClick={props.onSave}>
            {props.saved ? "✓ В банке идей" : "☆ В банк идей"}
          </button>
        )}
      </div>
    </article>
  );
}

interface AiIdea {
  title: string;
  oneLiner: string;
  problem: string;
  solution: string;
  audience: string;
  segment: Segment;
  industryId: string;
  modelId: string;
  whyNow: string;
  firstStep: string;
}

export function GeneratorPage() {
  const profile = useStore((s) => s.profile);
  const savedIdeas = useStore((s) => s.ideas);
  const savedTitles = useMemo(() => new Set(savedIdeas.map((i) => i.title)), [savedIdeas]);
  const [mode, setMode] = useState<Mode>("mix");
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1e9));
  const [count, setCount] = useState(9);
  const [industries, setIndustries] = useState<string[]>([]);
  const [trends, setTrends] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [useProfile, setUseProfile] = useState(true);
  const [scamperBase, setScamperBase] = useState("кофейня у метро");
  const [brief, setBrief] = useState("");
  const [aiIdeas, setAiIdeas] = useState<Idea[]>([]);
  const ai = useAiTask();

  const ideas = useMemo(() => {
    if (mode === "scamper" || mode === "ai") return [];
    return generateIdeas({
      method: mode,
      count,
      seed,
      industries,
      trends,
      models,
      segments,
      profile: useProfile ? profile : undefined,
    });
  }, [mode, count, seed, industries, trends, models, segments, useProfile, profile]);

  const scamper = useMemo(() => scamperIdeas(scamperBase), [scamperBase]);

  const save = (idea: Idea) => {
    actions.saveIdeas([{ ...idea, id: newId("idea"), createdAt: Date.now() }]);
    toast("Идея сохранена в банк идей");
  };

  const runAi = async () => {
    const result = await ai.run((signal) =>
      completeJson<{ ideas: AiIdea[] }>({
        system: SYSTEM_BASE,
        messages: [{ role: "user", content: ideasPrompt(profile, brief, Math.min(10, count)) }],
        schema: IDEAS_SCHEMA,
        signal,
      }),
    );
    if (!result) return;
    setAiIdeas(
      result.ideas.map((i, idx) =>
        rescoreIdea(
          {
            id: `ai_${Date.now()}_${idx}`,
            title: i.title,
            oneLiner: i.oneLiner,
            problem: i.problem,
            solution: i.solution,
            audience: i.audience,
            segment: i.segment,
            industryId: i.industryId,
            modelId: i.modelId,
            method: "ai",
            tags: [i.whyNow, i.firstStep],
            createdAt: Date.now(),
          },
          profile,
        ),
      ),
    );
  };

  const modeInfo = MODES.find((m) => m.id === mode)!;

  return (
    <>
      <PageHeader
        title="Генератор бизнес-идей"
        subtitle="Комбинируем тренды, проблемы отраслей и проверенные бизнес-модели. Каждая идея сразу получает экспресс-оценку с учётом вашего профиля."
      />
      <Tabs tabs={MODES.map((m) => ({ id: m.id, label: m.label }))} value={mode} onChange={setMode} />
      <p className="text-2 small" style={{ marginTop: -8 }}>
        {modeInfo.hint}
      </p>

      <div className="grid grid-side">
        <div className="stack">
          {mode === "scamper" ? (
            <>
              <Card>
                <TextField
                  label="Существующий бизнес, который хотим переизобрести"
                  value={scamperBase}
                  onChange={setScamperBase}
                  placeholder="Например: стоматологическая клиника, автомойка, языковая школа"
                />
              </Card>
              <div className="grid grid-auto">
                {scamper.map((t) => (
                  <Card key={t.key} title={`${t.key} — ${t.name}`} subtitle={t.question}>
                    <ul className="list-plain">
                      {t.ideas.map((text) => (
                        <li key={text} className="check-item">
                          <span style={{ flex: 1 }}>{text}</span>
                          <button
                            className="btn sm ghost"
                            title="Сохранить в банк идей"
                            aria-label="Сохранить в банк идей"
                            disabled={savedTitles.has(text)}
                            onClick={() =>
                              save({
                                id: "",
                                title: text.length > 70 ? `${text.slice(0, 67)}…` : text,
                                oneLiner: text,
                                problem: "",
                                solution: text,
                                audience: "",
                                segment: "b2c",
                                method: "scamper",
                                createdAt: Date.now(),
                              })
                            }
                          >
                            {savedTitles.has(text) ? "✓" : "☆"}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </Card>
                ))}
              </div>
            </>
          ) : mode === "ai" ? (
            <>
              <Card title="Пожелания к идеям" subtitle="Claude учтёт ваш профиль справа и эти пожелания.">
                <TextArea
                  value={brief}
                  onChange={setBrief}
                  rows={3}
                  placeholder="Например: B2B-сервис для малого бизнеса в регионах, можно запустить за 2 месяца без программистов"
                />
                <div className="row mt-16">
                  <AiButton onClick={runAi} loading={ai.loading}>
                    Сгенерировать идеи с ИИ
                  </AiButton>
                  {ai.loading && (
                    <button className="btn ghost" onClick={ai.cancel}>
                      Отменить
                    </button>
                  )}
                </div>
                {ai.error && <div className="callout bad mt-8">{ai.error}</div>}
              </Card>
              {aiIdeas.length > 0 ? (
                <div className="grid grid-auto">
                  {aiIdeas.map((idea) => (
                    <IdeaCard
                      key={idea.id}
                      idea={idea}
                      saved={savedTitles.has(idea.title)}
                      onSave={() => save(idea)}
                      extra={
                        idea.tags && (
                          <div className="small text-2">
                            <div>
                              <b>Почему сейчас:</b> {idea.tags[0]}
                            </div>
                            <div className="mt-8">
                              <b>Первый шаг:</b> {idea.tags[1]}
                            </div>
                          </div>
                        )
                      }
                    />
                  ))}
                </div>
              ) : (
                !ai.loading && <Empty icon="✨" title="Здесь появятся идеи от Claude" />
              )}
            </>
          ) : (
            <>
              <div className="row-between">
                <span className="text-2 small">
                  {ideas.length} идей · отсортированы по экспресс-оценке
                </span>
                <div className="row">
                  <Select
                    compact
                    ariaLabel="Сколько идей генерировать"
                    value={String(count)}
                    onChange={(v) => setCount(Number(v))}
                    options={[6, 9, 12, 18, 24].map((n) => ({ value: String(n), label: `${n} идей` }))}
                  />
                  <button className="btn primary" onClick={() => setSeed(Math.floor(Math.random() * 1e9))}>
                    🎲 Сгенерировать ещё
                  </button>
                  <button
                    className="btn"
                    onClick={() => {
                      actions.saveIdeas(ideas.map((i) => ({ ...i, id: newId("idea") })));
                      toast(`Сохранено идей: ${ideas.length}`);
                    }}
                  >
                    Сохранить все
                  </button>
                </div>
              </div>
              {ideas.length ? (
                <div className="grid grid-auto">
                  {ideas.map((idea) => (
                    <IdeaCard key={idea.id} idea={idea} saved={savedTitles.has(idea.title)} onSave={() => save(idea)} />
                  ))}
                </div>
              ) : (
                <Empty icon="🤔" title="По таким фильтрам идей нет">
                  Ослабьте фильтры справа.
                </Empty>
              )}
            </>
          )}
        </div>

        <div className="stack">
          <Card title="Ваш профиль" subtitle="Влияет на экспресс-оценку идей и на ИИ-генерацию.">
            <div className="stack" style={{ gap: 12 }}>
              <Field label="Навыки команды">
                <Chips
                  options={(Object.keys(SKILLS) as SkillId[]).map((s) => ({ value: s, label: SKILLS[s] }))}
                  selected={profile.skills}
                  onChange={(skills) => actions.setProfile({ skills })}
                />
              </Field>
              <div className="grid grid-2" style={{ gap: 10 }}>
                <NumberField
                  label="Бюджет на старт"
                  kind="money"
                  suffix="₽"
                  value={profile.budget}
                  min={0}
                  onChange={(budget) => actions.setProfile({ budget })}
                  hint={fmtMoney(profile.budget)}
                />
                <NumberField
                  label="Часов в неделю"
                  value={profile.hoursPerWeek}
                  digits={0}
                  min={0}
                  max={100}
                  onChange={(hoursPerWeek) => actions.setProfile({ hoursPerWeek })}
                />
              </div>
              <Select
                label="Отношение к риску"
                value={profile.riskTolerance}
                onChange={(riskTolerance) => actions.setProfile({ riskTolerance })}
                options={[
                  { value: "low", label: "Осторожное" },
                  { value: "medium", label: "Умеренное" },
                  { value: "high", label: "Готов рисковать" },
                ]}
              />
              <details className="disclosure">
                <summary>
                  Интересные отрасли {profile.interests.length > 0 && <Badge tone="ok">{profile.interests.length}</Badge>}
                </summary>
                <div className="mt-8">
                  <Chips
                    options={INDUSTRIES.map((i) => ({ value: i.id, label: `${i.emoji} ${i.name}` }))}
                    selected={profile.interests}
                    onChange={(interests) => actions.setProfile({ interests })}
                  />
                </div>
              </details>
              <Field label="Предпочтительные сегменты">
                <Chips
                  options={(["b2c", "b2b", "b2b2c"] as Segment[]).map((s) => ({ value: s, label: SEGMENTS[s].split(" — ")[0] }))}
                  selected={profile.preferredSegments}
                  onChange={(preferredSegments) => actions.setProfile({ preferredSegments })}
                />
              </Field>
              {mode !== "ai" && mode !== "scamper" && (
                <label className="checkbox">
                  <input type="checkbox" checked={useProfile} onChange={(e) => setUseProfile(e.target.checked)} />
                  Учитывать профиль в оценке
                </label>
              )}
            </div>
          </Card>

          {mode !== "ai" && mode !== "scamper" && (
            <Card title="Фильтры генерации">
              <div className="stack" style={{ gap: 12 }}>
                <details className="disclosure">
                  <summary>Отрасли {industries.length > 0 && <Badge tone="ok">{industries.length}</Badge>}</summary>
                  <div className="mt-8">
                    <Chips
                      options={INDUSTRIES.map((i) => ({ value: i.id, label: `${i.emoji} ${i.name}` }))}
                      selected={industries}
                      onChange={setIndustries}
                    />
                  </div>
                </details>
                <Field label="Сегмент">
                  <Chips
                    options={(["b2c", "b2b"] as Segment[]).map((s) => ({ value: s, label: SEGMENTS[s].split(" — ")[0] }))}
                    selected={segments}
                    onChange={setSegments}
                  />
                </Field>
                {(mode === "trend_industry" || mode === "mix") && (
                  <details className="disclosure">
                    <summary>Тренды {trends.length > 0 && <Badge tone="ok">{trends.length}</Badge>}</summary>
                    <div className="mt-8">
                      <Chips options={TRENDS.map((t) => ({ value: t.id, label: `${t.emoji} ${t.name}` }))} selected={trends} onChange={setTrends} />
                    </div>
                  </details>
                )}
                <details className="disclosure">
                  <summary>Бизнес-модели {models.length > 0 && <Badge tone="ok">{models.length}</Badge>}</summary>
                  <div className="mt-8">
                    <Chips options={BUSINESS_MODELS.map((m) => ({ value: m.id, label: `${m.emoji} ${m.name}` }))} selected={models} onChange={setModels} />
                  </div>
                </details>
                {(industries.length > 0 || trends.length > 0 || models.length > 0 || segments.length > 0) && (
                  <button
                    className="btn sm ghost"
                    onClick={() => {
                      setIndustries([]);
                      setTrends([]);
                      setModels([]);
                      setSegments([]);
                    }}
                  >
                    Сбросить фильтры
                  </button>
                )}
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
