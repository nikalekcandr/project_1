import pytest

from finradar.taxonomy import (
    classify_domains,
    classify_kind,
    classify_seniority,
    classify_work_format,
    extract_skills,
    resolve_location,
)


@pytest.mark.parametrize(
    "title, domain",
    [
        ("Финансовый аналитик (FP&A)", "corp_finance"),
        ("Senior Analyst, Investment Banking (M&A)", "ib_ma"),
        ("Associate, Private Equity", "pe_vc"),
        ("Economist, Monetary Policy", "economics"),
        ("Quantitative Researcher", "quant"),
        ("Risk Manager, Market Risk", "risk"),
        ("Credit Analyst, Leveraged Finance", "credit"),
        ("Аналитик данных", "data_analytics"),
        ("Treasury Analyst", "sales_trading"),
        ("Руководитель группы бюджетирования", "corp_finance"),
        ("Актуарий", "insurance_actuarial"),
        ("Специалист по комплаенсу (AML)", "compliance"),
    ],
)
def test_domains(title, domain):
    c = classify_domains(title)
    assert c.primary_domain == domain
    assert c.relevance >= 3


@pytest.mark.parametrize(
    "title",
    ["Системный аналитик", "Водитель", "Senior Software Engineer", "Продавец-кассир", "Software Engineer, Payments"],
)
def test_out_of_scope(title):
    assert classify_domains(title).relevance < 3


def test_generic_analyst_is_kept_as_other():
    c = classify_domains("Analyst")
    assert c.relevance >= 3 and c.primary_domain == "other"


def test_description_contributes():
    c = classify_domains("Аналитик", "Построение финансовых моделей, DCF, сопровождение сделок M&A")
    assert c.primary_domain == "ib_ma"


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Head of FP&A", "head"),
        ("Руководитель группы бюджетирования", "lead"),
        ("Руководитель отдела аналитики", "head"),
        ("CFO", "c_level"),
        ("Финансовый директор", "c_level"),
        ("Стажер в отдел оценки", "intern"),
        ("Junior аналитик", "junior"),
        ("Ведущий экономист", "senior"),
        ("Vice President, Credit", "lead"),
    ],
)
def test_seniority_from_title(title, expected):
    assert classify_seniority(title) == expected


def test_seniority_from_experience_and_associate():
    assert classify_seniority("Аналитик", "Опыт работы от 5 лет в банке") == "middle"
    assert classify_seniority("Analyst", "7+ years of experience in credit") == "senior"
    assert classify_seniority("Associate", domains=["pe_vc"]) == "middle"
    assert classify_seniority("Associate", domains=["data_analytics"]) == "junior"
    assert classify_seniority("Аналитик", hint="between3And6") == "middle"
    assert classify_seniority("Analyst", hint="Mid-Senior Level") == "senior"
    assert classify_seniority("Analyst", hint="Entry Level") == "junior"
    assert classify_seniority("Analyst", hint="middle") == "middle"
    assert classify_seniority("Analyst", hint="lead") == "lead"
    assert classify_seniority("Экономист", hint="От 1 года") == "junior"


@pytest.mark.parametrize(
    "title, kind",
    [
        ("Summer Analyst Internship 2027", "internship"),
        ("Стажировка в отделе M&A", "internship"),
        ("Graduate Programme — Global Markets", "graduate_program"),
        ("Research Fellowship in Macroeconomics", "fellowship"),
        ("Кейс-чемпионат по корпоративным финансам", "competition"),
        ("PhD position in Financial Economics", "academic"),
        ("Грант на исследование рынка труда", "grant"),
        ("Financial Analyst", "vacancy"),
    ],
)
def test_kind(title, kind):
    assert classify_kind(title) == kind


def test_work_format_and_skills_and_location():
    assert classify_work_format("Аналитик", "Москва", "Гибридный формат: 2 дня в офисе") == "hybrid"
    assert classify_work_format("Remote analyst") == "remote"
    assert classify_work_format("Работа в офисе м. Белорусская") == "office"
    skills = extract_skills("Нужны Excel, SQL, Power BI, финансовое моделирование, МСФО и CFA level II")
    assert {"Excel", "SQL", "Power BI", "Финансовое моделирование", "МСФО / IFRS", "CFA"} <= set(skills)
    assert resolve_location("г. Москва, м. Сити") == ("Москва", "Россия")
    assert resolve_location("London, United Kingdom") == ("Лондон", "Великобритания")
    assert resolve_location("Remote — Kazakhstan") == (None, "Казахстан")
