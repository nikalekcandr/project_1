// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";

const PAGES: [string, string][] = [
  ["overview", "ФитПульс (демо)"],
  ["generator", "Генератор бизнес-идей"],
  ["ideas", "Банк идей"],
  ["projects", "Мои проекты"],
  ["validation", "Оценка идеи"],
  ["canvas", "Бизнес-модель"],
  ["market", "Рынок и конкуренты"],
  ["unit", "Юнит-экономика"],
  ["finance", "Финансовая модель"],
  ["montecarlo", "Анализ рисков: Монте-Карло"],
  ["risks", "Риски и SWOT"],
  ["experiments", "Гипотезы и эксперименты"],
  ["plan", "Бизнес-план"],
  ["advisor", "ИИ-консультант"],
  ["settings", "Настройки"],
];

afterEach(cleanup);

describe("App smoke test", () => {
  it.each(PAGES)("renders the %s page", async (route, heading) => {
    window.location.hash = `/${route}`;
    await act(async () => {
      render(<App />);
    });
    expect(screen.getByRole("heading", { level: 1, name: heading })).toBeTruthy();
  });
});
