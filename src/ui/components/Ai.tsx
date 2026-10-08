import { useEffect, useRef, useState, type ReactNode } from "react";
import { AiError, isAiConfigured } from "../../ai/client";
import { isHosted, usePlatformVersion } from "../../platform";
import { useStore } from "../../state/store";
import { navigate } from "../router";
import { Markdown } from "./Markdown";
import { Modal, copyText, toast } from "./ui";

export interface AiTaskState {
  loading: boolean;
  text: string;
  error: string | null;
}

/**
 * Runs an AI task with streaming text, cancellation and friendly errors.
 * `task` receives an AbortSignal and an onText callback for live output.
 */
export function useAiTask() {
  const [state, setState] = useState<AiTaskState>({ loading: false, text: "", error: null });
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function run<T>(task: (signal: AbortSignal, onText: (t: string) => void) => Promise<T>): Promise<T | undefined> {
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    setState({ loading: true, text: "", error: null });
    try {
      const result = await task(ctrl.signal, (text) => setState((s) => ({ ...s, text })));
      setState((s) => ({ ...s, loading: false, text: typeof result === "string" ? result : s.text }));
      return result;
    } catch (e) {
      const err = e instanceof AiError ? e : new AiError(e instanceof Error ? e.message : String(e), "api");
      if (err.kind !== "aborted") toast(err.message, "error");
      setState((s) => ({ ...s, loading: false, error: err.kind === "aborted" ? null : err.message }));
      return undefined;
    } finally {
      if (controller.current === ctrl) controller.current = null;
    }
  }

  return {
    ...state,
    run,
    cancel: () => controller.current?.abort(),
    reset: () => setState({ loading: false, text: "", error: null }),
  };
}

/** Button that runs an AI action — or explains how to enable AI if no key is configured. */
export function AiButton(props: { onClick: () => void; loading?: boolean; children: ReactNode; small?: boolean; title?: string }) {
  useStore((s) => s.settings); // re-render when settings change
  usePlatformVersion();
  const [ask, setAsk] = useState(false);
  return (
    <>
      <button
        className={`btn ai ${props.small ? "sm" : ""}`}
        disabled={props.loading}
        title={props.title}
        onClick={() => (isAiConfigured() ? props.onClick() : setAsk(true))}
      >
        {props.loading ? <span className="spinner" aria-hidden /> : <span aria-hidden>✨</span>}
        {props.children}
      </button>
      {ask && (
        <Modal title={isHosted ? "ИИ недоступен" : "Подключите ИИ"} onClose={() => setAsk(false)}>
          {isHosted ? (
            <p>
              ИИ-функции работают через ваш аккаунт claude.ai. Сейчас доступ к Claude в этом просмотре закрыт: войдите в claude.ai или
              разрешите странице обращаться к Claude, затем откройте её снова.
            </p>
          ) : (
            <p>
              ИИ-функции BizForge работают на <b>Claude</b> от Anthropic. Чтобы их включить, добавьте свой API-ключ в настройках — он
              хранится только в вашем браузере и отправляется напрямую в Anthropic.
            </p>
          )}
          <p className="text-2 small">
            Все остальные функции — генератор, оценка, финмодель, Монте-Карло, бизнес-план — работают без ИИ и без интернета.
          </p>
          <div className="row mt-16">
            {!isHosted && (
              <button
                className="btn primary"
                onClick={() => {
                  setAsk(false);
                  navigate("settings");
                }}
              >
                Открыть настройки
              </button>
            )}
            <button className="btn ghost" onClick={() => setAsk(false)}>
              Позже
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

/** Panel showing streamed AI Markdown output. */
export function AiOutput(props: {
  title: ReactNode;
  task: AiTaskState & { cancel: () => void };
  onClose?: () => void;
  actions?: ReactNode;
  placeholder?: ReactNode;
}) {
  const { loading, text, error } = props.task;
  if (!loading && !text && !error) return null;
  return (
    <div className="ai-panel">
      <div className="row-between mb-8">
        <h3>✨ {props.title}</h3>
        <div className="row no-print">
          {loading && (
            <button className="btn sm ghost" onClick={props.task.cancel}>
              Остановить
            </button>
          )}
          {!loading && text && (
            <button className="btn sm ghost" onClick={() => copyText(text)}>
              Копировать
            </button>
          )}
          {props.actions}
          {props.onClose && !loading && (
            <button className="btn sm ghost icon" aria-label="Скрыть" onClick={props.onClose}>
              ✕
            </button>
          )}
        </div>
      </div>
      {error && <div className="callout bad">{error}</div>}
      {loading && !text && (
        <div className="row text-2 small">
          <span className="spinner" /> {props.placeholder ?? "Claude думает…"}
        </div>
      )}
      {text && (
        <div className={`ai-output ${loading ? "typing" : ""}`}>
          <Markdown text={text} />
        </div>
      )}
    </div>
  );
}
