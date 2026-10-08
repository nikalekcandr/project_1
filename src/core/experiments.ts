import { EXPERIMENTS, HYPOTHESIS_TYPES, type ExperimentMethod } from "./knowledge/library";
import type { Hypothesis, HypothesisType, ProjectIdea } from "./types";

/**
 * ICE adapted for assumption testing: the less confident we are in a high-impact assumption,
 * the more urgent it is to test it (risk = impact × (11 − confidence)), scaled by ease.
 */
export function priorityScore(h: Pick<Hypothesis, "impact" | "confidence" | "ease">): number {
  return Math.round(((h.impact * (11 - h.confidence) * h.ease) / 1000) * 100);
}

export function sortByPriority(hypotheses: Hypothesis[]): Hypothesis[] {
  const statusOrder = { running: 0, untested: 1, validated: 2, invalidated: 3 } as const;
  return [...hypotheses].sort((a, b) => statusOrder[a.status] - statusOrder[b.status] || priorityScore(b) - priorityScore(a));
}

/** Ranks experiment methods for a hypothesis type: strongest evidence per unit of cost and time first. */
export function recommendExperiments(type: HypothesisType, limit = 3): ExperimentMethod[] {
  return EXPERIMENTS.filter((e) => e.bestFor.includes(type))
    .map((e) => ({ e, score: e.evidence * 2 - e.cost - e.days / 30 }))
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((x) => x.e);
}

export function getExperiment(id: string | undefined): ExperimentMethod | undefined {
  return EXPERIMENTS.find((e) => e.id === id);
}

export interface InterviewScript {
  intro: string[];
  context: string[];
  problem: string[];
  currentSolutions: string[];
  money: string[];
  closing: string[];
  rules: string[];
}

/** Problem interview script in the spirit of "The Mom Test": ask about past behaviour, never pitch. */
export function interviewScript(idea: Pick<ProjectIdea, "audience" | "problem">): InterviewScript {
  const who = idea.audience?.trim() || "клиент";
  const problem = idea.problem?.trim() || "проблема, которую вы решаете";
  return {
    intro: [
      "Спасибо, что нашли время. Я изучаю, как люди решают одну задачу — продавать ничего не буду.",
      "Можно я буду делать заметки? Здесь нет правильных и неправильных ответов.",
    ],
    context: [
      "Расскажите немного о себе и о том, чем вы занимаетесь.",
      `Как выглядит ваш обычный день/неделя в контексте этой темы? (Сегмент: ${who})`,
    ],
    problem: [
      `Когда вы в последний раз сталкивались с ситуацией: «${problem}»? Расскажите подробно, как это было.`,
      "Что было самым сложным или неприятным в этой ситуации?",
      "Как часто это происходит?",
      "Что это вам стоило — по времени, деньгам, нервам?",
    ],
    currentSolutions: [
      "Как вы решаете это сейчас? Покажите, если можно.",
      "Что ещё пробовали? Почему перестали пользоваться?",
      "Что вам не нравится в текущем способе?",
    ],
    money: [
      "Тратите ли вы сейчас деньги на решение этой задачи? Сколько и на что?",
      "Кто принимает решение о покупке таких решений и из какого бюджета?",
    ],
    closing: [
      "Что я не спросил, но должен был спросить?",
      "С кем ещё мне стоит поговорить на эту тему?",
      "Можно я вернусь к вам, когда у нас будет что показать?",
    ],
    rules: [
      "Спрашивайте о прошлом опыте, а не о будущем («Вы бы купили?» — плохой вопрос).",
      "Не рассказывайте о своей идее, пока не закончите выяснять проблему.",
      "Ищите конкретику: даты, суммы, названия инструментов.",
      "Комплименты и «звучит интересно» — это не данные. Данные — это потраченные деньги и время.",
      "Сигнал успеха — человек сам предлагает следующий шаг: пилот, предоплату, знакомство с коллегой.",
    ],
  };
}

export function hypothesisTemplate(type: HypothesisType, idea: Pick<ProjectIdea, "audience" | "problem" | "solution">): string {
  const tpl = HYPOTHESIS_TYPES[type].template;
  return tpl
    .replace("[сегмент]", idea.audience || "[сегмент]")
    .replace("[проблема]", idea.problem ? `«${idea.problem}»` : "[проблема]")
    .replace("[решение]", idea.solution || "[решение]");
}
