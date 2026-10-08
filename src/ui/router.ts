import { useSyncExternalStore } from "react";

export type Route =
  | "generator"
  | "ideas"
  | "projects"
  | "overview"
  | "validation"
  | "canvas"
  | "market"
  | "unit"
  | "finance"
  | "montecarlo"
  | "risks"
  | "experiments"
  | "plan"
  | "advisor"
  | "settings";

const ROUTES: Route[] = [
  "generator",
  "ideas",
  "projects",
  "overview",
  "validation",
  "canvas",
  "market",
  "unit",
  "finance",
  "montecarlo",
  "risks",
  "experiments",
  "plan",
  "advisor",
  "settings",
];

function parse(): Route {
  const hash = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return (ROUTES as string[]).includes(hash) ? (hash as Route) : "overview";
}

function subscribe(cb: () => void) {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, parse, () => "overview");
}

export function navigate(route: string) {
  window.location.hash = `/${route}`;
  window.scrollTo({ top: 0 });
}
