import { useRef, useState } from "react";
import { AI_MODELS, completeAi } from "../../ai/client";
import { actions, exportState, getApiKey, setApiKey, useStore, type AiEffort, type AiModel, type Theme } from "../../state/store";
import { useAiTask } from "../components/Ai";
import { Card, PageHeader, Select, downloadFile, toast } from "../components/ui";

export function SettingsPage() {
  const settings = useStore((s) => s.settings);
  const [key, setKey] = useState(getApiKey());
  const [show, setShow] = useState(false);
  const test = useAiTask();
  const fileRef = useRef<HTMLInputElement>(null);
  const saved = key.trim() === getApiKey();

  const saveKey = () => {
    setApiKey(key.trim());
    toast(key.trim() ? "Ключ сохранён в этом браузере" : "Ключ удалён");
  };

  const testConnection = async () => {
    if (!saved) saveKey();
    const res = await test.run((signal) =>
      completeAi({
        system: "Ты проверяешь подключение. Ответь ровно одной фразой по-русски.",
        messages: [{ role: "user", content: "Скажи «Подключение работает» и назови себя." }],
        maxTokens: 4000,
        signal,
      }),
    );
    if (res) toast("✓ Claude на связи");
  };

  return (
    <>
      <PageHeader title="Настройки" subtitle="ИИ-ассистент, оформление и управление данными." />
      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <Card title="✨ ИИ на базе Claude" subtitle="ИИ-функции необязательны: всё остальное работает офлайн и без ключа.">
          <div className="stack" style={{ gap: 12 }}>
            <div className="field">
              <label htmlFor="api-key">API-ключ Anthropic</label>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input
                  id="api-key"
                  className="input"
                  type={show ? "text" : "password"}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="sk-ant-…"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                />
                <button className="btn ghost" type="button" onClick={() => setShow(!show)} aria-label={show ? "Скрыть ключ" : "Показать ключ"}>
                  {show ? "🙈" : "👁"}
                </button>
              </div>
              <span className="field-hint">
                Получить ключ: <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">console.anthropic.com</a>. Ключ
                хранится только в этом браузере (localStorage), не попадает в экспорт и отправляется только в api.anthropic.com.
              </span>
            </div>
            <div className="row">
              <button className="btn primary" onClick={saveKey} disabled={saved}>
                {saved ? "✓ Сохранён" : "Сохранить ключ"}
              </button>
              <button className="btn" onClick={testConnection} disabled={!key.trim() || test.loading}>
                {test.loading ? <span className="spinner" /> : "⚡"} Проверить подключение
              </button>
              {getApiKey() && (
                <button
                  className="btn ghost danger"
                  onClick={() => {
                    setKey("");
                    setApiKey("");
                    toast("Ключ удалён");
                  }}
                >
                  Удалить ключ
                </button>
              )}
            </div>
            {test.text && !test.loading && <div className="callout good small">{test.text}</div>}
            {test.error && <div className="callout bad small">{test.error}</div>}
            <Select<AiModel>
              label="Модель"
              value={settings.aiModel}
              onChange={(aiModel) => actions.setSettings({ aiModel })}
              options={AI_MODELS.map((m) => ({ value: m.id, label: m.label }))}
              hint={AI_MODELS.find((m) => m.id === settings.aiModel)?.hint}
            />
            <Select<AiEffort>
              label="Глубина анализа"
              value={settings.aiEffort}
              onChange={(aiEffort) => actions.setSettings({ aiEffort })}
              options={[
                { value: "low", label: "Быстро — короткие ответы" },
                { value: "medium", label: "Сбалансировано (рекомендуется)" },
                { value: "high", label: "Глубоко — дольше и дороже" },
              ]}
            />
          </div>
        </Card>

        <div className="stack">
          <Card title="Оформление">
            <Select<Theme>
              label="Тема"
              value={settings.theme}
              onChange={(theme) => actions.setSettings({ theme })}
              options={[
                { value: "system", label: "Как в системе" },
                { value: "light", label: "Светлая" },
                { value: "dark", label: "Тёмная" },
              ]}
            />
          </Card>

          <Card title="Данные" subtitle="Все проекты и идеи хранятся локально в вашем браузере. Делайте резервные копии.">
            <div className="row">
              <button
                className="btn"
                onClick={() => downloadFile(`bizforge-backup-${new Date().toISOString().slice(0, 10)}.json`, exportState(), "application/json")}
              >
                ⬇ Экспорт всех данных
              </button>
              <button className="btn" onClick={() => fileRef.current?.click()}>
                ⬆ Импорт
              </button>
              <input
                ref={fileRef}
                type="file"
                accept="application/json,.json"
                hidden
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (!f) return;
                  try {
                    const res = actions.importState(JSON.parse(await f.text()));
                    toast(`Импортировано: проектов — ${res.projects}, идей — ${res.ideas}`);
                  } catch (err) {
                    toast(err instanceof Error ? err.message : "Не удалось прочитать файл", "error");
                  }
                }}
              />
              <button
                className="btn ghost danger"
                onClick={() => {
                  if (confirm("Удалить все проекты, идеи и диалоги и вернуть демо-проект? Действие нельзя отменить.")) {
                    actions.resetAll();
                    toast("Данные сброшены");
                  }
                }}
              >
                Сбросить всё
              </button>
            </div>
          </Card>

          <Card title="О BizForge">
            <p className="small text-2">
              BizForge — лаборатория бизнес-идей: генератор идей, 14-критериальная оценка, Lean Canvas и BMC, расчёт рынка,
              юнит-экономика с анализом чувствительности, помесячная финансовая модель со сценариями, симуляция Монте-Карло,
              реестр рисков, гипотезы и эксперименты, автоматический бизнес-план и ИИ-консультант.
            </p>
            <p className="small text-2" style={{ margin: 0 }}>
              Расчёты — инструмент для размышлений, а не гарантия результата. Проверяйте ключевые допущения на реальных клиентах.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}
