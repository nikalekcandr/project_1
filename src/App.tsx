import { useEffect, useState } from "react";
import { actions, useActiveProject, useStore } from "./state/store";
import { Toasts } from "./ui/components/ui";
import { navigate, useRoute, type Route } from "./ui/router";
import { AdvisorPage } from "./ui/pages/AdvisorPage";
import { CanvasPage } from "./ui/pages/CanvasPage";
import { ExperimentsPage } from "./ui/pages/ExperimentsPage";
import { FinancePage } from "./ui/pages/FinancePage";
import { GeneratorPage } from "./ui/pages/GeneratorPage";
import { IdeasPage } from "./ui/pages/IdeasPage";
import { MarketPage } from "./ui/pages/MarketPage";
import { MonteCarloPage } from "./ui/pages/MonteCarloPage";
import { OverviewPage } from "./ui/pages/OverviewPage";
import { PlanPage } from "./ui/pages/PlanPage";
import { ProjectsPage } from "./ui/pages/ProjectsPage";
import { RisksPage } from "./ui/pages/RisksPage";
import { SettingsPage } from "./ui/pages/SettingsPage";
import { UnitPage } from "./ui/pages/UnitPage";
import { ValidationPage } from "./ui/pages/ValidationPage";

interface NavItem {
  route: Route;
  label: string;
  icon: string;
  project?: boolean;
}

const NAV: { title: string; items: NavItem[] }[] = [
  {
    title: "Идеи",
    items: [
      { route: "generator", label: "Генератор идей", icon: "💡" },
      { route: "ideas", label: "Банк идей", icon: "🗂️" },
    ],
  },
  {
    title: "Проект",
    items: [
      { route: "overview", label: "Обзор", icon: "🧭", project: true },
      { route: "validation", label: "Оценка идеи", icon: "🎯", project: true },
      { route: "canvas", label: "Бизнес-модель", icon: "🧩", project: true },
      { route: "market", label: "Рынок и конкуренты", icon: "🌍", project: true },
      { route: "unit", label: "Юнит-экономика", icon: "⚖️", project: true },
      { route: "finance", label: "Финансовая модель", icon: "📈", project: true },
      { route: "montecarlo", label: "Монте-Карло", icon: "🎲", project: true },
      { route: "risks", label: "Риски и SWOT", icon: "🛡️", project: true },
      { route: "experiments", label: "Гипотезы", icon: "🧪", project: true },
      { route: "plan", label: "Бизнес-план", icon: "📄", project: true },
      { route: "advisor", label: "ИИ-консультант", icon: "✨", project: true },
    ],
  },
  {
    title: "Прочее",
    items: [
      { route: "projects", label: "Мои проекты", icon: "📁" },
      { route: "settings", label: "Настройки", icon: "⚙️" },
    ],
  },
];

const PAGES: Record<Route, () => React.JSX.Element> = {
  generator: GeneratorPage,
  ideas: IdeasPage,
  projects: ProjectsPage,
  overview: OverviewPage,
  validation: ValidationPage,
  canvas: CanvasPage,
  market: MarketPage,
  unit: UnitPage,
  finance: FinancePage,
  montecarlo: MonteCarloPage,
  risks: RisksPage,
  experiments: ExperimentsPage,
  plan: PlanPage,
  advisor: AdvisorPage,
  settings: SettingsPage,
};

function useTheme() {
  const theme = useStore((s) => s.settings.theme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);
  return theme;
}

export function App() {
  const route = useRoute();
  const theme = useTheme();
  const project = useActiveProject();
  const projects = useStore((s) => s.projects);
  const ideasCount = useStore((s) => s.ideas.length);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => setMenuOpen(false), [route]);
  useEffect(() => {
    const item = NAV.flatMap((g) => g.items).find((i) => i.route === route);
    document.title = item ? `${item.label} · BizForge` : "BizForge";
  }, [route]);

  const needsProject = NAV.flatMap((g) => g.items).find((i) => i.route === route)?.project ?? false;
  const Page = needsProject && !project ? ProjectsPage : PAGES[route];

  const cycleTheme = () => actions.setSettings({ theme: theme === "system" ? "dark" : theme === "dark" ? "light" : "system" });

  return (
    <div className="app">
      {menuOpen && <div className="sidebar-backdrop" onClick={() => setMenuOpen(false)} />}
      <aside className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Навигация">
        <div className="brand">
          <div className="brand-logo" aria-hidden>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 18l6-12 5 9 2.5-4L21 18" />
            </svg>
          </div>
          <div>
            BizForge
            <small>лаборатория бизнес-идей</small>
          </div>
        </div>
        {NAV.map((group) => (
          <nav className="nav-group" key={group.title}>
            <div className="nav-title">{group.title}</div>
            {group.items.map((item) => (
              <a
                key={item.route}
                href={`#/${item.route}`}
                className={`nav-item ${route === item.route ? "active" : ""}`}
                aria-current={route === item.route ? "page" : undefined}
              >
                <span className="nav-icon" aria-hidden>
                  {item.icon}
                </span>
                {item.label}
                {item.route === "ideas" && ideasCount > 0 && <span className="nav-badge">{ideasCount}</span>}
                {item.route === "projects" && <span className="nav-badge">{projects.length}</span>}
              </a>
            ))}
          </nav>
        ))}
      </aside>
      <div className="main">
        <header className="topbar no-print">
          <button className="btn ghost icon menu-btn" aria-label="Меню" onClick={() => setMenuOpen(true)}>
            ☰
          </button>
          {projects.length > 0 && (
            <label className="row" style={{ minWidth: 0, flex: "0 1 380px", flexWrap: "nowrap" }}>
              <span className="muted small hide-sm">Проект:</span>
              <select
                className="select"
                aria-label="Активный проект"
                value={project?.id ?? ""}
                onChange={(e) => actions.setActive(e.target.value)}
                style={{ minWidth: 0, flex: 1 }}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="spacer" />
          <button className="btn sm hide-sm" onClick={() => navigate("generator")}>
            💡 Новые идеи
          </button>
          <button className="btn ghost icon" onClick={cycleTheme} title={`Тема: ${theme === "system" ? "как в системе" : theme === "dark" ? "тёмная" : "светлая"}`} aria-label="Сменить тему">
            {theme === "dark" ? "🌙" : theme === "light" ? "☀️" : "🌓"}
          </button>
        </header>
        <main className="content">
          <Page key={`${route}:${needsProject ? project?.id : ""}`} />
        </main>
      </div>
      <Toasts />
    </div>
  );
}
