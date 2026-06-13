#!/usr/bin/env python3
"""
fundamentals_fetcher.py — 基本面+估值数据采集

数据源:
  1. SEC EDGAR XBRL API → 季度Revenue/EPS/GrossProfit/NetIncome
  2. Sina Finance hq.sinajs.cn → 实时P/E/市值/52周高低

用法:
  python3 fundamentals_fetcher.py              # 采集全部watchlist
  python3 fundamentals_fetcher.py COHR LITE    # 采集指定标的
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor_db as mdb

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

CIK_CACHE = os.path.join(mdb.STATE_DIR, "10k_cache", "_cik_map.json")


def _http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "keji.rx research@example.com",
        "Accept-Encoding": "identity",
    })
    return urllib.request.urlopen(req, context=_ctx, timeout=timeout).read()


def get_cik(ticker):
    if os.path.exists(CIK_CACHE):
        with open(CIK_CACHE) as f:
            cik_map = json.load(f)
        if ticker.upper() in cik_map:
            return cik_map[ticker.upper()]
    data = _http_get("https://www.sec.gov/files/company_tickers.json")
    tickers_data = json.loads(data)
    cik_map = {}
    for v in tickers_data.values():
        cik_map[v["ticker"].upper()] = str(v["cik_str"])
    os.makedirs(os.path.dirname(CIK_CACHE), exist_ok=True)
    with open(CIK_CACHE, "w") as f:
        json.dump(cik_map, f)
    return cik_map.get(ticker.upper())


# ---- SEC XBRL Fundamentals ----

XBRL_METRICS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "shares": ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"],
}


def fetch_xbrl_fundamentals(ticker):
    cik = get_cik(ticker)
    if not cik:
        print(f"  {ticker}: CIK not found, skipping")
        return False

    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"

    try:
        data = json.loads(_http_get(url))
    except Exception as e:
        print(f"  {ticker}: XBRL fetch failed: {e}")
        return False

    facts = data.get("facts", {}).get("us-gaap", {})
    if not facts:
        print(f"  {ticker}: No us-gaap facts found")
        return False

    def get_quarterly_values(metric_names, unit_key="USD"):
        for name in metric_names:
            if name not in facts:
                continue
            entries = facts[name].get("units", {}).get(unit_key, [])
            quarterly = [e for e in entries
                         if e.get("form") in ("10-K", "10-Q", "20-F")
                         and "frame" in e
                         and ("Q" in e["frame"] or "I" not in e["frame"])]
            quarterly.sort(key=lambda x: x.get("end", ""))
            return quarterly[-8:] if quarterly else []
        return []

    rev_entries = get_quarterly_values(XBRL_METRICS["revenue"])
    eps_entries = get_quarterly_values(XBRL_METRICS["eps"], "USD/shares")
    gp_entries = get_quarterly_values(XBRL_METRICS["gross_profit"])
    cor_entries = get_quarterly_values(XBRL_METRICS["cost_of_revenue"])
    ni_entries = get_quarterly_values(XBRL_METRICS["net_income"])
    shares_entries = get_quarterly_values(XBRL_METRICS["shares"], "shares")

    periods_saved = set()
    conn = mdb.get_conn()

    all_entries = []
    for entries, field in [(rev_entries, "revenue"), (eps_entries, "eps"),
                           (gp_entries, "gross_profit")]:
        for e in entries:
            frame = e.get("frame", "")
            if frame and frame not in periods_saved:
                periods_saved.add(frame)
                all_entries.append((frame, e.get("end", "")))

    rev_by_period = {e["frame"]: e["val"] for e in rev_entries if "frame" in e}
    eps_by_period = {e["frame"]: e["val"] for e in eps_entries if "frame" in e}
    gp_by_period = {e["frame"]: e["val"] for e in gp_entries if "frame" in e}
    cor_by_period = {e["frame"]: e["val"] for e in cor_entries if "frame" in e}
    ni_by_period = {e["frame"]: e["val"] for e in ni_entries if "frame" in e}
    shares_by_period = {e["frame"]: e["val"] for e in shares_entries if "frame" in e}

    count = 0
    for period in sorted(periods_saved)[-8:]:
        rev = rev_by_period.get(period)
        gp = gp_by_period.get(period)
        cor = cor_by_period.get(period)
        gross_margin = (gp / rev * 100) if (rev and gp and rev > 0) else None

        rev_yoy = None
        if rev and "Q" in period:
            year = int(re.search(r'CY(\d{4})', period).group(1)) if re.search(r'CY(\d{4})', period) else None
            q = re.search(r'Q(\d)', period)
            if year and q:
                prev_period = f"CY{year-1}Q{q.group(1)}"
                prev_rev = rev_by_period.get(prev_period)
                if prev_rev and prev_rev > 0:
                    rev_yoy = (rev - prev_rev) / prev_rev * 100

        mdb.save_fundamentals(
            ticker=ticker, period=period,
            revenue=rev, eps=eps_by_period.get(period),
            gross_profit=gp, cost_of_revenue=cor,
            net_income=ni_by_period.get(period),
            shares_outstanding=shares_by_period.get(period),
            revenue_yoy=rev_yoy, gross_margin=gross_margin,
            conn=conn,
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"  {ticker}: {count} quarterly records saved")
    return True


# ---- Sina Valuation ----

def fetch_valuation_batch(tickers):
    us_tickers = []
    conn = mdb.get_conn()

    for ticker in tickers:
        info = mdb.get_ticker_info(ticker, conn)
        if info and info.get("source") == "tencent_hk":
            continue
        us_tickers.append(ticker)

    if not us_tickers:
        conn.close()
        return

    symbols = ",".join(f"gb_{t.lower()}" for t in us_tickers)
    url = f"https://hq.sinajs.cn/list={symbols}"

    try:
        req = urllib.request.Request(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        })
        raw = urllib.request.urlopen(req, context=_ctx, timeout=15).read()
        text = raw.decode("gbk", errors="replace")
    except Exception as e:
        print(f"  Sina valuation fetch failed: {e}")
        conn.close()
        return

    lines = text.strip().split("\n")
    for i, line in enumerate(lines):
        if "=\"" not in line:
            continue
        fields = line.split("\"")[1].split(",")
        if len(fields) < 14:
            continue

        ticker = us_tickers[i] if i < len(us_tickers) else None
        if not ticker:
            continue

        try:
            price = float(fields[1]) if fields[1] else None
            market_cap = float(fields[12]) if fields[12] else None
            pe = float(fields[13]) if fields[13] else None
            high_52w = float(fields[8]) if fields[8] else None
            low_52w = float(fields[9]) if fields[9] else None
        except (ValueError, IndexError):
            continue

        if not price:
            continue

        fundamentals = mdb.get_fundamentals(ticker, limit=4, conn=conn)
        annual_rev = None
        if fundamentals:
            annual_entries = [f for f in fundamentals if f.get("revenue") and "Q" not in (f.get("period") or "")]
            if annual_entries:
                annual_rev = annual_entries[-1]["revenue"]
            else:
                q_revs = [f["revenue"] for f in fundamentals[-4:] if f.get("revenue")]
                if len(q_revs) >= 4:
                    annual_rev = sum(q_revs)

        ps_ttm = (market_cap / annual_rev) if (market_cap and annual_rev and annual_rev > 0) else None

        mdb.save_valuation(ticker, price, market_cap, pe, ps_ttm,
                           high_52w, low_52w, conn=conn)
        ps_str = f"{ps_ttm:.1f}" if ps_ttm else "—"
        from_high = ((price - high_52w) / high_52w * 100) if high_52w else 0
        print(f"  {ticker}: P=${price:.1f} PE={pe} PS={ps_str} from_high={from_high:.0f}%")

    conn.commit()
    conn.close()


# ---- Main ----

def run(tickers=None):
    mdb.init_db()

    if not tickers:
        wl = mdb.get_watchlist()
        tickers = [w["ticker"] for w in wl]

    print(f"基本面+估值采集 — {len(tickers)} 个标的\n")

    print("1. SEC XBRL 季度基本面:")
    for ticker in tickers:
        info = mdb.get_ticker_info(ticker)
        if info and info.get("source") == "tencent_hk":
            print(f"  {ticker}: HK ETF, skipping XBRL")
            continue
        fetch_xbrl_fundamentals(ticker)
        time.sleep(0.2)

    print("\n2. Sina 实时估值:")
    fetch_valuation_batch(tickers)

    print("\nDone.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fundamentals + Valuation Fetcher")
    parser.add_argument("tickers", nargs="*", help="Tickers to fetch")
    args = parser.parse_args()
    tickers = [t.upper() for t in args.tickers] if args.tickers else None
    run(tickers)
