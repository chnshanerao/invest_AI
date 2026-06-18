#!/usr/bin/env python3
"""
Chokepoint 估值模型 — Revenue-Based Forward Valuation

公式全透明，每一步可审计。
读取 fundamentals + valuation 表，计算 Bear/Base/Bull 三情景潜在市值，
写入 valuation_model 表。

无网络调用，纯本地计算。
"""
import json, sys
from datetime import datetime
import monitor_db as db


def mcap_tier(mcap):
    if mcap is None:
        return "N/A"
    b = mcap / 1e9
    if b >= 200:
        return "Mega"
    if b >= 50:
        return "Large"
    if b >= 10:
        return "Mid"
    if b >= 2:
        return "Small"
    return "Micro"


def compute_ttm_revenue(fundamentals):
    if not fundamentals:
        return None, {}
    annual = [f for f in fundamentals if "Q" not in f["period"] and f["revenue"]]
    quarterly = [f for f in fundamentals if "Q" in f["period"] and f["revenue"]]

    if len(quarterly) >= 4:
        q_sorted = sorted(quarterly, key=lambda f: f["period"], reverse=True)[:4]
        ttm = sum(f["revenue"] for f in q_sorted)
        detail = {"method": "sum_4q", "quarters": [f["period"] for f in q_sorted], "value": ttm}
        return ttm, detail

    if annual:
        latest = sorted(annual, key=lambda f: f["period"], reverse=True)[0]
        detail = {"method": "latest_annual", "period": latest["period"], "value": latest["revenue"]}
        return latest["revenue"], detail

    if quarterly:
        q_sorted = sorted(quarterly, key=lambda f: f["period"], reverse=True)
        n = len(q_sorted)
        ttm = sum(f["revenue"] for f in q_sorted) / n * 4
        detail = {"method": f"annualized_{n}q", "quarters": [f["period"] for f in q_sorted], "value": ttm}
        return ttm, detail

    return None, {}


def compute_revenue_cagr(fundamentals):
    if not fundamentals:
        return None, {}
    annual = [f for f in fundamentals if "Q" not in f["period"] and f["revenue"] and f["revenue"] > 0]
    annual.sort(key=lambda f: f["period"])

    if len(annual) >= 2:
        oldest, newest = annual[0], annual[-1]
        y_old = int(oldest["period"].replace("CY", ""))
        y_new = int(newest["period"].replace("CY", ""))
        years = y_new - y_old
        if years > 0 and oldest["revenue"] > 0:
            cagr = (newest["revenue"] / oldest["revenue"]) ** (1 / years) - 1
            detail = {
                "method": f"annual_{years}yr",
                "from": f"{oldest['period']}:{oldest['revenue']/1e6:.0f}M",
                "to": f"{newest['period']}:{newest['revenue']/1e6:.0f}M",
                "years": years, "value": round(cagr, 4)
            }
            return cagr, detail

    quarterly = [f for f in fundamentals if "Q" in f["period"] and f["revenue"] and f["revenue"] > 0]
    quarterly.sort(key=lambda f: f["period"], reverse=True)

    yoy_vals = [f["revenue_yoy"] / 100 for f in quarterly if f.get("revenue_yoy") is not None]
    if yoy_vals:
        median_yoy = sorted(yoy_vals)[len(yoy_vals) // 2]
        detail = {"method": "median_quarterly_yoy", "n_points": len(yoy_vals), "value": round(median_yoy, 4)}
        return median_yoy, detail

    if len(quarterly) >= 5:
        latest = quarterly[0]["revenue"]
        year_ago = quarterly[3]["revenue"] if len(quarterly) >= 4 else quarterly[-1]["revenue"]
        if year_ago > 0:
            yoy = latest / year_ago - 1
            detail = {"method": "q_over_q_yoy", "latest": quarterly[0]["period"],
                       "compare": quarterly[3]["period"] if len(quarterly) >= 4 else quarterly[-1]["period"],
                       "value": round(yoy, 4)}
            return yoy, detail

    return None, {}


def compute_gross_margin(fundamentals):
    recent = [f for f in fundamentals if f.get("gross_margin") is not None]
    if not recent:
        return None
    recent.sort(key=lambda f: f["period"], reverse=True)
    vals = [f["gross_margin"] / 100 for f in recent[:4]]
    return sum(vals) / len(vals)


def growth_decay(cagr):
    abs_g = abs(cagr)
    if abs_g > 0.80:
        return 0.50
    if abs_g > 0.50:
        return 0.60
    if abs_g > 0.25:
        return 0.75
    if abs_g > 0.10:
        return 0.85
    return 0.95


def terminal_ps(y3_growth, gross_margin):
    base = 3.0
    growth_adj = y3_growth * 15.0
    margin_adj = max(0, (gross_margin - 0.30)) * 10.0
    return max(1.5, min(25.0, base + growth_adj + margin_adj))


def project_scenario(ttm_rev, raw_cagr, current_mcap, scenario_mult):
    effective_cagr = max(-0.20, min(1.00, raw_cagr * scenario_mult))
    decay = growth_decay(raw_cagr)

    g1 = max(-0.10, effective_cagr)
    g2 = max(-0.10, effective_cagr * decay)
    g3 = max(-0.10, effective_cagr * decay * decay)

    rev_y1 = ttm_rev * (1 + g1)
    rev_y2 = rev_y1 * (1 + g2)
    rev_y3 = rev_y2 * (1 + g3)

    return {
        "rev_y3": rev_y3,
        "y1_growth": g1, "y2_growth": g2, "y3_growth": g3,
        "decay": decay,
    }


def valuate_ticker(ticker, fundamentals, valuation):
    if not valuation or not valuation.get("market_cap"):
        return None

    current_mcap = valuation["market_cap"]

    ttm_rev, ttm_detail = compute_ttm_revenue(fundamentals)
    if not ttm_rev or ttm_rev <= 0:
        return None

    cagr, cagr_detail = compute_revenue_cagr(fundamentals)
    if cagr is None:
        return None
    cagr_capped = max(-0.20, min(1.00, cagr))

    gm = compute_gross_margin(fundamentals)
    if gm is None:
        gm = 0.40

    scenarios = {}
    if cagr_capped < 0:
        mults = [("bear", 1.4, 0.85), ("base", 1.0, 1.0), ("bull", 0.5, 1.15)]
    else:
        mults = [("bear", 0.6, 0.85), ("base", 1.0, 1.0), ("bull", 1.3, 1.15)]

    for name, rev_mult, ps_mult in mults:
        proj = project_scenario(ttm_rev, cagr_capped, current_mcap, rev_mult)
        ps = terminal_ps(proj["y3_growth"], gm) * ps_mult
        ps = max(1.5, min(25.0, ps))
        potential = proj["rev_y3"] * ps
        upside = (potential / current_mcap - 1) * 100 if current_mcap > 0 else None
        scenarios[name] = {
            "rev_y3": proj["rev_y3"],
            "ps": ps,
            "mcap": potential,
            "upside": upside,
            "projection": proj,
        }

    tier = mcap_tier(current_mcap)
    b = current_mcap / 1e9
    is_sweet = 1 if 5 <= b <= 50 else 0
    has_path = 1 if scenarios["bull"]["mcap"] >= 100e9 else 0
    micro_warn = 1 if b < 2 else 0

    calc_details = {
        "ttm_revenue": ttm_detail,
        "cagr": cagr_detail,
        "gross_margin": round(gm, 4),
        "bear_projection": scenarios["bear"]["projection"],
        "base_projection": scenarios["base"]["projection"],
        "bull_projection": scenarios["bull"]["projection"],
        "terminal_ps": {
            "base_const": 3.0,
            "growth_adj_formula": "y3_growth * 15.0",
            "margin_adj_formula": "max(0, (gm - 0.30)) * 10.0",
            "cap": "[1.5, 25.0]",
        }
    }

    return {
        "current_mcap": current_mcap,
        "current_tier": tier,
        "ttm_revenue": ttm_rev,
        "revenue_cagr": cagr_capped,
        "gross_margin": gm,
        "bear_rev_y3": scenarios["bear"]["rev_y3"],
        "bear_ps": scenarios["bear"]["ps"],
        "bear_mcap": scenarios["bear"]["mcap"],
        "bear_upside": scenarios["bear"]["upside"],
        "base_rev_y3": scenarios["base"]["rev_y3"],
        "base_ps": scenarios["base"]["ps"],
        "base_mcap": scenarios["base"]["mcap"],
        "base_upside": scenarios["base"]["upside"],
        "bull_rev_y3": scenarios["bull"]["rev_y3"],
        "bull_ps": scenarios["bull"]["ps"],
        "bull_mcap": scenarios["bull"]["mcap"],
        "bull_upside": scenarios["bull"]["upside"],
        "is_sweet_spot": is_sweet,
        "has_100b_path": has_path,
        "micro_warning": micro_warn,
        "calc_details": calc_details,
    }


def fmt_b(n):
    if n is None:
        return "N/A"
    return f"${n/1e9:.1f}B" if n >= 1e9 else f"${n/1e6:.0f}M"


def run(tickers=None):
    conn = db.get_conn()
    if tickers:
        wl = [{"ticker": t} for t in tickers]
    else:
        wl = db.get_watchlist(conn)

    success, skip = 0, 0
    for item in wl:
        ticker = item["ticker"]
        fundamentals = db.get_fundamentals(ticker, limit=8, conn=conn)
        valuation = db.get_valuation(ticker, conn=conn)

        result = valuate_ticker(ticker, fundamentals, valuation)
        if not result:
            print(f"  {ticker:8s}  SKIP — insufficient data")
            skip += 1
            continue

        db.save_valuation_model(ticker, result, conn=conn)
        success += 1

        tier_icon = {"Mega": "🏛️", "Large": "🔵", "Mid": "🟢", "Small": "🟡", "Micro": "🔴"}.get(result["current_tier"], "⚪")
        flags = ""
        if result["is_sweet_spot"]:
            flags += " ✓sweet"
        if result["has_100b_path"]:
            flags += " ✓$100B路径"
        if result["micro_warning"]:
            flags += " ⚠️micro"

        print(f"  {ticker:8s}  {tier_icon} {result['current_tier']:6s} {fmt_b(result['current_mcap']):>10s}"
              f"  CAGR {result['revenue_cagr']*100:+.0f}%  GM {result['gross_margin']*100:.0f}%"
              f"  → Bear {fmt_b(result['bear_mcap']):>10s}"
              f"  Base {fmt_b(result['base_mcap']):>10s}"
              f"  Bull {fmt_b(result['bull_mcap']):>10s}"
              f"{flags}")

    conn.commit()
    conn.close()
    print(f"\n计算完成: {success}个标的, {skip}个跳过")


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else None
    print("=== Chokepoint 估值模型 ===")
    run(tickers)
