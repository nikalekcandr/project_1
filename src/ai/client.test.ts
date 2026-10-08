// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setApiKey } from "../state/store";
import { AiError, completeAi, completeJson } from "./client";

function sseResponse(text: string, stopReason = "end_turn"): Response {
  const events: [string, unknown][] = [
    ["message_start", { type: "message_start", message: { id: "msg_1", type: "message", role: "assistant", model: "claude-opus-5-5", content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 5, output_tokens: 1 } } }],
    ["content_block_start", { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } }],
    ["content_block_delta", { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: text.slice(0, 3) } }],
    ["content_block_delta", { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: text.slice(3) } }],
    ["content_block_stop", { type: "content_block_stop", index: 0 }],
    ["message_delta", { type: "message_delta", delta: { stop_reason: stopReason, stop_sequence: null }, usage: { output_tokens: 7 } }],
    ["message_stop", { type: "message_stop" }],
  ];
  const body = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

describe("Claude client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setApiKey("sk-ant-test");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setApiKey("");
  });

  it("requires an API key", async () => {
    setApiKey("");
    await expect(completeAi({ system: "s", messages: [{ role: "user", content: "hi" }] })).rejects.toMatchObject({ kind: "no_key" });
  });

  it("streams text and sends model, effort and refusal fallback", async () => {
    fetchMock.mockResolvedValue(sseResponse("Привет, мир"));
    const snapshots: string[] = [];
    const text = await completeAi({ system: "sys", messages: [{ role: "user", content: "hi" }], onText: (t) => snapshots.push(t) });
    expect(text).toBe("Привет, мир");
    expect(snapshots.at(-1)).toBe("Привет, мир");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/v1/messages");
    const body = JSON.parse(String(init.body));
    expect(body).toMatchObject({ model: "claude-opus-5-5", stream: true, system: "sys", fallbacks: "default", output_config: { effort: "medium" } });
    const headers = new Headers(init.headers);
    expect(headers.get("x-api-key")).toBe("sk-ant-test");
    expect(headers.get("anthropic-beta")).toContain("server-side-fallback-2026-07-01");
  });

  it("parses structured JSON output", async () => {
    fetchMock.mockResolvedValue(sseResponse(JSON.stringify({ ok: true, items: [1, 2] })));
    const res = await completeJson<{ ok: boolean; items: number[] }>({
      system: "s",
      messages: [{ role: "user", content: "x" }],
      schema: { type: "object", properties: {}, additionalProperties: false },
    });
    expect(res).toEqual({ ok: true, items: [1, 2] });
    const body = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body.output_config.format.type).toBe("json_schema");
  });

  it("reports refusals and auth errors as typed AiErrors", async () => {
    fetchMock.mockResolvedValue(sseResponse("", "refusal"));
    await expect(completeAi({ system: "s", messages: [{ role: "user", content: "x" }] })).rejects.toMatchObject({ kind: "refusal" });

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ type: "error", error: { type: "authentication_error", message: "invalid x-api-key" } }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );
    const err = await completeAi({ system: "s", messages: [{ role: "user", content: "x" }] }).catch((e) => e);
    expect(err).toBeInstanceOf(AiError);
    expect(err.kind).toBe("auth");
  });
});
