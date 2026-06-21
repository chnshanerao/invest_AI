#!/usr/bin/env python3
"""
thesis_health.py — 投资论点健康监控

5个内置检查 + 1个降级触发匹配:
1. 论点过期 (>90天)
2. 收入减速 (连续2季revenue_yoy下降且<10%)
3. 毛利压缩 (连续2季gross_margin下降超3pp)
4. 估值过高 (bear_upside < 0)
5. 缺看空分析 (BUY标的无bear_thesis)
6. 降级触发匹配 (检查bear_thesis中的量化条件)
"""
import re
import sys
from datetime import datetime, timedelta
import monitor_db as db


def check_thesis_stale(ticker, thesis, conn):
    if not thesis or not thesis.get("updated_at"):
        return
    try:
        updated = datetime.strptime(thesis["updated_at"][:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return
    age = (datetime.now() - updated).days
    if age > 90:
        db.save_warning(ticker, "thesis_stale", "medium",
                        f"研究论点已{age}天未更新", f"上次更新: {thesis['updated_at']}", conn=conn)


def check_revenue_decel(ticker, fundamentals, conn):
    quarterly = [f for f in fundamentals if "Q" in f["period"] and f.get("revenue_yoy") is not None]
    quarterly.sort(key=lambda f: f["period"], reverse=True)
    if len(quarterly) < 2:
        return
    r0, r1 = quarterly[0]["revenue_yoy"], quarterly[1]["revenue_yoy"]
    if r0 < 10 and r1 < 10 and r0 < r1:
        db.save_warning(ticker, "revenue_decel", "high",
                        f"收入增速连续放缓: {quarterly[0]['period']} {r0:.1f}% ← {quarterly[1]['period']} {r1:.1f}%",
                        f"最近2季YoY: {r0:.1f}%, {r1:.1f}%", conn=conn)


def check_margin_compression(ticker, fundamentals, conn):
    quarterly = [f for f in fundamentals if "Q" in f["period"] and f.get("gross_margin") is not None]
    quarterly.sort(key=lambda f: f["period"], reverse=True)
    if len(quarterly) < 2:
        return
    m0, m1 = quarterly[0]["gross_margin"], quarterly[1]["gross_margin"]
    if m0 < m1 - 3:
        db.save_warning(ticker, "margin_compress", "high",
                        f"毛利率压缩: {quarterly[0]['period']} {m0:.1f}% ← {quarterly[1]['period']} {m1:.1f}%",
                        f"下降{m1-m0:.1f}pp", conn=conn)


def check_valuation_risk(ticker, vm, conn):
    if not vm or vm.get("bear_upside") is None:
        return
    if vm["bear_upside"] < 0:
        db.save_warning(ticker, "valuation_overextended", "high",
                        f"熊市情景亏损{abs(vm['bear_upside']):.0f}%",
                        f"Bear市值: ${vm['bear_mcap']/1e9:.1f}B vs 当前: ${vm['current_mcap']/1e9:.1f}B",
                        conn=conn)


def check_missing_bear(ticker, thesis, bear, conn):
    if not thesis:
        return
    verdict = thesis.get("verdict", "HOLD")
    if verdict in ("BUY",) and not bear:
        db.save_warning(ticker, "no_bear_thesis", "medium",
                        f"BUY标的缺少看空分析", "", conn=conn)


def check_downgrade_triggers(ticker, bear, fundamentals, conn):
    if not bear or not bear.get("downgrade_triggers"):
        return
    triggers = bear["downgrade_triggers"]
    if isinstance(triggers, str):
        try:
            import json
            triggers = json.loads(triggers)
        except Exception:
            return

    quarterly = [f for f in fundamentals if "Q" in f["period"]]
    quarterly.sort(key=lambda f: f["period"], reverse=True)
    if not quarterly:
        return

    latest = quarterly[0]
    status = {}
    for i, trigger in enumerate(triggers):
        fired = False
        m = re.search(r'收入增速[<＜](\d+)%', trigger)
        if m and latest.get("revenue_yoy") is not None:
            threshold = float(m.group(1))
            if latest["revenue_yoy"] < threshold:
                fired = True
        m = re.search(r'毛利率[<＜](\d+)%', trigger)
        if m and latest.get("gross_margin") is not None:
            threshold = float(m.group(1))
            if latest["gross_margin"] < threshold:
                fired = True
        status[i] = fired
        if fired:
            db.save_warning(ticker, "trigger_fired", "high",
                            f"降级条件触发: {trigger}",
                            f"当前数据: {latest['period']}", conn=conn)

    db.update_trigger_status(ticker, status, conn=conn)


def run(tickers=None):
    conn = db.get_conn()
    wl = db.get_watchlist(conn)
    if tickers:
        wl = [w for w in wl if w["ticker"] in tickers]

    conn.execute("DELETE FROM thesis_warnings WHERE is_dismissed=0")

    checked, warned = 0, 0
    for item in wl:
        ticker = item["ticker"]
        thesis = db.get_thesis(ticker, conn=conn)
        fundamentals = db.get_fundamentals(ticker, limit=8, conn=conn)
        vm = db.get_valuation_model(ticker, conn=conn)
        bear = db.get_bear_thesis(ticker, conn=conn)

        before = conn.execute("SELECT COUNT(*) FROM thesis_warnings WHERE ticker=? AND is_dismissed=0",
                              (ticker,)).fetchone()[0]

        check_thesis_stale(ticker, thesis, conn)
        check_revenue_decel(ticker, fundamentals, conn)
        check_margin_compression(ticker, fundamentals, conn)
        check_valuation_risk(ticker, vm, conn)
        check_missing_bear(ticker, thesis, bear, conn)
        check_downgrade_triggers(ticker, bear, fundamentals, conn)

        after = conn.execute("SELECT COUNT(*) FROM thesis_warnings WHERE ticker=? AND is_dismissed=0",
                             (ticker,)).fetchone()[0]
        new_warns = after - before
        checked += 1
        warned += new_warns
        icon = "🔴" if new_warns else "🟢"
        print(f"  {icon} {ticker:8s} {new_warns}个预警")

    conn.commit()
    conn.close()
    print(f"\n检查完成: {checked}个标的, {warned}个新预警")


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    print("=== 论点健康检查 ===")
    run(tickers)
