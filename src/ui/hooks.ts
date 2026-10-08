import { useMemo } from "react";
import { analyzeProject, type ProjectAnalysis } from "../core/analysis";
import { fmtMoney } from "../core/format";
import type { Project } from "../core/types";
import { actions, useActiveProject } from "../state/store";

export interface ProjectCtx {
  project: Project;
  analysis: ProjectAnalysis;
  update: (recipe: (draft: Project) => void) => void;
  money: (v: number, compact?: boolean) => string;
}

/** Active project + memoised analysis. Pages render only when a project exists (guarded in App). */
export function useProject(): ProjectCtx {
  const project = useActiveProject()!;
  const analysis = useMemo(() => analyzeProject(project), [project]);
  return {
    project,
    analysis,
    update: (recipe) => actions.updateProject(project.id, recipe),
    money: (v, compact = true) => fmtMoney(v, project.currency, compact),
  };
}
