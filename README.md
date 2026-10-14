# FinRadar

Агрегатор вакансий и карьерных возможностей в **финансах, экономике и аналитике**: Россия и СНГ плюс глобальный рынок. Собирает позиции из 26 типов источников, схлопывает кросспостинг, нормализует зарплаты, классифицирует по 15 финансовым направлениям, ранжирует под ваш профиль и строит аналитику рынка.

> Аналитическая записка о том, какие источники есть, как к ним подключаться и что из этого считать: **[docs/ANALYSIS.md](docs/ANALYSIS.md)**.

## Что умеет

- **Источники.** Подробная карта — в [docs/ANALYSIS.md](docs/ANALYSIS.md#2-карта-источников).
  - Россия и СНГ: hh.ru (API с токеном или вежливый HTML-режим после закрытия публичного API в 2026), Habr Career, GetMatch, Perforum (сайт и @Perforum_jobs), FinExecutive (сайт и @finexecutive), профильные Telegram-каналы, SuperJob, «Работа России».
  - Мир: карьерные сайты работодателей через ATS (Greenhouse, Lever, Ashby, SmartRecruiters, Workday — банки, фонды, трейдинговые фирмы, финтех), Remotive, RemoteOK, Himalayas, Jobicy, The Muse, Arbeitnow, Adzuna, Reed, Jooble, USAJOBS, ReliefWeb.
  - Закрытые платформы (LinkedIn, Indeed, eFinancialCareers, Glassdoor) — через ваши e-mail-алерты (IMAP).
  - Любой сайт без кода: RSS/Atom, краулер schema.org `JobPosting`, CSS-шаблоны листингов.
- **Обработка.**
  - Парсер зарплат RU/EN: «300–400к», «$120k–150k», gross/net, год/месяц/час. Пересчёт в два сопоставимых рынка: ₽/мес на руки и USD/год gross, по курсам ЦБ РФ.
  - Классификация: направление, тип возможности (вакансия, стажировка, fellowship, грант, кейс-чемпионат…), уровень, формат работы, навыки, город.
  - Кросс-источниковая дедупликация, история изменений (например, подняли вилку), закрытие исчезнувших позиций.
- **Персональный скоринг 0–100** по `config/profile.yaml` с объяснением причин. Опционально — fit к вашему резюме через Claude (`finradar enrich`).
- **Аналитика:** индекс «горячести» направлений, недельные тренды, зарплатные бенчмарки и карта «направление × уровень», премия за навыки, импульс работодателей, время жизни вакансий, качество и эксклюзивность источников.
- **Выдача:** самодостаточный HTML-отчёт (графики, фильтры, поиск, светлая и тёмная тема, работает офлайн), дайджест в Telegram, CLI-поиск, экспорт в CSV/JSON.

## Быстрый старт

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # или pip install -e ".[llm]" для finradar enrich

finradar init               # создаст config/sources.yaml, config/profile.yaml, config/resume.txt, .env
# отредактируйте config/profile.yaml (направления, ключевые слова, уровень, зарплата, города)

finradar doctor             # живая проверка каждого источника из вашей сети (по 5 позиций, без записи)
finradar fetch              # сбор (источники работают параллельно)
finradar top                # лучшие совпадения за 7 дней
finradar report             # reports/index.html — аналитика и фильтруемый список
finradar digest --send      # дайджест новых позиций в Telegram (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID в .env)
```

## Команды

| Команда | Что делает |
|---|---|
| `init` | создаёт конфиги из примеров |
| `doctor [-s NAME] [--all]` | проверяет источники вживую и показывает пример или ошибку |
| `fetch [-s NAME] [--dry-run]` | собирает, обогащает, дедуплицирует, скорит |
| `sources` | статус последнего запуска каждого источника |
| `top [--days N] [--kind internship]` | лучшие совпадения с профилем |
| `search "запрос" [--domain ib_ma] [--remote] [--min-salary 250000]` | полнотекстовый поиск (SQLite FTS5) |
| `show <uid>` | карточка: дубли в других источниках, история изменений, LLM-разбор |
| `stats` | аналитика рынка в терминале |
| `report [-o file.html]` | HTML-отчёт |
| `digest [--days 1] [--min-score 40] [--send]` | дайджест (Markdown или Telegram) |
| `export -f csv\|json\|jsonl` | выгрузка |
| `enrich [--limit N]` | LLM-обогащение и fit к резюме (Claude, опционально) |
| `rescore` | пересчёт дедупликации и скоринга после правки профиля |

## Добавить источник без кода

```yaml
# config/sources.yaml
- name: my_channels
  type: telegram
  channels: [some_finance_jobs_channel]

- name: bank_careers                    # любой сайт со schema.org JobPosting
  type: jsonld_crawler
  start_urls: ["https://example-bank.ru/careers/vacancies"]
  link_pattern: "/vacancies/[^/?#]+/?$"

- name: target_funds                    # работодатели на Greenhouse
  type: greenhouse
  companies: [point72, jumptrading]
```

Как найти ATS работодателя по ссылке «Apply», описано в [docs/ANALYSIS.md](docs/ANALYSIS.md#23-как-найти-ats-работодателя). Новый тип коннектора — это класс-наследник `Source` с декоратором `@register("type")` в `finradar/sources/`.

## Расписание

- **Свой сервер или домашний компьютер** (лучший вариант для российских сайтов):
  ```cron
  17 */6 * * *  cd /path/to/project_1 && .venv/bin/finradar fetch >> data/cron.log 2>&1
  30 9 * * *    cd /path/to/project_1 && .venv/bin/finradar digest --send && .venv/bin/finradar report
  ```
- **GitHub Actions**: `.github/workflows/finradar.yml` — каждые 6 часов. База хранится в кеше, отчёт сохраняется артефактом, дайджест отправляется при заданных секретах. Раннеры находятся вне РФ, поэтому часть российских сайтов может блокировать запросы; для них используйте self-hosted runner.

## Структура

```
finradar/
  sources/        коннекторы: hh, habr, getmatch, telegram, ats, boards, keyed, generic, email_alerts
  salary.py       парсинг и нормализация зарплат
  taxonomy.py     направления, тип, уровень, формат, навыки, локации
  enrich.py       обогащение одной позиции
  dedup.py        кросс-источниковая дедупликация
  scoring.py      персональный скоринг
  storage.py      SQLite + FTS5, история изменений, запуски
  pipeline.py     оркестрация сбора
  analytics.py    метрики рынка
  report.py, templates/report.html.j2   HTML-отчёт
  digest.py, notify.py                  дайджест и Telegram
  llm.py          опциональный проход Claude
  cli.py
config/           примеры sources.yaml, profile.yaml, resume.txt
docs/ANALYSIS.md  аналитическая записка
tests/            84 теста на фикстурах + сквозной прогон
```

## Тесты

```bash
pip install -e ".[dev]" && pytest
```

## Этика и ограничения

Используются официальные API, публичные ленты и ваши собственные почтовые алерты. HTML-сбор уважает robots.txt и лимиты частоты, при капче источник останавливается (обхода нет). HTML-режим hh.ru рассчитан на личное некоммерческое использование. Подробности — в [docs/ANALYSIS.md](docs/ANALYSIS.md#3-правовые-и-этические-рамки).

Коннекторы проверены на фикстурах в формате ответов источников. Живые запросы нужно подтвердить командой `finradar doctor` из вашей сети: у perforum.io, finexecutive.com, внутренней ленты GetMatch и JSON Habr Career формат может отличаться, и тогда достаточно поправить `link_pattern` или селекторы в YAML.
