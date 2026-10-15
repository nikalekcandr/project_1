"""HTML-отчёт по сделке — самодостаточный файл (стили, графики, скрипты внутри).

Состав отчёта (по ТЗ): описание инструмента и экономического назначения;
источник каждого рыночного входа со временем; справедливая стоимость по
модели; разложение цены по компонентам; цена ванильной альтернативы с тем
же назначением; совмещённый график выплат с отметкой зоны, где структура
перестаёт защищать; чувствительности; CVA с указанием метода прокси.
Плюс: сценарии и стрессы, проверки модели, кривые, QC, МСФО 9, поля НРД,
аудиторский след.
"""
from __future__ import annotations

import json
import math
from typing import Any

from ..core.provenance import DataKind
from .svg import column_chart, diverging_cell, esc, fmt_num, hbar_chart, line_chart

KIND_BADGE = {
    "market": ("рынок", "b-ok"), "derived": ("из рынка", "b-ok"), "interpolated": ("интерполяция", "b-info"),
    "extrapolated": ("экстраполяция", "b-warn"), "historical": ("историческая", "b-warn"), "model": ("модель", "b-warn"),
    "termsheet": ("термшит", "b-info"), "demo": ("ДЕМО", "b-crit"),
}


class Raw(str):
    """Ячейка с готовой разметкой (не экранируется)."""


def _badge(kind: str) -> str:
    lab, cls = KIND_BADGE.get(kind, (kind, "b-info"))
    return f'<span class="badge {cls}">{esc(lab)}</span>'


def _rub(v: float | None) -> str:
    return "—" if v is None else f"{fmt_num(v)} ₽"


def _num_cell(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f'<td class="num">{esc(fmt_num(float(v)))}</td>'
    return f"<td>{esc(v)}</td>"


def _table(headers: list[str], rows: list[list[Any]], cls: str = "") -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for r in rows:
        tds = []
        for c in r:
            if isinstance(c, str) and c.startswith("<td"):
                tds.append(c)
            elif isinstance(c, Raw):
                tds.append(f"<td>{c}</td>")
            elif isinstance(c, (int, float)) and not isinstance(c, bool):
                tds.append(_num_cell(c))
            else:
                tds.append(f"<td>{c if (isinstance(c, str) and c.startswith('<')) else esc('' if c is None else c)}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="tbl-wrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def _section(sid: str, title: str, body: str, lead: str = "", open_: bool = True) -> str:
    lead_html = f'<p class="lead">{lead}</p>' if lead else ""
    return (f'<section id="{sid}"><details {"open" if open_ else ""}><summary><h2>{esc(title)}</h2></summary>'
            f'{lead_html}{body}</details></section>')


def _cfo_summary(v) -> list[str]:
    p = v.pricing
    b = v.breakdown
    out = []
    notional = b.notional_ref if b else 0
    pct = f" ({p.value / notional:+.2%} номинала)" if notional else ""
    who = "в пользу компании" if p.value > 0 else "в пользу банка"
    out.append(f"Справедливая стоимость структуры для компании по рыночной модели: <b>{_rub(p.value)}</b>{pct} — {who}.")
    if b is not None:
        if b.transfer > 0:
            out.append(f"Компания передаёт банку стоимость <b>{_rub(b.transfer)}</b>. Обосновано рыночными издержками: "
                       f"хеджирование {_rub(b.hedge_cost)}, модельная неопределённость {_rub(b.model_reserve)}, "
                       f"кредитный риск компании {_rub(b.credit)}, капитал и фондирование {_rub(b.capital + b.funding)}.")
            if b.residual > 0:
                out.append(f"<b>Необоснованный остаток (наценка): {_rub(b.residual)}</b>"
                           + (f" ≈ {b.residual_bp_pa:,.0f} б.п. годовых на номинал." if math.isfinite(b.residual_bp_pa) else "."))
            else:
                out.append("Обоснованные издержки покрывают передачу стоимости: явной сверхнаценки не выявлено.")
        else:
            out.append("По mid-оценке структура не переносит стоимость к банку.")
    if v.alternatives:
        for a in v.alternatives:
            out.append(f"Альтернатива «{esc(a['label'])}»: стоимость для компании {_rub(a['value'])} — {esc(a['description'])}.")
    if v.profile is not None:
        for s in v.profile.summary:
            out.append(esc(s) + ".")
    if p.measure == "historical":
        out.append("<b>Внимание:</b> у базиса нет торгуемого хеджа — оценка выполнена в исторической (актуарной) мере.")
    mb = p.model_based_inputs
    if mb:
        out.append(f"Оценка опирается на модельные (не рыночные) входы: {len(mb)} шт. — см. раздел «Рыночные входы».")
    return out


CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--card:#ffffff;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;--line:#e4e3df;--grid:#ecebe7;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#6250d6;--ok:#0ca30c;--warn:#fab219;--serious:#ec835a;--crit:#d03b3b;
--div-pos:#2a78d6;--div-neg:#e34948;--div-mid:#f0efec;--zone-crit:rgba(208,59,59,.10);--zone-warn:rgba(236,131,90,.12);--accent-bg:#eef4fc}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#1a1a19;--card:#222220;--text:#f0efec;--text2:#c3c2b7;--muted:#9a998f;
--line:#383835;--grid:#2e2e2b;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#9085e9;--div-pos:#3987e5;--div-neg:#e66767;--div-mid:#383835;
--zone-crit:rgba(208,59,59,.20);--zone-warn:rgba(236,131,90,.18);--accent-bg:#1d2a3a}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--card:#222220;--text:#f0efec;--text2:#c3c2b7;--muted:#9a998f;--line:#383835;--grid:#2e2e2b;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#9085e9;--div-pos:#3987e5;--div-neg:#e66767;--div-mid:#383835;
--zone-crit:rgba(208,59,59,.20);--zone-warn:rgba(236,131,90,.18);--accent-bg:#1d2a3a}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
header.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
h1{font-size:26px;line-height:1.25;margin:0 0 6px}h2{font-size:19px;margin:0}h3{font-size:16px;margin:22px 0 8px}
.meta{color:var(--text2);font-size:13px}.muted{color:var(--muted)}
.demo{border:1px solid var(--crit);background:var(--zone-crit);border-radius:10px;padding:10px 14px;margin:16px 0;font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile .l{color:var(--text2);font-size:13px}.tile .v{font-size:24px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}
.tile .d{color:var(--muted);font-size:12px}.tile.hero .v{font-size:34px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:16px 0;padding:6px 18px 14px}
summary{cursor:pointer;list-style:none;padding:10px 0}summary::-webkit-details-marker{display:none}
summary h2::before{content:"▸";display:inline-block;width:18px;color:var(--muted);transition:transform .15s}
details[open] summary h2::before{transform:rotate(90deg)}
.lead{color:var(--text2);margin:0 0 12px}
ul.cfo{margin:6px 0 4px 0;padding-left:20px}ul.cfo li{margin:6px 0}
.tbl-wrap{overflow-x:auto;margin:8px 0}table{border-collapse:collapse;width:100%;font-size:13.5px}
th{text-align:left;color:var(--text2);font-weight:600;border-bottom:1px solid var(--line);padding:7px 8px;white-space:nowrap}
td{border-bottom:1px solid var(--grid);padding:6px 8px;vertical-align:top}td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.hl td{background:var(--accent-bg)}
.badge{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.b-ok{color:var(--text2)}.b-info{color:var(--text2);border-style:dashed}.b-warn{border-color:var(--serious);color:var(--text)}
.b-warn::before{content:"▲ ";color:var(--serious)}.b-crit{border-color:var(--crit);color:var(--text)}.b-crit::before{content:"● ";color:var(--crit)}
.ok::before{content:"✓ ";color:var(--ok);font-weight:700}.fail::before{content:"✕ ";color:var(--crit);font-weight:700}
.warnbox{border-left:3px solid var(--serious);background:var(--zone-warn);padding:8px 12px;border-radius:6px;margin:8px 0}
.fig{margin:10px 0 6px}.chart-wrap{position:relative}.chart{width:100%;height:auto;display:block;overflow:visible}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--text2);margin-bottom:4px}
.lg-item{display:inline-flex;align-items:center;gap:6px}.y-label{font-size:12px;color:var(--muted)}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--line);stroke-width:1}
.tick,.bar-l{fill:var(--text2);font-size:11.5px}.bar-v{fill:var(--text);font-size:12px;font-variant-numeric:tabular-nums}
.axis-label{fill:var(--muted);font-size:12px}.ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.ln-muted{fill:none;stroke-width:1.5;stroke:var(--muted)!important}.vref{stroke:var(--muted);stroke-width:1}
.vref-t{fill:var(--text2);font-size:11px}.zone-crit{fill:var(--zone-crit)}.zone-warn{fill:var(--zone-warn)}
.xhair{stroke:var(--muted);stroke-width:1}.hit{fill:transparent;cursor:crosshair}
.tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12px;
box-shadow:0 4px 14px rgba(0,0,0,.12);white-space:nowrap;z-index:5}.tip b{font-variant-numeric:tabular-nums}
.tip .k{display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
.zones{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--text2);margin:4px 0}
.zk{display:inline-block;width:14px;height:10px;border-radius:2px;margin-right:6px;vertical-align:middle}
.toggle{border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:8px;padding:5px 10px;font:inherit;font-size:13px;cursor:pointer}
nav.toc{font-size:13px;color:var(--text2);display:flex;flex-wrap:wrap;gap:4px 14px;margin:6px 0 4px}nav.toc a{color:var(--text2)}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;font-size:12px}
@media (max-width:640px){h1{font-size:21px}.tile .v{font-size:20px}.tile.hero .v{font-size:26px}section{padding:4px 12px 10px}}
@media print{details{display:block}summary h2::before{display:none}.toggle,nav.toc{display:none}section{break-inside:avoid-page}}
"""

JS = r"""
(function(){
 var root=document.documentElement;
 try{var t=localStorage.getItem('prism-theme'); if(t) root.setAttribute('data-theme',t);}catch(e){}
 var b=document.getElementById('theme');
 if(b) b.addEventListener('click',function(){var c=root.getAttribute('data-theme');var n=c==='dark'?'light':(c==='light'?'':'dark');
   if(n) root.setAttribute('data-theme',n); else root.removeAttribute('data-theme');
   try{ if(n) localStorage.setItem('prism-theme',n); else localStorage.removeItem('prism-theme');}catch(e){}
   b.textContent=n==='dark'?'Тема: тёмная':(n==='light'?'Тема: светлая':'Тема: системная');});
 function fmt(v,pct){if(v===null||v===undefined||!isFinite(v))return '—'; if(pct) return (v*100).toFixed(2)+'%';
   var a=Math.abs(v); if(a>=1e9) return (v/1e9).toFixed(2)+' млрд'; if(a>=1e6) return (v/1e6).toFixed(2)+' млн';
   if(a>=1e4) return (v/1e3).toFixed(0)+' тыс.'; if(a>=1) return v.toFixed(2); return v.toFixed(4);}
 document.querySelectorAll('figure.fig').forEach(function(fig){
   var dEl=fig.querySelector('script.chart-data'); if(!dEl) return; var d=JSON.parse(dEl.textContent);
   var svg=fig.querySelector('svg.chart'); var tip=fig.querySelector('.tip'); var hit=svg.querySelector('.hit'); var xh=svg.querySelector('.xhair');
   function move(ev){var r=svg.getBoundingClientRect(); var sc=d.geom.width/r.width; var px=(ev.clientX-r.left)*sc;
     var xv=d.geom.x0+(px-d.geom.ml)/d.geom.w*(d.geom.x1-d.geom.x0); var i=0,best=1e300;
     for(var k=0;k<d.x.length;k++){var dd=Math.abs(d.x[k]-xv); if(dd<best){best=dd;i=k;}}
     var sxp=d.geom.ml+(d.x[i]-d.geom.x0)/(d.geom.x1-d.geom.x0)*d.geom.w; xh.setAttribute('x1',sxp); xh.setAttribute('x2',sxp); xh.setAttribute('visibility','visible');
     var h='<div>'+fmt(d.x[i],d.pct_x)+'</div>'; d.series.forEach(function(s){h+='<div><span class="k" style="background:'+s.color+'"></span>'+s.label+': <b>'+fmt(s.y[i],d.pct_y)+'</b></div>';});
     tip.innerHTML=h; tip.hidden=false; var lx=(sxp/sc)+12; if(lx+tip.offsetWidth>r.width) lx=(sxp/sc)-tip.offsetWidth-12; tip.style.left=lx+'px'; tip.style.top='8px';}
   hit.addEventListener('mousemove',move); hit.addEventListener('mouseleave',function(){tip.hidden=true; xh.setAttribute('visibility','hidden');});
 });
})();
"""


def render_html(v) -> str:
    p = v.pricing
    tr = v.trade
    idn = tr.identification
    desc = v.description
    parts: list[str] = []
    title = esc(tr.product)
    parts.append(f'<header class="top"><div><h1>{title}</h1><div class="meta">Сделка {esc(idn.trade_id)} · клиент '
                 f'{esc(idn.client)} · банк {esc(idn.bank)} · дата оценки {esc(v.record.get("snapshot", {}).get("as_of", "")[:16].replace("T", " "))} МСК'
                 f' · снапшот <code>{esc(v.snapshot_id)}</code></div></div>'
                 f'<button class="toggle" id="theme" type="button">Тема: системная</button></header>')
    if v.snapshot_demo:
        parts.append('<div class="demo">ДЕМОНСТРАЦИОННЫЙ СНАПШОТ: рыночные данные иллюстративные. Числа в отчёте показывают работу '
                     'методики и не являются оценкой реальной сделки.</div>')
    b = v.breakdown
    tiles = [("Справедливая стоимость для компании (mid)", _rub(p.value), f"движок: {p.engine}", True)]
    if b is not None:
        tiles.append(("Передача стоимости банку", _rub(b.transfer), "премия − mid", False))
        if b.transfer > 0:
            tiles.append(("Наценка сверх обоснованного", _rub(b.residual),
                          f"{b.residual_bp_pa:,.0f} б.п. годовых на номинал".replace(",", " ") if math.isfinite(b.residual_bp_pa) else "", False))
        else:
            tiles.append(("Наценка сверх обоснованного", "нет", "по mid-оценке структура выгодна компании", False))
    if v.xva is not None:
        tiles.append(("Кредитная составляющая (CVA)", _rub(b.credit if b else v.xva.cva), "метод прокси — см. раздел CVA", False))
    tiles.append(("Модельные входы", str(len(p.model_based_inputs)), "не рыночные числа в оценке", False))
    parts.append('<div class="tiles">' + "".join(
        f'<div class="tile{" hero" if h else ""}"><div class="l">{esc(l)}</div><div class="v">{val}</div><div class="d">{esc(d)}</div></div>'
        for l, val, d, h in tiles) + "</div>")
    toc = [("cfo", "Итог"), ("deal", "Сделка"), ("decomp", "Разложение"), ("alt", "Альтернатива"), ("greeks", "Чувствительности"),
           ("scen", "Сценарии"), ("cva", "CVA"), ("inputs", "Входы"), ("model", "Модель"), ("market", "Кривые"),
           ("qc", "QC"), ("nrd", "НРД"), ("audit", "Аудит")]
    parts.append('<nav class="toc">' + "".join(f'<a href="#{a}">{esc(t)}</a>' for a, t in toc) + "</nav>")
    if p.warnings:
        parts.append("".join(f'<div class="warnbox">{esc(w)}</div>' for w in p.warnings[:12]))
    # 1. итог
    parts.append(_section("cfo", "Итог для финансового директора",
                          '<ul class="cfo">' + "".join(f"<li>{s}</li>" for s in _cfo_summary(v)) + "</ul>"))
    # 2. сделка
    legs_html = ""
    for leg in desc["legs"]:
        items = "".join(f"<li>{esc(c)}</li>" for c in leg["components"] + leg["modifiers"])
        legs_html += f"<h3>{esc(leg['head'])}</h3><ul>{items}</ul>"
    if desc["structure"]:
        legs_html += "<h3>Условия уровня сделки</h3><ul>" + "".join(f"<li>{esc(s)}</li>" for s in desc["structure"]) + "</ul>"
    refs = ""
    if tr.termsheet_refs:
        refs = "<h3>Ссылки на термшит</h3>" + _table(["Поле", "Место в документе"], [[k, vv] for k, vv in tr.termsheet_refs.items()])
    parts.append(_section("deal", "Инструмент и экономическое назначение",
                          f'<p><b>Назначение:</b> {esc(desc["purpose"])}{(" — " + esc(desc["purpose_note"])) if desc["purpose_note"] else ""}</p>'
                          f"{legs_html}{refs}"))
    # 3. разложение
    if b is not None:
        wf = b.waterfall()
        chart = hbar_chart([(w["label"], w["value"]) for w in wf], highlight={len(wf) - 1}, unit=" ₽")
        rows = [["Премия клиента (приведённая)", b.premium_pv, "условия сделки"],
                ["Справедливая стоимость для клиента (mid)", b.fair_value_client, p.model],
                [Raw("<b>Передача стоимости банку</b>"), b.transfer, "премия − mid"]]
        meth = {"Хеджирование и исполнение": "спреды спота/форвардов/волатильности/свопов × чувствительности + оценка перехеджирования",
                "Модельная неопределённость": "½·|VV − LV(PDE)| для барьерной части",
                "Кредитный риск (CVA)": "CVA с WWR (стохастическая интенсивность), прокси-кривая",
                "Фондирование (FVA)": "FCA − FBA по EE/ENE, спред фондирования — допущение",
                "Капитал (KVA)": "α·EEE·RW·норматив × стоимость капитала — допущение",
                "Остаток (наценка)": "передача − все обоснованные компоненты"}
        rows += [[w["label"], w["value"], meth.get(w["label"], "")] for w in wf]
        hd = _table(["Издержка", "Сумма, ₽", "Основа расчёта"], [[h["item"], h["value"], h["basis"]] for h in b.hedge_detail])
        notes = "".join(f'<div class="warnbox">{esc(n)}</div>' for n in b.notes)
        parts.append(_section("decomp", "Разложение цены",
                              chart + _table(["Компонента", "Сумма, ₽", "Метод"], rows) + "<h3>Издержки хеджирования</h3>" + hd + notes,
                              lead="Разница между премией и справедливой стоимостью раскладывается на обоснованные компоненты "
                                   "и остаток — наценку банка сверх рыночных издержек и кредитного риска."))
    # 4. альтернативы и профиль
    if v.alternatives is not None:
        rows = [[Raw("<b>Предложенная структура</b>"), p.value, p.engine, "—"]]
        rows += [[a["label"], a["value"], a["engine"], a["description"]] for a in v.alternatives]
        body = _table(["Вариант", "Стоимость для компании, ₽", "Движок", "Описание"], rows)
        if v.profile is not None:
            pr = v.profile
            series = [{"label": k, "y": vals} for k, vals in pr.series.items()]
            series.append({"label": "Без хеджа (рынок)", "y": pr.unhedged, "muted": True, "dashed": True, "color": "var(--muted)"})
            body += line_chart(pr.x, series, cid="profile", x_label=pr.x_label, zones=pr.zones,
                               vlines=[(pr.forward, "текущий уровень")], pct_x=pr.x[-1] < 1.0, pct_y=pr.x[-1] < 1.0,
                               y_label="эффективный курс / ставка для компании")
            kinds = {z["type"] for z in pr.zones}
            zl = []
            if "worse_than_unhedged" in kinds:
                zl.append('<span><span class="zk" style="background:var(--zone-crit)"></span>● хуже, чем без хеджа</span>')
            if "protection_off" in kinds:
                zl.append('<span><span class="zk" style="background:var(--zone-warn)"></span>▲ защита отключается</span>')
            if zl:
                body += '<div class="zones">' + "".join(zl) + "</div>"
            body += "<ul>" + "".join(f"<li>{esc(s)}</li>" for s in pr.summary) + "</ul>"
            body += f'<p class="muted">Конвенция профиля: {esc(pr.convention)}.</p>'
            # табличный вид ключевых точек
            idx = [int(i) for i in sorted(set([0, len(pr.x) // 4, len(pr.x) // 2, 3 * len(pr.x) // 4, len(pr.x) - 1]))]
            hdr = ["Уровень"] + list(pr.series.keys())
            body += _table(hdr, [[pr.x[i]] + [pr.series[k][i] for k in pr.series] for i in idx])
        parts.append(_section("alt", "Ванильная альтернатива и профиль выплат", body,
                              lead="Альтернативы с тем же назначением, на том же графике и номинале, без плеча и барьеров."))
    # 5. чувствительности
    if v.greeks is not None:
        g = v.greeks
        rows = []
        for k, val in g["values"].items():
            if isinstance(val, dict) and "delta" in val:
                rows += [[f"{k}: дельта (спот), ед. базиса", val["delta"]], [f"{k}: дельта (форвард)", val.get("forward_delta")],
                         [f"{k}: дельта в рублях", val["delta_value"]], [f"{k}: гамма (P&L на 1% спота)", val.get("gamma_pnl_1pct")],
                         [f"{k}: вега на 1 п.", val.get("vega_1pt")], [f"{k}: волга на 1 п.²", val.get("volga_1pt")],
                         [f"{k}: ванна (Δвега на 1% спота)", val.get("vanna_1pt")], [f"{k}: ро иностранной ставки, 1 б.п.", val.get("rho_foreign_1bp")]]
            elif isinstance(val, dict) and "dv01_parallel" in val:
                rows += [[f"{k}: DV01 параллельный, 1 б.п.", val["dv01_parallel"]], [f"{k}: гамма по ставке (±10 б.п.)", val["gamma_10bp"]]]
            elif isinstance(val, dict) and "vega_1bp_normal" in val:
                rows += [[f"{k}: вега ставки, 1 б.п. нормальной волы", val["vega_1bp_normal"]]]
            elif k == "theta_1d":
                rows.append(["Тета за 1 день", val])
            elif k == "correlation":
                rows.append([f"Корреляция {val['pair']}: на +0.01", val["d_value_per_0.01"]])
            elif k == "cross_gamma":
                rows.append([f"Кросс-гамма {val['pair']} (1% × 1%)", val["value_per_1pct_each"]])
        body = _table(["Чувствительность", "Значение, ₽ (для дельты — ед.)"], rows)
        for key, rws in g["buckets"].items():
            if key.startswith("vega:") and rws:
                body += f"<h3>Вега по срокам поверхности {esc(key[5:])}</h3>" + column_chart([r["bucket"] for r in rws], [r["vega_1pt"] for r in rws],
                                                                                             y_label="₽ на 1 п. волатильности")
            elif key.startswith("krd:") and rws:
                _, cid, role = key.split(":")
                body += f"<h3>Key-rate DV01: {esc(cid)} ({'дисконтная' if role == 'disc' else 'прогнозная'} роль)</h3>" + \
                    column_chart([r["tenor"] for r in rws], [r["dv01"] for r in rws], y_label="₽ на 1 б.п.")
            elif key.startswith("irvega:") and rws:
                body += f"<h3>Вега ставки по сетке expiry × tenor ({esc(key[7:])})</h3>" + _table(
                    ["Экспирация, лет", "Срок, лет", "₽ на 1 б.п."], [[r["expiry"], r["tenor"], r["vega_1bp"]] for r in rws if abs(r["vega_1bp"]) > 1e-6])
        if v.barrier:
            bp = v.barrier
            if bp.get("warning"):
                body += f'<div class="warnbox">▲ {esc(bp["message"])}</div>'
            else:
                body += f'<p class="muted">{esc(bp["message"])}</p>'
            prof = bp["profiles"]
            if prof:
                xs = prof[0]["spots"]
                body += "<h3>Профиль у барьера: стоимость</h3>" + line_chart(
                    xs, [{"label": f"через {c['days_forward']} дн." if c["days_forward"] else "сейчас", "y": c["values"]} for c in prof],
                    cid="barrier_v", x_label="спот", vlines=[(bp["barrier"], "барьер")], y_label="стоимость, ₽")
                body += "<h3>Профиль у барьера: дельта</h3>" + line_chart(
                    xs, [{"label": f"через {c['days_forward']} дн." if c["days_forward"] else "сейчас", "y": c["delta"]} for c in prof],
                    cid="barrier_d", x_label="спот", vlines=[(bp["barrier"], "барьер")], y_label="дельта, ед. базиса")
        body += f'<p class="muted">Метод: {esc("; ".join(f"{k}: {m}" for k, m in g["method"].items()))}</p>'
        parts.append(_section("greeks", "Чувствительности", body))
    # 6. сценарии
    if v.stresses or v.grid:
        body = ""
        if v.stresses:
            body += "<h3>Обязательные стрессы</h3>" + _table(["Сценарий", "P&L компании, ₽", "Стоимость после шока, ₽"],
                                                              [[s["label"], s.get("pnl"), s.get("value")] for s in v.stresses])
        if v.grid:
            gr = v.grid
            vmax = max((abs(x) for row in gr["pnl"] for x in row), default=1.0)
            hdr = "<tr><th>Вола \\ спот</th>" + "".join(f"<th>{s:+.0%}</th>" for s in gr["spot_shifts"]) + "</tr>"
            trs = ""
            for dv, row in zip(gr["vol_shifts"], gr["pnl"]):
                trs += f"<tr><th>{dv * 100:+.0f} п.</th>" + "".join(f'<td class="num" {diverging_cell(x, vmax)}>{esc(fmt_num(x))}</td>' for x in row) + "</tr>"
            body += ('<h3>Сетка спот × волатильность (P&L компании)</h3><div class="tbl-wrap"><table>' + hdr + trs + "</table></div>"
                     '<p class="muted">Синий — выигрыш компании, красный — потеря; насыщенность — величина.</p>')
        parts.append(_section("scen", "Сценарии и стрессы", body))
    # 7. CVA
    if v.xva is not None:
        x = v.xva
        rows = [["CVA (дефолт компании, базовый)", x.cva], ["CVA с WWR: альфа-множитель", x.cva_wwr_alpha],
                ["CVA с WWR: стохастическая интенсивность", x.cva_wwr_stochastic], ["DVA (дефолт банка)", x.dva],
                ["FCA / FBA", f"{fmt_num(x.fca)} / {fmt_num(x.fba)}"], ["KVA", x.kva], ["EPE", x.epe], ["Эффективная EPE (1 год)", x.eepe]]
        cc = x.method.get("credit_client", {})
        cb = x.method.get("credit_bank", {})
        def _crow(side, c):
            return [side, c.get("entity"), c.get("method"), str(c.get("method_rank")), c.get("spread_5y_bp"),
                    f"{c.get('pd_1y', 0):.2%}", f"{c.get('recovery', 0):.0%}"]
        crow = [_crow("Компания", cc), _crow("Банк", cb)]
        body = _table(["Показатель", "₽"], rows)
        body += "<h3>Кредитные кривые (прокси)</h3>" + _table(["Сторона", "Лицо", "Метод", "Приоритет метода", "Спред 5Y, б.п.", "PD 1Y", "Восстановление"], crow)
        body += line_chart(x.times, [{"label": "EE (ожидаемая экспозиция банка)", "y": x.ee},
                                     {"label": f"PFE (квантиль)", "y": x.pfe}, {"label": "ENE (экспозиция компании на банк)", "y": x.ene}],
                           cid="exposure", x_label="лет от даты оценки", y_label="экспозиция, ₽")
        body += (f'<p class="muted">Экспозиция: {esc(x.method.get("exposure"))}; путей {x.method.get("paths")}, seed {x.method.get("seed")}; '
                 f'факторы: {esc(", ".join(x.method.get("risk_factors", [])))}. Неттинг: {esc(x.netting)}; обеспечение: {esc(x.collateral)}. '
                 f'WWR: β={x.method.get("wwr", {}).get("beta")}, фактор {esc(x.method.get("wwr", {}).get("driver"))}.</p>')
        body += "".join(f'<div class="warnbox">{esc(w)}</div>' for w in x.warnings)
        parts.append(_section("cva", "CVA и прочие XVA", body, lead="Кредитная составляющая — общий модуль кредитных кривых; "
                                                                    "метод прокси и его входы воспроизводимы по публичным данным."))
    # 8. входы
    mb = {u["id"] for u in p.model_based_inputs}
    rows = []
    for u in sorted(p.inputs, key=lambda u: (u["id"] not in mb, u["id"])):
        pv = u["provenance"]
        val = u["value"]
        if isinstance(val, float):
            vs = f"{val:.6g}"
        elif isinstance(val, (dict, list)):
            vs = json.dumps(val, ensure_ascii=False)[:80]
        else:
            vs = str(val)
        flags = " ".join(f'<span class="badge b-warn">{esc(f)}</span>' for f in u.get("flags", []))
        src = esc(pv["source"]) + (f' <span class="muted">({esc(pv["note"])})</span>' if pv.get("note") else "")
        rows.append([f"<td><code>{esc(u['id'])}</code></td>", vs, Raw(src), (pv.get("as_of") or "")[:16].replace("T", " "),
                     Raw(_badge(pv["kind"]) + " " + flags), u.get("role", "")])
    lead = (f"Использовано входов: {len(p.inputs)}. Модельных (не рыночных) — {len(mb)}: они показаны первыми."
            if mb else f"Использовано входов: {len(p.inputs)}. Все входы — рыночные или выведенные из рынка.")
    parts.append(_section("inputs", "Рыночные входы и их происхождение",
                          _table(["Вход", "Значение", "Источник", "Время", "Вид", "Роль в оценке"], rows), lead=lead, open_=False))
    # 9. модель
    body = f"<p><b>Движок:</b> {esc(p.engine)}. <b>Модель:</b> {esc(p.model)}.</p>"
    if p.fallback_reason:
        body += f'<p class="muted">Аналитика неприменима: {esc(p.fallback_reason)} — использован {esc(p.engine)}.</p>'
    if p.mc:
        m = p.mc
        body += (f"<p>Монте-Карло: {m['paths']:,} путей, seed {m['seed']}, стандартная ошибка {fmt_num(m['stderr'])} ₽, "
                 f"95% ДИ [{fmt_num(m['ci95'][0])}; {fmt_num(m['ci95'][1])}] ₽.</p>").replace(",", " ")
        body += _table(["Путей", "Оценка, ₽", "Ст. ошибка, ₽"], [[c["paths"], c["value"], c["stderr"]] for c in m["convergence"]])
    if p.checks:
        body += "<h3>Проверки</h3>" + _table(["Проверка", "Результат", "Детали"],
                                             [[c["check"], f'<span class="{"ok" if c.get("ok") else "fail"}">{"пройдена" if c.get("ok") else "не пройдена"}</span>',
                                               c.get("detail", "")] for c in p.checks])
    if p.items:
        body += "<h3>Компоненты оценки</h3>" + _table(["Нога", "Период", "Компонент", "PV, ₽", "Метод"],
                                                       [[i.get("leg"), i.get("period"), i.get("component"), i.get("pv"), i.get("method")] for i in p.items[:60]])
    if p.cashflows:
        body += "<h3>Ожидаемые потоки (МК)</h3>" + _table(["Нога", "Поток", "Фиксинг", "Платёж", "Валюта", "Ожидаемая сумма", "PV, ₽"],
                                                         [[c["leg"], c["label"], c["fixing"], c["payment"], c["currency"], c["expected_amount"], c["pv"]] for c in p.cashflows[:80]])
    if v.errors:
        body += "<h3>Ошибки отдельных блоков</h3>" + "".join(f'<div class="warnbox">{esc(e)}</div>' for e in v.errors)
    body += "<h3>Время расчёта, мс</h3>" + _table(["Блок", "мс"], [[k, val] for k, val in v.timings.items()])
    parts.append(_section("model", "Модель, численные методы и проверки", body, open_=False))
    # 10. рынок
    mk = v.market or {}
    body = ""
    mp = mk.get("meeting_path")
    if mp:
        xs = list(range(len(mp)))
        body += "<h3>Имплицированная траектория ключевой ставки по заседаниям</h3>"
        body += _table(["Объявление", "Вступление в силу", "Ставка до", "Ставка после", "Ожидаемое изменение, б.п.", "Исходы (б.п.: вероятность)"],
                       [[m["announcement"], m["effective"], f"{m['rate_before']:.2%}", f"{m['rate_after']:.2%}", m["expected_change_bp"],
                         ", ".join(f"{o['change_bp']:+.0f}: {o['probability']:.0%}" for o in m["outcomes"])] for m in mp])
    for cid, rep in mk.get("curves", {}).items():
        body += f"<h3>Кривая {esc(cid)}: репрайсинг калибровочных инструментов (макс. ошибка {rep['max_error_bp']:.3f} б.п.)</h3>"
        body += _table(["Котировка", "Рынок", "Модель", "Ошибка, б.п."],
                       [[r["quote_id"], f"{r['market']:.4%}" if abs(r["market"]) < 1 else r["market"],
                         f"{r['model']:.4%}" if abs(r["model"]) < 1 else r["model"], r["error_bp"]] for r in rep["calibration"]])
    for pair, rows_ in mk.get("cip", {}).items():
        body += f"<h3>Покрытый паритет {esc(pair)}: имплицированная рублёвая ставка и базис к onshore</h3>"
        body += _table(["Дата", "Аутрайт", "Пункты", "Ставка валюты", "Имплиц. RUB", "Onshore RUB", "Базис, б.п."],
                       [[r["date"], r["outright"], r["points"], f"{r['foreign_rate']:.2%}", f"{r['implied_rate']:.2%}", f"{r['onshore_rate']:.2%}", r["basis_bp"]] for r in rows_])
    for pair, sd in mk.get("vol", {}).items():
        arb = sd.get("arbitrage", [])
        body += f"<h3>Поверхность волатильности {esc(pair)} ({esc(sd.get('method'))}, sticky-{esc(sd.get('sticky'))})</h3>"
        body += _table(["Срок", "Экспирация", "Форвард", "Столпы (страйк: вола)", "Ошибка подгонки"],
                       [[s.get("tenor"), s["expiry"], s["forward"], ", ".join(f"{pp['label']} {pp['strike']:.2f}: {pp['vol']:.2%}" for pp in s["pillars"]),
                         s["fit_rmse"]] for s in sd["slices"]])
        bad = [a for a in arb if not a["ok"]]
        body += (f'<p><span class="ok">Арбитражные проверки пройдены ({len(arb)})</span></p>' if not bad else
                 "".join(f'<div class="warnbox">✕ {esc(a["check"])} {esc(a["expiry"])}: {esc(a["detail"])}</div>' for a in bad))
    parts.append(_section("market", "Кривые, поверхности и диагностика рынка", body or '<p class="muted">нет данных</p>', open_=False))
    # 11. QC
    qc = v.qc or []
    parts.append(_section("qc", "Контроль качества данных снапшота",
                          _table(["Уровень", "Проверка", "Котировка", "Сообщение"], [[q["severity"], q["check"], q["quote_id"], q["message"]] for q in qc])
                          if qc else '<p><span class="ok">Замечаний нет</span></p>', open_=False))
    # 12. МСФО 9
    if v.ifrs9 is not None:
        f = v.ifrs9
        body = (f"<p><b>Основной договор:</b> {esc(f.host_type)}. <b>Тесно связан:</b> {'да' if f.closely_related else 'нет'}. "
                f"<b>Отделение:</b> {'требуется' if f.separate else 'не требуется'}. <b>Справедливая стоимость встроенного дериватива:</b> "
                f"{_rub(f.fair_value)} (уровень {f.fair_value_level} иерархии).</p><ul>" + "".join(f"<li>{esc(r)}</li>" for r in f.rationale) + "</ul>"
                f"<p class=\"muted\">Пункты МСФО 9: {esc(', '.join(f.paragraphs))}.</p>"
                + "".join(f'<div class="warnbox">Требует суждения: {esc(j)}</div>' for j in f.judgement_required))
        parts.append(_section("ifrs9", "Встроенный дериватив: раскрытие по МСФО 9", body))
    # 13. НРД
    if v.nrd:
        parts.append(_section("nrd", "Поля для сверки с репозитарием НРД",
                              _table(["Поле", "Значение"], [[k, vv] for k, vv in v.nrd.items()]), open_=False))
    # 14. аудит
    rec = v.record
    body = (f"<p>Оценка воспроизводится командой <code>prism replay &lt;запись.json&gt;</code>: снапшот загружается по идентификатору "
            f"с проверкой хэша, сделка — с проверкой хэша, все движки получают те же seed; результаты сравниваются побитово.</p>"
            + _table(["Элемент", "Значение"], [
                ["Версия пакета", rec.get("code", {}).get("package_version")], ["Git commit", rec.get("code", {}).get("commit")],
                ["Хэш исходного кода", rec.get("code", {}).get("source_hash")], ["Снапшот", rec.get("snapshot", {}).get("id")],
                ["Хэш снапшота", rec.get("snapshot", {}).get("content_hash")], ["Хэш сделки", rec.get("trade", {}).get("hash")],
                ["Версия схемы сделки", rec.get("trade", {}).get("schema_version")], ["Хэш конфигурации рынка", rec.get("market_config_hash")],
                ["Seed Монте-Карло / XVA", f"{rec.get('rng', {}).get('mc_seed')} / {rec.get('rng', {}).get('xva_seed')}"],
                ["Версии моделей", ", ".join(f"{k} {vv}" for k, vv in rec.get("models", {}).items())]])
            + "<h3>Ключевые результаты (IEEE-754 hex)</h3>"
            + _table(["Результат", "Значение", "hex"], [[k, o["value"], f"<td><code>{esc(o['hex'])}</code></td>"] for k, o in rec.get("outputs", {}).items()]))
    parts.append(_section("audit", "Аудиторский след и воспроизводимость", body, open_=False))
    doc = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>Отчёт Prism — {title}</title><style>{CSS}</style></head><body><div class=\"wrap\">{''.join(parts)}"
           f'<p class="muted">Prism {esc(rec.get("code", {}).get("package_version", ""))} · независимая оценка внебиржевых ПФИ · '
           f"только публичные источники данных</p></div><script>{JS}</script></body></html>")
    return doc


def save_report(v, path) -> str:
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_html(v), encoding="utf-8")
    return str(p)
