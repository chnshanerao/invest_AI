#!/usr/bin/env python3
"""
chokepoint_web.py — Chokepoint投研监测系统 Web Server V2

研究驱动型投资决策系统：产业链研究 → 估值 → 技术面 → 交易指令
aiohttp + 静态文件, port 8088
"""

import json
import os
import sys

from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor_db as mdb

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(WORKSPACE, "web")


def json_response(data, status=200):
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json",
        status=status,
    )


async def api_dashboard(request):
    data = mdb.get_dashboard_data()
    return json_response(data)


async def api_ticker(request):
    ticker = request.match_info["ticker"].upper()
    conn = mdb.get_conn()
    info = mdb.get_ticker_info(ticker, conn)
    if not info:
        conn.close()
        return json_response({"error": "Ticker not found"}, 404)

    signals = mdb.get_signals(ticker, limit=60, conn=conn)
    thesis = mdb.get_thesis(ticker, conn=conn)
    fundamentals = mdb.get_fundamentals(ticker, limit=8, conn=conn)
    valuation = mdb.get_valuation(ticker, conn=conn)
    filings = mdb.get_filings(ticker, days=90, conn=conn)
    bars = mdb.get_price_bars(ticker, days=120, conn=conn)
    supply = conn.execute(
        "SELECT * FROM supply_chain WHERE ticker=?", (ticker,)
    ).fetchall()
    company = mdb.get_company_profile(ticker, conn=conn)
    vm = mdb.get_valuation_model(ticker, conn=conn)

    conn.close()
    if company and company.get("raw_sections"):
        company.pop("raw_sections", None)
    if vm and vm.get("calc_details") and isinstance(vm["calc_details"], str):
        try:
            vm["calc_details"] = json.loads(vm["calc_details"])
        except Exception:
            pass
    return json_response({
        "info": info,
        "thesis": thesis,
        "fundamentals": fundamentals,
        "valuation": valuation,
        "bars": bars,
        "signals": signals,
        "filings": [dict(r) for r in filings],
        "supply_chain": [dict(r) for r in supply],
        "company_profile": company,
        "valuation_model": vm,
    })


async def api_fundamentals(request):
    ticker = request.match_info["ticker"].upper()
    data = mdb.get_fundamentals(ticker, limit=12)
    return json_response(data)


async def api_valuation(request):
    data = mdb.get_valuation()
    return json_response(data)


async def api_demand(request):
    data = mdb.get_demand_signals()
    return json_response(data)


async def api_supply_chain(request):
    data = mdb.get_supply_chain()
    return json_response(data)


async def api_signals(request):
    ticker = request.match_info["ticker"].upper()
    limit = int(request.query.get("limit", "60"))
    signals = mdb.get_signals(ticker, limit=limit)
    return json_response(signals)


async def api_macro(request):
    days = int(request.query.get("days", "30"))
    history = mdb.get_macro_history(days=days)
    latest = mdb.get_macro_latest()
    return json_response({"history": history, "latest": latest})


async def api_watchlist_post(request):
    body = await request.json()
    action = body.get("action", "upsert")

    if action == "delete":
        ticker = body.get("ticker", "").upper()
        if not ticker:
            return json_response({"error": "ticker required"}, 400)
        mdb.delete_watchlist_item(ticker)
        return json_response({"ok": True, "deleted": ticker})

    if action == "thesis":
        ticker = body.get("ticker", "").upper()
        mdb.save_thesis(ticker, thesis=body.get("thesis"), moat=body.get("moat"),
                        catalysts=body.get("catalysts"), risks=body.get("risks"),
                        verdict=body.get("verdict"))
        return json_response({"ok": True, "ticker": ticker})

    item = body.get("item", body)
    if not item.get("ticker"):
        return json_response({"error": "ticker required"}, 400)
    item["ticker"] = item["ticker"].upper()
    mdb.save_watchlist_item(item)
    return json_response({"ok": True, "ticker": item["ticker"]})


async def api_collect(request):
    module = request.match_info["module"]
    import subprocess
    scripts = {
        "trader": "chokepoint_trader.py",
        "insider": "insider_monitor.py",
        "filing": "sec_filing_monitor.py",
        "fundamentals": "fundamentals_fetcher.py",
        "research": "company_researcher.py",
        "valuation": "valuation_model.py",
    }
    script = scripts.get(module)
    if not script:
        return json_response({"error": f"Unknown module: {module}"}, 400)

    path = os.path.join(WORKSPACE, script)
    proc = subprocess.Popen(
        [sys.executable, path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=WORKSPACE,
    )
    stdout, _ = proc.communicate(timeout=300)
    return json_response({
        "ok": proc.returncode == 0,
        "output": stdout.decode("utf-8", errors="replace")[-2000:],
    })


async def api_company(request):
    ticker = request.match_info["ticker"].upper()
    profile = mdb.get_company_profile(ticker)
    if not profile:
        return json_response({"error": "No profile for " + ticker}, 404)
    if profile.get("raw_sections"):
        profile.pop("raw_sections", None)
    return json_response(profile)


async def api_settings_get(request):
    settings = mdb.get_all_settings()
    if "llm_api_key" in settings and settings["llm_api_key"]:
        key = settings["llm_api_key"]
        settings["llm_api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    return json_response(settings)


async def api_settings_post(request):
    body = await request.json()
    for key, value in body.items():
        if key == "llm_api_key" and "..." in str(value):
            continue
        mdb.save_setting(key, value)
    return json_response({"ok": True})


async def index_handler(request):
    return web.FileResponse(os.path.join(WEB_DIR, "index.html"))


def create_app():
    mdb.init_db()
    app = web.Application()

    app.router.add_get("/api/dashboard", api_dashboard)
    app.router.add_get("/api/ticker/{ticker}", api_ticker)
    app.router.add_get("/api/fundamentals/{ticker}", api_fundamentals)
    app.router.add_get("/api/valuation", api_valuation)
    app.router.add_get("/api/demand", api_demand)
    app.router.add_get("/api/supply-chain", api_supply_chain)
    app.router.add_get("/api/signals/{ticker}", api_signals)
    app.router.add_get("/api/macro", api_macro)
    app.router.add_post("/api/watchlist", api_watchlist_post)
    app.router.add_post("/api/collect/{module}", api_collect)
    app.router.add_get("/api/company/{ticker}", api_company)
    app.router.add_get("/api/settings", api_settings_get)
    app.router.add_post("/api/settings", api_settings_post)

    app.router.add_get("/", index_handler)
    app.router.add_static("/web/", WEB_DIR, show_index=False)

    return app


if __name__ == "__main__":
    app = create_app()
    print("Chokepoint Web Server V2 — http://0.0.0.0:8088")
    web.run_app(app, host="0.0.0.0", port=8088)
