import type Anthropic from "@anthropic-ai/sdk";
import { getApiKey, getState, type AiModel } from "../state/store";

export interface AiMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AiRequest {
  system: string;
  messages: AiMessage[];
  /** JSON Schema for structured output; the response text is then guaranteed-valid JSON. */
  schema?: Record<string, unknown>;
  maxTokens?: number;
  onText?: (snapshot: string) => void;
  signal?: AbortSignal;
}

export class AiError extends Error {
  constructor(
    message: string,
    readonly kind: "no_key" | "auth" | "rate_limit" | "network" | "refusal" | "truncated" | "aborted" | "api",
  ) {
    super(message);
  }
}

export const AI_MODELS: { id: AiModel; label: string; hint: string }[] = [
  { id: "claude-opus-5-5", label: "Claude Opus 5.5", hint: "Самая умная модель — лучший выбор для анализа и бизнес-планов" },
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5", hint: "Быстрее и дешевле, отлично справляется с большинством задач" },
  { id: "claude-haiku-5-5", label: "Claude Haiku 5.5", hint: "Самая быстрая и экономичная" },
];

export function isAiConfigured(): boolean {
  return getApiKey().trim().length > 0;
}

/** Server-side refusal fallback is available for Opus 5.5 and Sonnet 5.5 on the Claude API. */
const SUPPORTS_FALLBACK: AiModel[] = ["claude-opus-5-5", "claude-sonnet-5-5"];

export async function completeAi(req: AiRequest): Promise<string> {
  const apiKey = getApiKey().trim();
  if (!apiKey) throw new AiError("Добавьте API-ключ Anthropic в настройках, чтобы включить ИИ-функции.", "no_key");
  const { aiModel, aiEffort } = getState().settings;

  const { default: AnthropicSdk } = await import("@anthropic-ai/sdk");
  // The key belongs to the user and lives only in their browser, so direct browser access is intended here.
  const client = new AnthropicSdk({ apiKey, dangerouslyAllowBrowser: true, maxRetries: 2 });

  const params: Anthropic.Beta.Messages.MessageCreateParamsStreaming = {
    model: aiModel,
    max_tokens: req.maxTokens ?? 32000,
    system: req.system,
    messages: req.messages,
    stream: true,
    output_config: {
      effort: aiEffort,
      ...(req.schema ? { format: { type: "json_schema", schema: req.schema } } : {}),
    },
    ...(SUPPORTS_FALLBACK.includes(aiModel)
      ? { betas: ["server-side-fallback-2026-07-01"], fallbacks: "default" as const }
      : {}),
  };

  try {
    const stream = client.beta.messages.stream(params, { signal: req.signal });
    if (req.onText) stream.on("text", (_delta, snapshot) => req.onText?.(snapshot));
    const message = await stream.finalMessage();
    if (message.stop_reason === "refusal") {
      throw new AiError("Модель отказалась выполнять этот запрос. Попробуйте переформулировать.", "refusal");
    }
    const text = message.content
      .filter((b): b is Anthropic.Beta.Messages.BetaTextBlock => b.type === "text")
      .map((b) => b.text)
      .join("");
    if (message.stop_reason === "max_tokens" && req.schema) {
      throw new AiError("Ответ модели оказался слишком длинным и был обрезан. Попробуйте ещё раз.", "truncated");
    }
    return text;
  } catch (error) {
    throw toAiError(error, AnthropicSdk);
  }
}

function toAiError(error: unknown, Sdk: typeof Anthropic): AiError {
  if (error instanceof AiError) return error;
  if (error instanceof Sdk.APIUserAbortError) return new AiError("Запрос отменён.", "aborted");
  if (error instanceof Sdk.AuthenticationError) return new AiError("Неверный API-ключ. Проверьте ключ в настройках.", "auth");
  if (error instanceof Sdk.PermissionDeniedError)
    return new AiError("У ключа нет доступа к выбранной модели. Выберите другую модель в настройках.", "auth");
  if (error instanceof Sdk.RateLimitError) return new AiError("Превышен лимит запросов. Подождите минуту и повторите.", "rate_limit");
  if (error instanceof Sdk.APIConnectionError)
    return new AiError("Не удалось связаться с Claude API. Проверьте интернет-соединение.", "network");
  if (error instanceof Sdk.BadRequestError) return new AiError(`Ошибка запроса: ${error.message}`, "api");
  if (error instanceof Sdk.APIError) return new AiError(`Ошибка Claude API (${error.status ?? "—"}): ${error.message}`, "api");
  return new AiError(error instanceof Error ? error.message : String(error), "api");
}

/** Runs a structured-output request and parses the JSON. */
export async function completeJson<T>(req: AiRequest & { schema: Record<string, unknown> }): Promise<T> {
  const text = await completeAi(req);
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new AiError("Модель вернула некорректный JSON. Попробуйте ещё раз.", "api");
  }
}
