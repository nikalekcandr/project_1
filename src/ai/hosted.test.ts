// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

/** Simulates the claude.ai artifact viewer, which exposes capabilities through `window.claude.use()`. */
function installViewer(sampleImpl: unknown) {
  const sample = Object.assign(vi.fn(sampleImpl as (...a: unknown[]) => unknown), {
    json: vi.fn(async () => ({ scores: [{ criterion: "problem_pain", score: 4, rationale: "ok" }] })),
  });
  (window as unknown as { claude: unknown }).claude = {
    use: vi.fn(async (name: string) => (name === "sample" ? sample : null)),
  };
  return sample;
}

describe("AI inside the claude.ai viewer", () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  it("uses the viewer's Claude instead of an API key", async () => {
    const sample = installViewer(async (_input: unknown, opts: { onText?: (u: { text: string; delta: string }) => void }) => {
      opts.onText?.({ text: "Ответ", delta: "Ответ" });
      return { text: "Ответ", truncated: false };
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { initPlatform } = await import("../platform");
    await initPlatform();
    const { aiMode, completeAi, completeJson } = await import("./client");

    expect(aiMode()).toBe("host");
    const streamed: string[] = [];
    const text = await completeAi({ system: "Правила", messages: [{ role: "user", content: "Вопрос" }], onText: (t) => streamed.push(t) });
    expect(text).toBe("Ответ");
    expect(streamed).toEqual(["Ответ"]);
    const [turns, options] = sample.mock.calls[0] as [{ role: string; content: string }[], { modelTier: string }];
    expect(turns[0]).toEqual({ role: "user", content: "Инструкции для тебя:\nПравила" });
    expect(turns.at(-1)).toEqual({ role: "user", content: "Вопрос" });
    expect(options.modelTier).toBe("default");

    const json = await completeJson<{ scores: unknown[] }>({
      system: "s",
      messages: [{ role: "user", content: "Оцени" }],
      schema: { type: "object", properties: { scores: { type: "array" } }, required: ["scores"], additionalProperties: false },
    });
    expect(json.scores).toHaveLength(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("turns a declined consent into a friendly error and disables AI for the view", async () => {
    installViewer(async () => Promise.reject({ code: "not_granted", message: "declined" }));
    const { initPlatform } = await import("../platform");
    await initPlatform();
    const { aiMode, completeAi } = await import("./client");
    await expect(completeAi({ system: "s", messages: [{ role: "user", content: "x" }] })).rejects.toMatchObject({ kind: "auth" });
    expect(aiMode()).toBe("none");
  });
});
