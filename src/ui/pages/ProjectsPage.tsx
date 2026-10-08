import { useMemo, useRef, useState } from "react";
import { analyzeProject } from "../../core/analysis";
import { createProject } from "../../core/factory";
import { fmtMoney, slugify } from "../../core/format";
import type { Project } from "../../core/types";
import { VERDICTS } from "../../core/validation";
import { actions, useStore } from "../../state/store";
import { Badge, Card, Empty, Modal, PageHeader, TextField, downloadFile, toast } from "../components/ui";
import { navigate } from "../router";

export function ProjectsPage() {
  const projects = useStore((s) => s.projects);
  const activeId = useStore((s) => s.activeProjectId);
  const [creating, setCreating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const rows = useMemo(() => projects.map((p) => ({ p, a: analyzeProject(p) })), [projects]);

  const importFile = async (file: File) => {
    try {
      const data = JSON.parse(await file.text());
      const res = actions.importState(data);
      toast(`Импортировано: проектов — ${res.projects}, идей — ${res.ideas}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Не удалось прочитать файл", "error");
    }
  };

  return (
    <>
      <PageHeader
        title="Мои проекты"
        subtitle="Каждый проект — полный набор: оценка, бизнес-модель, рынок, финансы, риски и бизнес-план. Данные хранятся только в вашем браузере."
        actions={
          <>
            <button className="btn" onClick={() => fileRef.current?.click()}>
              ⬆ Импорт JSON
            </button>
            <button className="btn primary" onClick={() => setCreating(true)}>
              ＋ Новый проект
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importFile(f);
                e.target.value = "";
              }}
            />
          </>
        }
      />
      {rows.length === 0 ? (
        <Card>
          <Empty icon="📁" title="Пока нет проектов">
            <p className="text-2">Создайте проект с нуля или из идеи генератора.</p>
            <div className="row" style={{ justifyContent: "center" }}>
              <button className="btn primary" onClick={() => setCreating(true)}>
                ＋ Новый проект
              </button>
              <button className="btn" onClick={() => navigate("generator")}>
                💡 К генератору
              </button>
              <button className="btn ghost" onClick={() => actions.resetAll()}>
                Загрузить демо
              </button>
            </div>
          </Empty>
        </Card>
      ) : (
        <div className="grid grid-auto">
          {rows.map(({ p, a }) => {
            const v = VERDICTS[a.validation.verdict];
            return (
              <Card key={p.id} className={p.id === activeId ? "accent" : ""}>
                <div className="stack" style={{ gap: 10 }}>
                  <div className="row-between">
                    <h3>{p.name}</h3>
                    {p.id === activeId && <Badge tone="ok">Активный</Badge>}
                  </div>
                  <p className="small text-2" style={{ margin: 0 }}>
                    {p.idea.oneLiner || p.idea.problem || "Описание не заполнено"}
                  </p>
                  <div className="grid grid-2" style={{ gap: 8 }}>
                    <div className="small">
                      <div className="muted">Оценка идеи</div>
                      <b>{a.validation.answered ? Math.round(a.validation.score) : "—"}</b> <Badge tone={v.tone}>{v.label}</Badge>
                    </div>
                    <div className="small">
                      <div className="muted">Готовность</div>
                      <b>{a.readiness.score}%</b>
                    </div>
                    <div className="small">
                      <div className="muted">Безубыточность</div>
                      <b>{a.finance.breakEvenMonth ? `${a.finance.breakEvenMonth}-й мес.` : "нет"}</b>
                    </div>
                    <div className="small">
                      <div className="muted">Нужно денег</div>
                      <b>{fmtMoney(a.finance.fundingNeed, p.currency)}</b>
                    </div>
                  </div>
                  <div className="muted tiny">Изменён {new Date(p.updatedAt).toLocaleString("ru-RU")}</div>
                  <div className="row">
                    <button
                      className="btn sm primary"
                      onClick={() => {
                        actions.setActive(p.id);
                        navigate("overview");
                      }}
                    >
                      Открыть
                    </button>
                    <button className="btn sm" onClick={() => actions.duplicateProject(p.id)}>
                      Копия
                    </button>
                    <button className="btn sm" onClick={() => exportProject(p)}>
                      Экспорт
                    </button>
                    <button
                      className="btn sm ghost danger"
                      onClick={() => {
                        if (confirm(`Удалить проект «${p.name}»? Это действие нельзя отменить.`)) actions.deleteProject(p.id);
                      }}
                    >
                      Удалить
                    </button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
      {creating && <NewProjectModal onClose={() => setCreating(false)} />}
    </>
  );
}

function exportProject(p: Project) {
  downloadFile(`${slugify(p.name, "project")}.bizforge.json`, JSON.stringify({ app: "bizforge", project: p }, null, 2), "application/json");
}

function NewProjectModal(props: { onClose: () => void }) {
  const [title, setTitle] = useState("");
  return (
    <Modal title="Новый проект" onClose={props.onClose}>
      <TextField label="Название идеи или проекта" value={title} onChange={setTitle} placeholder="Например: сервис доставки цветов по подписке" />
      <p className="small text-2 mt-8">
        Проект создастся с типовыми допущениями — дальше вы заполните описание, оценку и финмодель. Если идеи ещё нет —
        загляните в генератор.
      </p>
      <div className="row mt-16">
        <button
          className="btn primary"
          disabled={!title.trim()}
          onClick={() => {
            actions.addProject(createProject({ title: title.trim() }));
            props.onClose();
            navigate("overview");
          }}
        >
          Создать
        </button>
        <button
          className="btn"
          onClick={() => {
            props.onClose();
            navigate("generator");
          }}
        >
          💡 Выбрать в генераторе
        </button>
      </div>
    </Modal>
  );
}
