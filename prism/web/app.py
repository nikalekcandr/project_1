"""Веб-интерфейс Prism (FastAPI): каталог структур, термшит, оценка, отчёт, рынок, сравнение предложений."""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

import yaml

from pydantic import BaseModel

STATIC = Path(__file__).resolve().parent / "static"


class RenderReq(BaseModel):
    template: str
    params: dict[str, Any] = {}


class PriceReq(BaseModel):
    trade_yaml: str
    snapshot_id: str | None = None
    mode: str = "quick"           # quick | full | price


class CompareReq(BaseModel):
    packages: list[str]
    snapshot_id: str | None = None


def create_app(store_dir: str | None = None):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
    from ..instruments.schema import load_trade
    from ..instruments.templates import list_templates, render
    from ..marketdata.context import MarketContext
    from ..marketdata.store import SnapshotStore
    from ..reporting.html import render_html
    from ..reporting.svg import hbar_chart, line_chart
    from ..valuation import ValuationOptions, run_valuation

    app = FastAPI(title="Prism", description="Независимый прайсер внебиржевых ПФИ российского рынка")
    store = SnapshotStore(store_dir)
    if not store.ids():
        from ..marketdata.demo import demo_store_snapshots
        demo_store_snapshots(store)
    reports: dict[str, Any] = {}
    lock = threading.Lock()

    def snapshot(sid: str | None):
        try:
            return store.load(sid) if sid else store.latest()
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/favicon.svg")
    def favicon():
        from fastapi.responses import Response
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#2a78d6"/>'
               '<path d="M8 23 L16 7 L24 23 Z" fill="none" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/></svg>')
        return Response(svg, media_type="image/svg+xml")

    @app.get("/app.css")
    def app_css():
        from fastapi.responses import Response
        from ..reporting.html import CSS
        return Response(CSS + (STATIC / "app.css").read_text(encoding="utf-8"), media_type="text/css; charset=utf-8")

    @app.get("/app-charts.js")
    def app_js():
        from fastapi.responses import Response
        from ..reporting.html import JS
        return Response(JS, media_type="application/javascript; charset=utf-8")

    @app.get("/api/templates")
    def templates():
        return list_templates()

    @app.post("/api/render")
    def render_trade(req: RenderReq):
        try:
            data = render(req.template, req.params)
            load_trade(dict(data))   # проверка схемы
        except Exception as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}")
        return {"yaml": yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=None)}

    @app.get("/api/snapshots")
    def snapshots():
        out = []
        for sid in store.ids():
            s = store.load(sid)
            out.append({"id": sid, "as_of": s.as_of.isoformat(), "demo": s.is_demo, "quotes": len(s.quotes),
                        "parent": s.parent_id, "qc": len(s.qc)})
        return out

    @app.post("/api/price")
    def price(req: PriceReq):
        try:
            trade = load_trade(yaml.safe_load(req.trade_yaml))
        except Exception as e:
            raise HTTPException(400, f"ошибка в термшите: {type(e).__name__}: {e}")
        snap = snapshot(req.snapshot_id)
        opts = {"quick": ValuationOptions.fast(), "full": ValuationOptions(), "price": ValuationOptions.price_only()}.get(req.mode)
        if opts is None:
            raise HTTPException(400, "mode: quick | full | price")
        v = run_valuation(trade, snap, opts)
        rid = uuid.uuid4().hex[:12]
        with lock:
            reports[rid] = v
            if len(reports) > 50:
                reports.pop(next(iter(reports)))
        p = v.pricing
        out: dict[str, Any] = {
            "report_id": rid, "product": trade.product, "value": p.value, "currency": p.currency, "engine": p.engine,
            "model": p.model, "warnings": p.warnings, "errors": v.errors, "demo": v.snapshot_demo, "snapshot": v.snapshot_id,
            "mc": p.mc and {k: p.mc[k] for k in ("stderr", "ci95", "paths", "seed")}, "checks": p.checks,
            "model_based_inputs": [u["id"] for u in p.model_based_inputs], "timings": v.timings,
            "description": v.description,
        }
        if v.breakdown is not None:
            b = v.breakdown
            out["breakdown"] = {"transfer": b.transfer, "premium_pv": b.premium_pv, "waterfall": b.waterfall(),
                                "residual_bp_pa": b.residual_bp_pa, "residual_pct": b.residual_pct_notional}
            wf = b.waterfall()
            out["breakdown_svg"] = hbar_chart([(w["label"], w["value"]) for w in wf], highlight={len(wf) - 1}, unit=" ₽")
        if v.alternatives is not None:
            out["alternatives"] = [{"label": a["label"], "value": a["value"], "description": a["description"]} for a in v.alternatives]
        if v.profile is not None:
            pr = v.profile
            series = [{"label": k, "y": vals} for k, vals in pr.series.items()]
            series.append({"label": "Без хеджа (рынок)", "y": pr.unhedged, "muted": True, "dashed": True, "color": "var(--muted)"})
            pct = pr.x[-1] < 1.0
            out["profile_svg"] = line_chart(pr.x, series, cid="profile", x_label=pr.x_label, zones=pr.zones,
                                            vlines=[(pr.forward, "текущий уровень")], pct_x=pct, pct_y=pct,
                                            y_label="эффективный курс / ставка для компании")
            out["profile_summary"] = pr.summary
        if v.greeks is not None:
            g = {}
            for k, val in v.greeks["values"].items():
                if isinstance(val, dict) and "delta" in val:
                    g[k] = {"delta": val["delta"], "gamma_pnl_1pct": val.get("gamma_pnl_1pct"), "vega_1pt": val.get("vega_1pt")}
                elif isinstance(val, dict) and "dv01_parallel" in val:
                    g[k] = {"dv01": val["dv01_parallel"]}
                elif k == "theta_1d":
                    g["theta_1d"] = val
            out["greeks"] = g
        if v.xva is not None:
            out["xva"] = {"cva": v.xva.cva, "cva_wwr": v.xva.cva_wwr_stochastic, "dva": v.xva.dva, "kva": v.xva.kva,
                          "method": v.xva.method.get("credit_client", {}).get("method")}
        if v.stresses:
            out["stresses"] = [{"label": s["label"], "pnl": s.get("pnl")} for s in v.stresses]
        return JSONResponse(_clean(json.loads(json.dumps(out, default=_json_default))))

    @app.get("/api/report/{rid}", response_class=HTMLResponse)
    def report(rid: str):
        v = reports.get(rid)
        if v is None:
            raise HTTPException(404, "отчёт не найден (перезапуск сервера очищает кэш)")
        return HTMLResponse(render_html(v))

    @app.get("/api/record/{rid}")
    def record(rid: str):
        v = reports.get(rid)
        if v is None:
            raise HTTPException(404, "запись не найдена")
        return JSONResponse(_clean(json.loads(json.dumps(v.record, default=_json_default))))

    @app.get("/api/market")
    def market(snapshot_id: str | None = None):
        snap = snapshot(snapshot_id)
        ctx = MarketContext(snap)
        ks = ctx.curve("RUB.KEYRATE")
        import numpy as np
        ts = np.linspace(1 / 365, 3.0, 300)
        fwd = [365 * float(np.expm1(f / 365)) for f in ks.inst_fwd(ts)]
        ofz = ctx.curve("RUB.OFZ")
        rusfar = ctx.curve("RUB.RUSFAR")
        chart = line_chart(ts.tolist(), [{"label": "Форвард ключевой ставки (ступени на заседаниях)", "y": fwd},
                                         {"label": "Форвард RUSFAR", "y": [365 * float(np.expm1(f / 365)) for f in rusfar.inst_fwd(ts)]},
                                         {"label": "КБД ОФЗ (нулевая)", "y": [float(np.expm1(z)) for z in ofz.zero(ts)]}],
                           cid="ks", x_label="лет", pct_y=True, y_label="ставка")
        return _clean({"snapshot": snap.id, "demo": snap.is_demo, "as_of": snap.as_of.isoformat(), "keyrate_svg": chart,
                "meetings": ctx.meeting_path(), "qc": snap.qc,
                "curves": {cid: ctx.curve_fit_report(cid)["max_error_bp"] for cid in ctx.config["curves"]},
                "cip": {p: ctx.cip_table(p) for p in ("USDRUB", "CNYRUB")}})

    @app.post("/api/compare")
    def compare(req: CompareReq):
        from ..packages.package import compare_offers, load_package
        snap = snapshot(req.snapshot_id)
        try:
            pk = [load_package(yaml.safe_load(t)) for t in req.packages]
        except Exception as e:
            raise HTTPException(400, f"ошибка в описании пакета: {e}")
        res = compare_offers(pk, MarketContext(snap))
        return JSONResponse(_clean(json.loads(json.dumps(res, default=_json_default))))

    @app.get("/api/examples/packages")
    def example_packages():
        root = Path(__file__).resolve().parents[2] / "examples" / "packages"
        return [{"name": p.name, "yaml": p.read_text(encoding="utf-8")} for p in sorted(root.glob("*.yaml"))]

    return app


def _json_default(o):
    import numpy as np
    from datetime import date, datetime
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "to_dict"):
        return o.to_dict()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    return str(o)


def _clean(o):
    """NaN/inf → None (JSON браузера не принимает NaN)."""
    import math
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o
