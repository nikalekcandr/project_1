import { useSyncExternalStore } from "react";

/**
 * Services of the claude.ai artifact viewer, available when BizForge is published as an Artifact.
 * In a regular browser `window.claude` is absent and every service resolves to null.
 */

export interface HostSampleError {
  code: string;
  message: string;
  text?: string;
}

type SampleTurn = { role: "user" | "assistant"; content: string };
type SampleOptions = {
  onText?: (u: { text: string; delta: string }) => void;
  signal?: AbortSignal;
  modelTier?: "quick" | "default" | "complex";
  cache?: boolean;
};

export interface HostSample {
  (input: string | SampleTurn[], options?: SampleOptions): Promise<{ text: string; truncated: boolean }>;
  json<T = unknown>(input: string | SampleTurn[], options?: SampleOptions): Promise<T>;
}

export interface HostDownloads {
  save(request: { filename: string; data: string | Blob }): Promise<{ status: "saved" | "delivered" }>;
}

interface HostRuntime {
  use(name: string): Promise<unknown>;
}

function runtime(): HostRuntime | null {
  const c = (window as unknown as { claude?: { use?: unknown } }).claude;
  return c && typeof c.use === "function" ? (c as HostRuntime) : null;
}

/** True when the page runs inside the claude.ai viewer (printing, plain downloads and API calls are blocked there). */
export const isHosted = typeof window !== "undefined" && runtime() !== null;

let sample: HostSample | null = null;
let downloads: HostDownloads | null = null;
let version = 0;
const listeners = new Set<() => void>();
const notify = () => {
  version++;
  listeners.forEach((l) => l());
};

let started: Promise<void> | null = null;

/** Resolves the viewer's capabilities once; features light up when they arrive. */
export function initPlatform(): Promise<void> {
  if (started) return started;
  const rt = runtime();
  if (!rt) return (started = Promise.resolve());
  started = Promise.all([
    rt.use("sample").then(
      (s) => void (sample = (s as HostSample) ?? null),
      () => undefined,
    ),
    rt.use("downloads").then(
      (d) => void (downloads = (d as HostDownloads) ?? null),
      () => undefined,
    ),
  ]).then(notify);
  return started;
}

export function hostSample(): HostSample | null {
  return sample;
}

export function hostDownloads(): HostDownloads | null {
  return downloads;
}

/** Marks Claude as unavailable for the rest of this view (e.g. the viewer declined access). */
export function disableHostSample() {
  sample = null;
  notify();
}

/** Re-renders a component when host services become available. */
export function usePlatformVersion(): number {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => version,
    () => version,
  );
}
