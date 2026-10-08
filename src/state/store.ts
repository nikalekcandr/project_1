import { useSyncExternalStore } from "react";
import { createProject, demoProject, emptyIdea } from "../core/factory";
import { DEFAULT_MC_PARAMS } from "../core/monteCarlo";
import type { FounderProfile, Idea, Project } from "../core/types";

export type AiModel = "claude-opus-5-5" | "claude-sonnet-5-5" | "claude-haiku-5-5";
export type AiEffort = "low" | "medium" | "high";
export type Theme = "system" | "light" | "dark";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  at: number;
}

export interface Settings {
  aiModel: AiModel;
  aiEffort: AiEffort;
  theme: Theme;
}

export interface AppState {
  version: 1;
  projects: Project[];
  activeProjectId: string | null;
  ideas: Idea[];
  profile: FounderProfile;
  settings: Settings;
  chats: Record<string, ChatMessage[]>;
}

const STORAGE_KEY = "bizforge:v1";
const API_KEY_STORAGE = "bizforge:apiKey";

export const DEFAULT_PROFILE: FounderProfile = {
  skills: [],
  budget: 500_000,
  hoursPerWeek: 20,
  interests: [],
  riskTolerance: "medium",
  preferredSegments: [],
};

const DEFAULT_SETTINGS: Settings = { aiModel: "claude-opus-5-5", aiEffort: "medium", theme: "system" };

function initialState(): AppState {
  const demo = demoProject();
  return {
    version: 1,
    projects: [demo],
    activeProjectId: demo.id,
    ideas: [],
    profile: DEFAULT_PROFILE,
    settings: DEFAULT_SETTINGS,
    chats: {},
  };
}

/** Fills fields that may be missing in data saved by older versions or imported from files. */
export function normalizeProject(raw: Partial<Project>): Project {
  const base = createProject({ title: raw.idea?.title ?? raw.name ?? "Без названия" });
  const p = { ...base, ...raw } as Project;
  p.idea = { ...emptyIdea(), ...raw.idea };
  p.market = {
    ...base.market,
    ...raw.market,
    topDown: { ...base.market.topDown, ...raw.market?.topDown },
    bottomUp: { ...base.market.bottomUp, ...raw.market?.bottomUp },
  };
  p.unit = { ...base.unit, ...raw.unit };
  p.finance = { ...base.finance, ...raw.finance };
  p.monteCarlo = {
    ...base.monteCarlo,
    ...raw.monteCarlo,
    params: DEFAULT_MC_PARAMS.map((d) => ({ ...d, ...raw.monteCarlo?.params?.find((x) => x.key === d.key) })),
  };
  p.plan = { ...base.plan, ...raw.plan, useOfFunds: { ...base.plan.useOfFunds, ...raw.plan?.useOfFunds } };
  p.positioning = { ...base.positioning, ...raw.positioning };
  p.swot = { ...base.swot, ...raw.swot };
  for (const key of ["competitors", "risks", "hypotheses"] as const) {
    if (!Array.isArray(p[key])) (p as unknown as Record<string, unknown>)[key] = [];
  }
  return p;
}

function load(): AppState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialState();
    const parsed = JSON.parse(raw) as Partial<AppState>;
    const projects = (parsed.projects ?? []).map(normalizeProject);
    return {
      version: 1,
      projects,
      activeProjectId: parsed.activeProjectId ?? projects[0]?.id ?? null,
      ideas: parsed.ideas ?? [],
      profile: { ...DEFAULT_PROFILE, ...parsed.profile },
      settings: { ...DEFAULT_SETTINGS, ...parsed.settings },
      chats: parsed.chats ?? {},
    };
  } catch {
    return initialState();
  }
}

let state: AppState = load();
const listeners = new Set<() => void>();
let saveTimer: ReturnType<typeof setTimeout> | undefined;

function persist() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Storage may be unavailable (private mode) — the app keeps working in memory.
    }
  }, 250);
}

export function getState(): AppState {
  return state;
}

export function setState(updater: (s: AppState) => AppState) {
  state = updater(state);
  persist();
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useStore<T>(selector: (s: AppState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(state), () => selector(state));
}

export function useActiveProject(): Project | null {
  return useStore((s) => s.projects.find((p) => p.id === s.activeProjectId) ?? s.projects[0] ?? null);
}

/* ---------- Actions ---------- */

export const actions = {
  addProject(project: Project) {
    setState((s) => ({ ...s, projects: [project, ...s.projects], activeProjectId: project.id }));
  },
  setActive(id: string) {
    setState((s) => ({ ...s, activeProjectId: id }));
  },
  /** Applies a mutating recipe to a deep copy of the project. */
  updateProject(id: string, recipe: (draft: Project) => void) {
    setState((s) => ({
      ...s,
      projects: s.projects.map((p) => {
        if (p.id !== id) return p;
        const draft = structuredClone(p);
        recipe(draft);
        draft.updatedAt = Date.now();
        return draft;
      }),
    }));
  },
  deleteProject(id: string) {
    setState((s) => {
      const projects = s.projects.filter((p) => p.id !== id);
      const chats = { ...s.chats };
      delete chats[id];
      return {
        ...s,
        projects,
        chats,
        activeProjectId: s.activeProjectId === id ? (projects[0]?.id ?? null) : s.activeProjectId,
      };
    });
  },
  duplicateProject(id: string) {
    const src = state.projects.find((p) => p.id === id);
    if (!src) return;
    const copy = structuredClone(src);
    copy.id = `prj_${Date.now().toString(36)}`;
    copy.name = `${src.name} (копия)`;
    copy.createdAt = copy.updatedAt = Date.now();
    actions.addProject(copy);
  },
  saveIdeas(ideas: Idea[]) {
    setState((s) => {
      const existing = new Set(s.ideas.map((i) => i.title));
      const fresh = ideas.filter((i) => !existing.has(i.title));
      return { ...s, ideas: [...fresh, ...s.ideas] };
    });
  },
  updateIdea(id: string, patch: Partial<Idea>) {
    setState((s) => ({ ...s, ideas: s.ideas.map((i) => (i.id === id ? { ...i, ...patch } : i)) }));
  },
  removeIdea(id: string) {
    setState((s) => ({ ...s, ideas: s.ideas.filter((i) => i.id !== id) }));
  },
  setProfile(patch: Partial<FounderProfile>) {
    setState((s) => ({ ...s, profile: { ...s.profile, ...patch } }));
  },
  setSettings(patch: Partial<Settings>) {
    setState((s) => ({ ...s, settings: { ...s.settings, ...patch } }));
  },
  appendChat(projectId: string, message: ChatMessage) {
    setState((s) => ({ ...s, chats: { ...s.chats, [projectId]: [...(s.chats[projectId] ?? []), message] } }));
  },
  clearChat(projectId: string) {
    setState((s) => ({ ...s, chats: { ...s.chats, [projectId]: [] } }));
  },
  importState(data: unknown): { projects: number; ideas: number } {
    const d = data as Partial<AppState> & { project?: Project };
    const incoming = (d.projects ?? (d.project ? [d.project] : [])).map(normalizeProject);
    const ideas = Array.isArray(d.ideas) ? d.ideas : [];
    if (!incoming.length && !ideas.length) throw new Error("В файле нет проектов или идей BizForge");
    setState((s) => {
      const ids = new Set(s.projects.map((p) => p.id));
      const projects = incoming.map((p) => (ids.has(p.id) ? { ...p, id: `${p.id}_${Date.now().toString(36)}` } : p));
      const titles = new Set(s.ideas.map((i) => i.title));
      return {
        ...s,
        projects: [...projects, ...s.projects],
        ideas: [...ideas.filter((i) => !titles.has(i.title)), ...s.ideas],
        activeProjectId: projects[0]?.id ?? s.activeProjectId,
      };
    });
    return { projects: incoming.length, ideas: ideas.length };
  },
  resetAll() {
    setState(() => initialState());
  },
};

/* ---------- API key (kept outside the exported state) ---------- */

export function getApiKey(): string {
  try {
    return localStorage.getItem(API_KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setApiKey(key: string) {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);
  } catch {
    // ignore
  }
  listeners.forEach((l) => l());
}

export function exportState(): string {
  return JSON.stringify({ app: "bizforge", ...state, exportedAt: new Date().toISOString() }, null, 2);
}
