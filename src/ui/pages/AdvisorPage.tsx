import { useEffect, useRef, useState } from "react";
import { completeAi, isAiConfigured } from "../../ai/client";
import { isHosted, usePlatformVersion } from "../../platform";
import { ADVISOR_PROMPT, SYSTEM_BASE, projectContext } from "../../ai/prompts";
import { actions, useStore, type ChatMessage } from "../../state/store";
import { AiButton, useAiTask } from "../components/Ai";
import { Markdown } from "../components/Markdown";
import { Card, PageHeader } from "../components/ui";
import { useProject } from "../hooks";
import { navigate } from "../router";

const SUGGESTIONS = [
  "Какие три главных риска у проекта и как их снизить?",
  "Как найти первых 10 платящих клиентов за месяц?",
  "Как снизить стоимость привлечения клиента?",
  "Составь план действий на ближайшие 30 дней",
  "Реалистична ли моя финансовая модель? Что в ней слабее всего?",
  "Какую цену поставить и как упаковать тарифы?",
];

const EMPTY: ChatMessage[] = [];

export function AdvisorPage() {
  const { project: p, analysis: a } = useProject();
  const history = useStore((s) => s.chats[p.id] ?? EMPTY);
  const [input, setInput] = useState("");
  const ai = useAiTask();
  const endRef = useRef<HTMLDivElement>(null);
  usePlatformVersion();
  const configured = isAiConfigured();

  useEffect(() => {
    if (history.length || ai.text) endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [history.length, ai.text]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || ai.loading) return;
    setInput("");
    const userMsg: ChatMessage = { role: "user", content: question, at: Date.now() };
    actions.appendChat(p.id, userMsg);
    const messages = [...history, userMsg].slice(-20).map((m) => ({ role: m.role, content: m.content }));
    const answer = await ai.run((signal, onText) =>
      completeAi({
        system: `${SYSTEM_BASE}\n\n${ADVISOR_PROMPT}\n\n${projectContext(p, a)}`,
        messages,
        onText,
        signal,
      }),
    );
    if (answer) {
      actions.appendChat(p.id, { role: "assistant", content: answer, at: Date.now() });
      ai.reset();
    }
  };

  return (
    <>
      <PageHeader
        title="ИИ-консультант"
        subtitle="Claude видит весь ваш проект — оценку, холсты, рынок, юнит-экономику, финмодель, риски и гипотезы — и отвечает с опорой на ваши цифры."
        actions={
          history.length > 0 && (
            <button className="btn ghost" onClick={() => actions.clearChat(p.id)}>
              Очистить диалог
            </button>
          )
        }
      />

      <Card>
        <div className="chat">
          {history.length === 0 && !ai.loading && (
            <div className="stack" style={{ gap: 10 }}>
              <p className="text-2" style={{ margin: 0 }}>
                Задайте вопрос о проекте «{p.name}» или выберите готовый:
              </p>
              <div className="chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => (configured ? send(s) : setInput(s))}>
                    {s}
                  </button>
                ))}
              </div>
              {!configured &&
                (isHosted ? (
                  <div className="callout ok small">Консультант работает через ваш аккаунт claude.ai — войдите, чтобы задать вопрос.</div>
                ) : (
                  <div className="callout ok small">
                    Для консультанта нужен API-ключ Anthropic.{" "}
                    <a href="#/settings" onClick={() => navigate("settings")}>
                      Добавить ключ в настройках
                    </a>
                  </div>
                ))}
            </div>
          )}
          {history.map((m) =>
            m.role === "user" ? (
              <div key={m.at} className="msg user">
                {m.content}
              </div>
            ) : (
              <div key={m.at} className="msg assistant">
                <Markdown text={m.content} />
              </div>
            ),
          )}
          {ai.loading && (
            <div className={`msg assistant ${ai.text ? "typing" : ""}`}>
              {ai.text ? (
                <Markdown text={ai.text} />
              ) : (
                <span className="row text-2 small">
                  <span className="spinner" /> Claude анализирует проект…
                </span>
              )}
            </div>
          )}
          {ai.error && <div className="callout bad small">{ai.error}</div>}
          <div ref={endRef} />
        </div>

        <form
          className="row mt-16"
          style={{ alignItems: "flex-end" }}
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <textarea
            className="textarea"
            style={{ flex: 1, minHeight: 48 }}
            rows={2}
            aria-label="Ваш вопрос"
            placeholder="Спросите что угодно о проекте… (Enter — отправить, Shift+Enter — новая строка)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (configured) void send(input);
              }
            }}
          />
          {ai.loading ? (
            <button type="button" className="btn" onClick={ai.cancel}>
              Остановить
            </button>
          ) : (
            <AiButton onClick={() => void send(input)}>Отправить</AiButton>
          )}
        </form>
      </Card>
    </>
  );
}
