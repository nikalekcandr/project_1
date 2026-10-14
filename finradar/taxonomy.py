"""Rule-based classification: finance/economics/analytics domains, opportunity kind,
seniority, work format, skills and location.

Rules are deliberately transparent (weighted regexes) so that every decision can be
explained and tuned. An optional LLM pass (:mod:`finradar.llm`) can refine them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- domains

DOMAIN_LABELS: dict[str, str] = {
    "corp_finance": "Корпоративные финансы / FP&A / контроллинг",
    "ib_ma": "Инвестбанкинг / M&A / Corporate Development",
    "pe_vc": "Private Equity / венчур / фонды",
    "asset_mgmt": "Управление активами / Research / Wealth",
    "sales_trading": "Рынки / трейдинг / казначейство",
    "quant": "Quant / алготрейдинг",
    "risk": "Риск-менеджмент",
    "credit": "Кредитный анализ / проектное финансирование",
    "accounting_audit": "Учёт / аудит / налоги / МСФО",
    "compliance": "Комплаенс / AML / KYC",
    "economics": "Экономика / макро / исследования",
    "data_analytics": "Аналитика данных / BI / продуктовая аналитика",
    "business_analysis": "Бизнес-анализ / стратегия / консалтинг",
    "fintech_crypto": "Финтех / крипто / платежи",
    "insurance_actuarial": "Страхование / актуарии",
    "other": "Прочее (аналитика общего профиля)",
}

# Short labels for charts, chips and score reasons.
DOMAIN_SHORT: dict[str, str] = {
    "corp_finance": "Корпфинансы / FP&A",
    "ib_ma": "IB / M&A",
    "pe_vc": "PE / VC",
    "asset_mgmt": "Asset mgmt / Research",
    "sales_trading": "Трейдинг / казначейство",
    "quant": "Quant",
    "risk": "Риск-менеджмент",
    "credit": "Кредитный анализ",
    "accounting_audit": "Учёт / аудит / МСФО",
    "compliance": "Комплаенс / AML",
    "economics": "Экономика / макро",
    "data_analytics": "Аналитика данных / BI",
    "business_analysis": "Бизнес-анализ / стратегия",
    "fintech_crypto": "Финтех / крипто",
    "insurance_actuarial": "Страхование / актуарии",
    "other": "Прочая аналитика",
}

_W = r"\w*"
_DOMAIN_RULES: dict[str, list[tuple[str, float]]] = {
    "corp_finance": [
        (r"fp&a|fp & a|financial planning", 3),
        (rf"финансов{_W}\s+аналитик|financial analyst|finance analyst", 3),
        (rf"финансов{_W}\s+менеджер|finance manager|финансист", 2),
        (rf"финансов{_W}\s+директор|финдиректор|\bcfo\b|chief financial", 3),
        (rf"controller|controlling|контролл[еи]{_W}|финансов{_W}\s+контрол", 2),
        (rf"бюджетир{_W}|бюджет{_W}\s+(?:и|планир)|budgeting|forecasting\s+&\s+budget", 2),
        (rf"corporate finance|корпоративн{_W}\s+финанс", 2),
        (rf"планово-экономическ{_W}|\bпэо\b|\bпэу\b", 2),
        (r"экономист", 1.5),
        (rf"управленческ{_W}\s+(?:учет|учёт|отчет|отчёт)|management accounting|management reporting", 2),
        (rf"unit[- ]economics|юнит[- ]экономик{_W}", 1.5),
        (rf"финансов{_W}\s+модел{_W}|financial model{_W}", 1.5),
        (rf"business partner|бизнес-партн[её]р{_W}\s+по\s+финанс", 2),
        (rf"\bp&l\b|\bpnl\b|cash ?flow|денежн{_W}\s+пот[оо]к|capex|opex", 1),
        (rf"\bfinance\b|\bфинанс{_W}", 1),
    ],
    "ib_ma": [
        (r"\bm&a\b|\bm & a\b|mergers|слияни\w*\s+и\s+поглощ", 3),
        (rf"investment bank{_W}|инвестбанк{_W}|инвестиционн{_W}\s+банк{_W}|\bibd\b", 3),
        (rf"\becm\b|\bdcm\b|equity capital markets|debt capital markets|рынк{_W}\s+капитала", 2),
        (rf"corporate development|corp\.? ?dev\b|корпоративн{_W}\s+развити", 2),
        (rf"transaction services|transaction advisory|deal advisory|сопровождени{_W}\s+сдел", 2),
        (rf"valuation|оценк{_W}\s+(?:бизнес|стоимост|компани)|оценщик|отдел{_W}\s+оценк", 1.5),
        (r"due diligence|\blbo\b|pitch ?book|\bdcf\b", 1.5),
        (rf"restructuring|реструктуризац{_W}|\bipo\b|\bspo\b|сделк{_W}", 1),
        (rf"investment analyst|инвестиционн{_W}\s+аналитик", 2),
    ],
    "pe_vc": [
        (rf"private equity|прям{_W}\s+инвестиц{_W}|\bpe fund", 3),
        (rf"venture|венчур{_W}", 3),
        (r"\bvc\b|growth equity|buyout", 2),
        (rf"portfolio compan{_W}|портфельн{_W}\s+компани", 1.5),
        (rf"investment (?:associate|manager|director|professional)|инвестиционн{_W}\s+(?:менеджер|директор)", 2),
        (rf"family office|семейн{_W}\s+офис", 2),
        (rf"fundraising|фандрайз{_W}|\bfund\b|фонд{_W}", 1),
    ],
    "asset_mgmt": [
        (rf"asset management|управлени{_W}\s+активами|управляющ{_W}\s+компани", 3),
        (rf"portfolio manager|портфельн{_W}\s+управляющ|управляющ{_W}\s+портфел", 3),
        (rf"wealth management|private bank{_W}|прайвет[- ]банк{_W}|private banker", 2.5),
        (r"equity research|sell[- ]side|buy[- ]side|hedge fund|хедж[- ]фонд", 3),
        (rf"research analyst|аналитик\s+(?:фондового|финансового)\s+рынка|инвестиционн{_W}\s+стратег{_W}", 2),
        (rf"fixed income|облигаци{_W}|долгов{_W}\s+рынк", 2),
        (rf"\betf\b|mutual fund|\bпиф{_W}|брокер{_W}|brokerage", 1.5),
        (rf"investment (?:strateg{_W}|advis{_W}|research)|инвестиционн{_W}\s+(?:советник|консультант)", 2),
    ],
    "sales_trading": [
        (rf"trader|трейдер{_W}|\btrading\b|трейдинг", 3),
        (r"sales (?:&|and) trading|\bs&t\b|\bficc\b", 3),
        (rf"treasury|казначейств{_W}|казначей", 3),
        (rf"\balm\b|liquidity|ликвидност{_W}", 2),
        (rf"dealer|дилер{_W}|market[- ]mak{_W}|маркет[- ]мейк{_W}", 2),
        (rf"derivatives|дериватив{_W}|производн{_W}\s+финансов|\bfx\b|forex|валютн{_W}\s+рынк", 2),
        (rf"\brepo\b|\bрепо\b|commodit{_W}|сырьев{_W}\s+рынк", 1.5),
    ],
    "quant": [
        (rf"\bquant{_W}|квант{_W}", 3),
        (rf"quantitative|количественн{_W}", 2.5),
        (rf"algo{_W}\s*trading|алготрейд{_W}|algorithmic|\bhft\b|high[- ]frequency|высокочастотн{_W}", 3),
        (rf"stochastic|стохаст{_W}|monte[- ]carlo|option pricing|pricing model{_W}", 1.5),
        (r"statistical arbitrage|stat ?arb|market microstructure|\bxva\b|\bcva\b", 2),
    ],
    "risk": [
        (rf"\brisk{_W}|\bриск{_W}", 2),
        (rf"credit risk|кредитн{_W}\s+риск|market risk|рыночн{_W}\s+риск|operational risk|операционн{_W}\s+риск", 3),
        (rf"риск[- ]менедж{_W}|risk manag{_W}", 3),
        (rf"basel|базел{_W}|\bicaap\b|\bвппда\b|ifrs ?9|мсфо ?(?:\(ifrs\) ?)?9", 2),
        (rf"model validation|валидаци{_W}\s+модел|stress[- ]test{_W}|стресс[- ]тест{_W}|value at risk|\bvar\b", 2),
        (rf"\bpd\b|\blgd\b|\bead\b|скоринг{_W}|scoring|antifraud|антифрод|fraud", 1.5),
    ],
    "credit": [
        (rf"кредитн{_W}\s+аналитик|credit analyst|credit analysis", 3),
        (rf"андеррайт{_W}|underwrit{_W}", 2.5),
        (rf"leveraged finance|lev ?fin|project finance|проектн{_W}\s+финансир{_W}", 3),
        (rf"structured finance|структурн{_W}\s+финанс{_W}|securiti[sz]ation|секьюритизац{_W}|trade finance|торгов{_W}\s+финансир", 2.5),
        (rf"\blending\b|\bloans?\b|кредитован{_W}|кредитн{_W}\s+(?:продукт|портфел|комитет)", 1.5),
        (rf"credit rating|рейтинг{_W}\s+агентств|corporate banking|корпоративн{_W}\s+(?:бизнес|клиент)", 1.5),
    ],
    "accounting_audit": [
        (rf"бухгалтер{_W}|accountant|\baccounting\b|бухуч[её]т|бухгалтерск{_W}", 3),
        (rf"аудит{_W}|audit{_W}", 3),
        (r"мсфо|\bifrs\b|us ?gaap|\bgaap\b", 2),
        (r"рсбу", 1.5),
        (rf"налог{_W}|\btax\b|taxation", 2.5),
        (rf"консолидац{_W}|consolidation|financial reporting|финансов{_W}\s+отч[её]тност", 2),
        (rf"закрыти{_W}\s+период|month[- ]end close|\bsox\b|internal control|внутренн{_W}\s+контрол", 1.5),
        (rf"accounts (?:payable|receivable)|дебиторск{_W}|кредиторск{_W}", 1),
    ],
    "compliance": [
        (r"комплаенс|compliance", 3),
        (r"\baml\b|anti[- ]money laundering|под\s*/\s*фт|115[- ]фз", 3),
        (rf"\bkyc\b|\bkyb\b|санкц{_W}|sanctions|financial crime|fincrime|финансов{_W}\s+мониторинг", 2.5),
        (rf"regulatory reporting|регуляторн{_W}\s+отч[её]т", 1.5),
    ],
    "economics": [
        (r"экономист|economist", 3),
        (rf"макроэконом{_W}|macroeconom{_W}|\bmacro\b|\bмакро\b", 3),
        (rf"эконометр{_W}|econometric{_W}", 3),
        (rf"economic (?:research|analyst|analysis|consulting)|экономическ{_W}\s+(?:исследован|анализ|консалтинг)|research economist", 3),
        (rf"monetary policy|денежно[- ]кредитн{_W}|central bank|центральн{_W}\s+банк|цб рф|банк{_W} россии|\bimf\b|\bмвф\b|world bank|всемирн{_W}\s+банк|\boecd\b|\bоэср\b|\becb\b|\bbis\b|federal reserve", 2),
        (rf"policy analyst|public policy|regulatory economics|competition economics|антимонопольн{_W}", 2),
        (r"development (?:economics|finance)|international development|labou?r economics|health economics|energy economics", 2),
        (rf"think tank|аналитическ{_W}\s+центр|research assistant|научн{_W}\s+сотрудник|исследовател{_W}|researcher", 1.5),
        (rf"economics|экономик{_W}|прогнозир{_W}|statistics|статистик{_W}", 1),
    ],
    "data_analytics": [
        (rf"аналитик\w*\s+данных|data analy{_W}|analytics engineer", 3),
        (rf"\bbi\b|business intelligence|bi[- ]аналитик|bi[- ]разработ{_W}|bi developer|bi analyst", 3),
        (rf"продуктов{_W}\s+аналитик|product analy{_W}", 3),
        (rf"маркетинг{_W}\s+аналитик|marketing analy{_W}|growth analy{_W}|web analy{_W}|веб[- ]аналитик", 2.5),
        (rf"data scien{_W}|дата[- ]сайент{_W}|machine learning|машинн{_W}\s+обучени|\bml\b", 2),
        (r"power ?bi|tableau|qlik|looker|superset|datalens|metabase|\bsql\b", 1),
        (rf"a/b[- ]?тест{_W}|a/b[- ]?test{_W}|experimentation|pricing analy{_W}|аналитик\s+ценообразован{_W}", 1.5),
    ],
    "business_analysis": [
        (r"business analyst|бизнес[- ]аналитик", 3),
        (rf"strateg{_W}|стратег{_W}", 2),
        (rf"management consult{_W}|управленческ{_W}\s+консалтинг|consult{_W}|консалтинг|консультант", 2),
        (rf"market research|исследовани{_W}\s+рынка|маркетинг{_W}\s+исследован{_W}", 2),
        (r"mckinsey|\bbcg\b|\bbain\b|kearney|roland berger|oliver wyman|strategy&", 1.5),
        (rf"commercial (?:finance|analy{_W})|коммерческ{_W}\s+аналитик|revenue (?:analy{_W}|operations)|bizops|business operations|операционн{_W}\s+аналитик", 2.5),
    ],
    "fintech_crypto": [
        (r"fintech|финтех", 2.5),
        (rf"crypto{_W}|крипт{_W}|blockchain|блокчейн|\bdefi\b|web3|digital assets|цифров{_W}\s+актив{_W}|tokeni[sz]{_W}|токениз{_W}", 2.5),
        (rf"payments?\b|платеж{_W}|платёж{_W}|эквайринг|acquiring|neobank|необанк|\bbnpl\b|open banking|\bcbdc\b|цифров{_W}\s+рубл", 1.5),
    ],
    "insurance_actuarial": [
        (rf"актуари{_W}|actuar{_W}", 3),
        (rf"страхов{_W}|insurance|reinsurance|перестрах{_W}", 2.5),
        (rf"solvency|платежеспособност{_W}|\bclaims\b", 1.5),
    ],
}

_GENERIC_ANALYST = re.compile(r"аналитик|analyst|analytics|аналитик[аи]", re.IGNORECASE)

# Titles that look analytical but belong to IT/security or are clearly out of scope.
_NOISE_TITLE = re.compile(
    r"системн\w*\s+аналитик|systems?\s+analyst|soc\s+analyst|security\s+analyst|"
    r"аналитик\w*\s+(?:информационной\s+)?безопасност|\bqa\b|тестировщик|"
    r"1с[- ]?программист|программист\s+1с|frontend|backend|full[- ]?stack|devops|"
    r"(?<!bi )(?<!bi-)developer|(?<!bi[- ])разработчик|software engineer|"
    r"\bводител|\bкурьер|\bкассир|\bпродав[еи]ц|\bгрузчик|\bкладовщик|оператор\s+call|колл[- ]центр|"
    r"менеджер\s+по\s+продажам|sales\s+(?:manager|representative|development)|"
    r"\bмедицинск|\bврач|\bnurse|\bteacher(?!.*econom)",
    re.IGNORECASE,
)

_COMPILED: dict[str, list[tuple[re.Pattern, float]]] = {
    d: [(re.compile(p, re.IGNORECASE), w) for p, w in rules] for d, rules in _DOMAIN_RULES.items()
}

TITLE_WEIGHT = 3.0
TAG_WEIGHT = 2.0
BODY_WEIGHT = 1.0
DOMAIN_THRESHOLD = 3.0


@dataclass
class Classification:
    domains: list[str]
    primary_domain: str | None
    relevance: float
    scores: dict[str, float]


def classify_domains(title: str, description: str = "", tags: list[str] | None = None) -> Classification:
    title = title or ""
    body = (description or "")[:6000]
    tag_text = " ".join(tags or [])
    scores: dict[str, float] = {}
    for domain, rules in _COMPILED.items():
        score = 0.0
        for rx, w in rules:
            if rx.search(title):
                score += w * TITLE_WEIGHT
            elif tag_text and rx.search(tag_text):
                score += w * TAG_WEIGHT
            elif body and rx.search(body):
                score += w * BODY_WEIGHT
        if score:
            scores[domain] = round(score, 2)

    relevance = max(scores.values(), default=0.0)
    if _GENERIC_ANALYST.search(title):
        relevance = max(relevance, DOMAIN_THRESHOLD)
    if _NOISE_TITLE.search(title):
        title_hits = sum(1 for rules in _COMPILED.values() for rx, w in rules if w >= 2.5 and rx.search(title))
        if not title_hits:
            relevance = min(relevance, 1.0)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    domains = [d for d, s in ranked if s >= DOMAIN_THRESHOLD][:4]
    primary = domains[0] if domains else ("other" if relevance >= DOMAIN_THRESHOLD else None)
    return Classification(domains=domains, primary_domain=primary, relevance=round(relevance, 2), scores=scores)


# --------------------------------------------------------------------------- kind

_KIND_RULES: list[tuple[str, re.Pattern, bool]] = [
    # (kind, pattern, title_only)
    ("event", re.compile(r"\bconference\b|конференц\w*|\bwebinar\b|вебинар|\bmeetup\b|митап|\bsummit\b|саммит|career day|день карьеры|ярмарк\w*\s+ваканс", re.I), True),
    ("competition", re.compile(r"case (?:championship|competition|challenge)|кейс[- ]чемпионат|чемпионат|олимпиад\w*|hackathon|хакатон|\bконкурс\w*|competition", re.I), True),
    ("grant", re.compile(r"\bgrants?\b|\bгрант\w*|scholarship|стипенди\w*|funding call", re.I), True),
    ("fellowship", re.compile(r"fellowship|\bfellow\b|young professionals? program", re.I), True),
    ("academic", re.compile(r"\bph\.?d\b|аспирант\w*|post[- ]?doc|постдок|assistant professor|associate professor|\blecturer\b|профессор|преподавател\w*|faculty position|tenure[- ]track", re.I), True),
    ("graduate_program", re.compile(r"graduate (?:program\w*|scheme|programme)|программ\w*\s+(?:для\s+)?выпускник\w*|management trainee|rotation(?:al)? program\w*|ротационн\w*\s+программ", re.I), True),
    ("internship", re.compile(r"стажир\w*|стаж[её]р\w*|internship|\bintern\b|summer analyst|spring (?:week|insight)|off[- ]cycle|insight (?:day|program)|практикант|trainee", re.I), False),
]


def classify_kind(title: str, description: str = "", employment: str | None = None, tags: list[str] | None = None) -> str:
    title = title or ""
    tag_text = " ".join(tags or [])
    for kind, rx, title_only in _KIND_RULES:
        if rx.search(title):
            return kind
        if not title_only and (rx.search(tag_text) or (employment and rx.search(employment))):
            return kind
    if employment and employment.lower() in {"internship", "intern", "стажировка"}:
        return "internship"
    return "vacancy"


# --------------------------------------------------------------------------- seniority

_SENIORITY_TITLE: list[tuple[str, re.Pattern]] = [
    ("c_level", re.compile(r"\bcfo\b|\bceo\b|\bcoo\b|\bcro\b|\bcio\b|\bchief\b|финансов\w*\s+директор|финдиректор|генеральн\w*\s+директор", re.I)),
    ("head", re.compile(r"head of|\bhead\b|руководител[ьяю](?!\s+групп)|начальник\w*|директор\w*|director|managing director|\bmd\b|\bpartner\b|партн[её]р", re.I)),
    ("lead", re.compile(r"\blead\b|\bлид\b|тимлид|team ?lead|principal|руководител\w*\s+групп\w*|vice president|\bvp\b|\bsvp\b|вице[- ]президент", re.I)),
    ("intern", re.compile(r"стажер|стажёр|стажир\w*|\bintern\b|internship|trainee|summer analyst|практикант|студент|student", re.I)),
    ("junior", re.compile(r"junior|младш\w*|начинающ\w*|entry[- ]level|\bgraduate\b|выпускник\w*|\bjr\b\.?|без опыта", re.I)),
    ("senior", re.compile(r"senior|старш\w*|ведущ\w*|главн\w*\s+(?:специалист|аналитик|экономист|эксперт)|\bsr\b\.?|эксперт", re.I)),
    ("middle", re.compile(r"middle|mid[- ]level|\bmid\b", re.I)),
]
_ASSOCIATE = re.compile(r"\bassociate\b", re.I)
_EXP_YEARS = re.compile(
    r"(?:опыт\w*[^.\n]{0,40}?(?:от|не менее|более|>)\s*(\d{1,2})(?:[,.]\d)?\s*(?:-|–|до)?\s*\d{0,2}\s*(?:лет|год))"
    r"|(?:(\d{1,2})\+?\s*(?:-\s*\d{1,2}\s*)?years?(?:'|’)?\s*(?:of\s+)?(?:relevant\s+|professional\s+|work\s+)?experience)",
    re.I,
)
_HH_EXPERIENCE = {"noExperience": "junior", "between1And3": "junior", "between3And6": "middle", "moreThan6": "senior"}
# Level labels used by international APIs (The Muse, SmartRecruiters, Himalayas, Jobicy, ReliefWeb).
_HINT_WORDS = [
    ("intern", "intern"), ("executive", "c_level"), ("director", "head"), ("management", "head"),
    ("mid-senior", "senior"), ("senior", "senior"), ("mid", "middle"), ("associate", "junior"),
    ("entry", "junior"), ("junior", "junior"), ("0-2", "junior"), ("3-4", "middle"), ("5-9", "senior"),
    ("10+", "head"), ("без опыта", "junior"), ("от 1", "junior"), ("от 3", "middle"), ("от 6", "senior"),
]


def classify_seniority(title: str, description: str = "", hint: str | None = None, domains: list[str] | None = None) -> str | None:
    title = title or ""
    for level, rx in _SENIORITY_TITLE:
        if rx.search(title):
            return level
    if _ASSOCIATE.search(title):
        return "middle" if set(domains or []) & {"ib_ma", "pe_vc", "asset_mgmt", "business_analysis"} else "junior"
    if hint:
        if hint in _HH_EXPERIENCE:
            return _HH_EXPERIENCE[hint]
        low = hint.lower()
        for marker, level in _HINT_WORDS:
            if marker in low:
                return level
        for level, rx in _SENIORITY_TITLE:
            if rx.search(hint):
                return level
    m = _EXP_YEARS.search(description or "")
    if m:
        years = int(m.group(1) or m.group(2))
        if years >= 6:
            return "senior"
        if years >= 3:
            return "middle"
        return "junior"
    return None


# --------------------------------------------------------------------------- work format

_REMOTE = re.compile(r"удал[её]нн?\w*|удаленк\w*|\bremote\b|дистанц\w*|из дома|work from home|\bwfh\b|anywhere|fully distributed|telecommut\w*", re.I)
_HYBRID = re.compile(r"гибрид\w*|hybrid|частично удал\w*", re.I)
_OFFICE = re.compile(r"в офисе|\bофис\b|on[- ]?site|in[- ]office|office[- ]based", re.I)


def classify_work_format(*texts: str | None) -> str | None:
    joined = " \n ".join(t for t in texts if t)
    if not joined:
        return None
    if _HYBRID.search(joined):
        return "hybrid"
    remote = _REMOTE.search(joined)
    office = _OFFICE.search(joined)
    if remote and office:
        return "hybrid"
    if remote:
        return "remote"
    if office:
        return "office"
    return None


# --------------------------------------------------------------------------- skills

SKILLS: dict[str, str] = {
    "Excel": r"\bexcel\b|эксел\w*|ms office",
    "VBA": r"\bvba\b|макрос\w*",
    "SQL": r"\bsql\b|postgres\w*|clickhouse|mysql|oracle sql|t-sql",
    "Python": r"\bpython\b|pandas|numpy|питон",
    "R": r"(?<![\w-])r(?:\s*\(|/python|,\s*python| studio|studio)|\br language\b|\brstudio\b",
    "Power BI": r"power ?bi",
    "Tableau": r"tableau",
    "Qlik": r"qlik",
    "Looker/DataLens/Superset": r"looker|datalens|superset|metabase",
    "SAS": r"\bsas\b",
    "Stata": r"\bstata\b",
    "EViews": r"eviews",
    "MATLAB": r"matlab",
    "1С": r"\b1[сc]\b|1[сc]:",
    "SAP": r"\bsap\b",
    "Oracle/Hyperion": r"hyperion|oracle (?:epm|fusion)|anaplan|onestream",
    "Bloomberg": r"bloomberg",
    "Refinitiv/LSEG": r"refinitiv|eikon|\blseg\b|reuters",
    "Capital IQ / FactSet / PitchBook": r"capital ?iq|factset|pitchbook|preqin",
    "Финансовое моделирование": r"финансов\w*\s+модел\w*|financial model\w*|three[- ]statement|3[- ]statement",
    "DCF / оценка": r"\bdcf\b|valuation|оценк\w*\s+(?:бизнес|стоимост|компани)|discounted cash",
    "LBO": r"\blbo\b|leveraged buyout",
    "МСФО / IFRS": r"мсфо|\bifrs\b",
    "US GAAP": r"us ?gaap",
    "РСБУ": r"рсбу",
    "Бюджетирование": r"бюджетир\w*|budgeting",
    "Эконометрика": r"эконометр\w*|econometric\w*",
    "Статистика": r"статистик\w*|statistic\w*",
    "Machine Learning": r"machine learning|машинн\w*\s+обучени\w*|\bml\b|scikit|xgboost|catboost",
    "A/B-тесты": r"a/b|ab[- ]тест\w*|experimentation",
    "Airflow/dbt/Spark": r"airflow|\bdbt\b|spark|hadoop",
    "CFA": r"\bcfa\b",
    "ACCA": r"\bacca\b",
    "CPA": r"\bcpa\b",
    "FRM/PRM": r"\bfrm\b|\bprm\b",
    "CIMA": r"\bcima\b",
    "Basel / IFRS 9": r"basel|базел\w*|ifrs ?9|мсфо ?9",
    "Английский язык": r"английск\w*|\benglish\b|upper[- ]intermediate|advanced english|fluent english|\bb2\b|\bc1\b",
    "C++": r"c\+\+",
    "Java/C#": r"\bjava\b|\bc#",
}
_SKILL_RES = {name: re.compile(p, re.IGNORECASE) for name, p in SKILLS.items()}


def extract_skills(*texts: str | None, extra: list[str] | None = None) -> list[str]:
    joined = " \n ".join(t for t in texts if t)
    found = [name for name, rx in _SKILL_RES.items() if rx.search(joined)]
    for item in extra or []:
        for name, rx in _SKILL_RES.items():
            if rx.search(item) and name not in found:
                found.append(name)
    return found


# --------------------------------------------------------------------------- location

_CITIES: list[tuple[str, str, str]] = [
    # (pattern, canonical city, country)
    (r"москв\w*|moscow|\bмск\b", "Москва", "Россия"),
    (r"санкт[- ]петербург\w*|петербург\w*|\bспб\b|st\.? ?petersburg|saint petersburg", "Санкт-Петербург", "Россия"),
    (r"новосибирск\w*|novosibirsk", "Новосибирск", "Россия"),
    (r"екатеринбург\w*|yekaterinburg|ekaterinburg", "Екатеринбург", "Россия"),
    (r"казан[ьи]\b|kazan\b", "Казань", "Россия"),
    (r"нижн\w*\s+новгород\w*|nizhny novgorod", "Нижний Новгород", "Россия"),
    (r"краснодар\w*|krasnodar", "Краснодар", "Россия"),
    (r"самар[аеы]\b|samara", "Самара", "Россия"),
    (r"ростов\w*[- ]на[- ]дону|rostov", "Ростов-на-Дону", "Россия"),
    (r"\bперм[ьи]\b|\bperm\b", "Пермь", "Россия"),
    (r"\bуф[аеы]\b|\bufa\b", "Уфа", "Россия"),
    (r"тюмен\w*|tyumen", "Тюмень", "Россия"),
    (r"иннополис|innopolis", "Иннополис", "Россия"),
    (r"минск\w*|minsk", "Минск", "Беларусь"),
    (r"алмат\w*|almaty", "Алматы", "Казахстан"),
    (r"астан\w*|astana", "Астана", "Казахстан"),
    (r"ташкент\w*|tashkent", "Ташкент", "Узбекистан"),
    (r"ереван\w*|yerevan", "Ереван", "Армения"),
    (r"тбилиси|tbilisi", "Тбилиси", "Грузия"),
    (r"баку\b|\bbaku\b", "Баку", "Азербайджан"),
    (r"белград\w*|belgrade", "Белград", "Сербия"),
    (r"лимасол\w*|limassol", "Лимасол", "Кипр"),
    (r"стамбул\w*|istanbul", "Стамбул", "Турция"),
    (r"дуба[ий]\w*|dubai", "Дубай", "ОАЭ"),
    (r"абу[- ]даби|abu dhabi", "Абу-Даби", "ОАЭ"),
    (r"\bdoha\b|доха", "Доха", "Катар"),
    (r"riyadh|эр[- ]рияд", "Эр-Рияд", "Саудовская Аравия"),
    (r"лондон\w*|london", "Лондон", "Великобритания"),
    (r"new york|\bnyc\b|нью[- ]йорк\w*", "Нью-Йорк", "США"),
    (r"chicago|чикаго", "Чикаго", "США"),
    (r"boston|бостон", "Бостон", "США"),
    (r"san francisco|сан[- ]франциско|bay area", "Сан-Франциско", "США"),
    (r"washington,? d\.?c|вашингтон", "Вашингтон", "США"),
    (r"toronto|торонто", "Торонто", "Канада"),
    (r"singapore|сингапур\w*", "Сингапур", "Сингапур"),
    (r"hong kong|гонконг\w*", "Гонконг", "Китай"),
    (r"shanghai|шанха\w*", "Шанхай", "Китай"),
    (r"tokyo|токио", "Токио", "Япония"),
    (r"frankfurt|франкфурт\w*", "Франкфурт", "Германия"),
    (r"berlin|берлин\w*", "Берлин", "Германия"),
    (r"munich|münchen|мюнхен\w*", "Мюнхен", "Германия"),
    (r"paris|париж\w*", "Париж", "Франция"),
    (r"amsterdam|амстердам\w*", "Амстердам", "Нидерланды"),
    (r"z[uü]rich|цюрих\w*", "Цюрих", "Швейцария"),
    (r"geneva|genève|женев\w*", "Женева", "Швейцария"),
    (r"luxembourg|люксембург\w*", "Люксембург", "Люксембург"),
    (r"dublin|дублин\w*", "Дублин", "Ирландия"),
    (r"warsaw|варшав\w*", "Варшава", "Польша"),
    (r"madrid|мадрид\w*", "Мадрид", "Испания"),
    (r"milan|милан\w*", "Милан", "Италия"),
    (r"sydney|сидне\w*", "Сидней", "Австралия"),
]
_CITY_RES = [(re.compile(p, re.IGNORECASE), c, k) for p, c, k in _CITIES]

_COUNTRIES: list[tuple[str, str]] = [
    (r"росси\w*|russia|\bрф\b", "Россия"),
    (r"казахстан\w*|kazakhstan", "Казахстан"),
    (r"беларус\w*|belarus", "Беларусь"),
    (r"узбекистан\w*|uzbekistan", "Узбекистан"),
    (r"армени\w*|armenia", "Армения"),
    (r"грузи[яи]\w*|georgia(?!\s*,?\s*(?:usa|us|atlanta))", "Грузия"),
    (r"сербия|serbia", "Сербия"),
    (r"кипр\w*|cyprus", "Кипр"),
    (r"оаэ|\buae\b|united arab emirates|эмират\w*", "ОАЭ"),
    (r"united kingdom|\buk\b|england|великобритан\w*|англи[яи]", "Великобритания"),
    (r"united states|\busa\b|\bu\.s\.|сша", "США"),
    (r"germany|германи\w*", "Германия"),
    (r"switzerland|швейцари\w*", "Швейцария"),
    (r"netherlands|нидерланд\w*", "Нидерланды"),
    (r"canada|канад\w*", "Канада"),
    (r"turkey|türkiye|турци\w*", "Турция"),
]
_COUNTRY_RES = [(re.compile(p, re.IGNORECASE), c) for p, c in _COUNTRIES]


def resolve_location(location: str | None, *fallback_texts: str | None) -> tuple[str | None, str | None]:
    """Return (city, country) from a location string, falling back to other text."""
    for text in (location, *fallback_texts):
        if not text:
            continue
        sample = text[:600]
        for rx, city, country in _CITY_RES:
            if rx.search(sample):
                return city, country
        for rx, country in _COUNTRY_RES:
            if rx.search(sample):
                return None, country
    return None, None
