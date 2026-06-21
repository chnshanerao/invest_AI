#!/usr/bin/env python3
"""
SEC Form 4 Insider Transaction Monitor — 内部人交易监控

从SEC EDGAR获取Form 4（内部人交易报告），解析XML，分类交易类型，
识别CEO/CFO买入（强信号）和异常卖出模式。

学术依据: Cohen, Malloy & Pomorski (2012)
- Insider buying: +4.5-7.5% abnormal returns, 55-60% win rate
- Routine selling (10b5-1): zero predictive power
- Opportunistic selling: weak -3~5% signal

用法：
  python3 insider_monitor.py              # 扫描全部标的
  python3 insider_monitor.py COHR LEU     # 扫描指定标的
  python3 insider_monitor.py --dingtalk   # 推送钉钉
  python3 insider_monitor.py --history    # 30天交易汇总
"""

import argparse
import base64
import hashlib
import hmac as hmac_mod
import json
import os
import re
import ssl
import sys
import time

try:
    import monitor_db as mdb
    _HAS_DB = True
except ImportError:
    _HAS_DB = False
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# ============================================================
# 配置
# ============================================================

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE, "state")
STATE_FILE = os.path.join(STATE_DIR, "insider_state.json")
CIK_CACHE = os.path.join(STATE_DIR, "10k_cache", "_cik_map.json")

import config_helper as cfg
DINGTALK_WEBHOOK, DINGTALK_SECRET = cfg.get_dingtalk_config()
MONITOR_TICKERS = cfg.get_watchlist_tickers()

C_SUITE_TITLES = [
    "ceo", "chief executive", "president",
    "cfo", "chief financial",
    "coo", "chief operating",
    "cto", "chief technology",
    "chairman", "vice chairman",
]

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

# ============================================================
# HTTP + SEC EDGAR
# ============================================================

def _http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": cfg.get_sec_email(),
        "Accept-Encoding": "identity",
    })
    resp = urllib.request.urlopen(req, context=_ctx, timeout=timeout)
    return resp.read()


def get_cik(ticker):
    if ticker == "HYNIX":
        return None
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


def get_recent_form4s(ticker, days=30):
    cik = get_cik(ticker)
    if not cik:
        return []
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    data = json.loads(_http_get(url))

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    docs = filings.get("primaryDocument", [])

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    results = []
    for i in range(len(forms)):
        if forms[i] not in ("4", "4/A"):
            continue
        if dates[i] < cutoff:
            break
        results.append({
            "form": forms[i],
            "date": dates[i],
            "accession": accessions[i],
            "doc": docs[i],
            "cik": cik,
        })
    return results


def fetch_form4_xml(cik, accession, doc):
    acc_nodash = accession.replace("-", "")
    if "/" in doc:
        raw_doc = doc.split("/")[-1]
    else:
        raw_doc = doc
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{raw_doc}"
    return _http_get(url).decode("utf-8", errors="replace")

# ============================================================
# Form 4 XML Parser
# ============================================================

def parse_form4(xml_text):
    ns = {"": ""}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        cleaned = re.sub(r'<\?xml[^>]*\?>', '', xml_text).strip()
        cleaned = re.sub(r'xmlns="[^"]*"', '', cleaned)
        try:
            root = ET.fromstring(cleaned)
        except ET.ParseError:
            return None

    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]

    owner = root.find(".//reportingOwner")
    if owner is None:
        return None

    owner_id = owner.find("reportingOwnerId")
    name = ""
    if owner_id is not None:
        n = owner_id.find("rptOwnerName")
        if n is not None and n.text:
            name = n.text.strip()

    rel = owner.find("reportingOwnerRelationship")
    title = ""
    is_officer = False
    is_director = False
    is_ten_pct = False
    if rel is not None:
        t = rel.find("officerTitle")
        if t is not None and t.text:
            title = t.text.strip()
        io = rel.find("isOfficer")
        if io is not None and io.text:
            is_officer = io.text.strip() in ("1", "true")
        id_ = rel.find("isDirector")
        if id_ is not None and id_.text:
            is_director = id_.text.strip() in ("1", "true")
        tp = rel.find("isTenPercentOwner")
        if tp is not None and tp.text:
            is_ten_pct = tp.text.strip() in ("1", "true")

    if not title:
        if is_director:
            title = "Director"
        elif is_ten_pct:
            title = "10% Owner"

    transactions = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        code_elem = tx.find(".//transactionCoding/transactionCode")
        date_elem = tx.find(".//transactionDate/value")
        shares_elem = tx.find(".//transactionAmounts/transactionShares/value")
        price_elem = tx.find(".//transactionAmounts/transactionPricePerShare/value")
        ad_elem = tx.find(".//transactionAmounts/transactionAcquiredDisposedCode/value")
        post_elem = tx.find(".//postTransactionAmounts/sharesOwnedFollowingTransaction/value")

        code = code_elem.text.strip() if code_elem is not None and code_elem.text else ""
        date = date_elem.text.strip() if date_elem is not None and date_elem.text else ""
        try:
            shares = float(shares_elem.text.strip()) if shares_elem is not None and shares_elem.text else 0
        except ValueError:
            shares = 0
        try:
            price = float(price_elem.text.strip()) if price_elem is not None and price_elem.text else 0
        except ValueError:
            price = 0
        ad = ad_elem.text.strip() if ad_elem is not None and ad_elem.text else ""
        try:
            post = float(post_elem.text.strip()) if post_elem is not None and post_elem.text else 0
        except ValueError:
            post = 0

        if code in ("P", "S", "F", "M", "A", "G", "J", "C"):
            transactions.append({
                "code": code,
                "date": date,
                "shares": shares,
                "price": price,
                "value": round(shares * price, 2),
                "acquired_disposed": ad,
                "post_holdings": post,
            })

    return {
        "insider": name,
        "title": title,
        "is_officer": is_officer,
        "is_director": is_director,
        "is_ten_pct": is_ten_pct,
        "transactions": transactions,
    }

# ============================================================
# Transaction Classification
# ============================================================

def is_c_suite(title):
    t = title.lower()
    return any(cs in t for cs in C_SUITE_TITLES)


def classify_transaction(tx):
    code = tx["code"]
    if code == "P":
        return "BUY"
    if code == "S":
        return "SELL"
    if code in ("F", "M", "A", "G", "J", "C"):
        return "IGNORE"
    return "UNKNOWN"


def is_routine_sell(insider_name, ticker, all_sells):
    if len(all_sells) < 3:
        return False
    shares_list = [s["shares"] for s in all_sells]
    avg_shares = sum(shares_list) / len(shares_list)
    if avg_shares == 0:
        return False
    deviations = [abs(s - avg_shares) / avg_shares for s in shares_list]
    avg_dev = sum(deviations) / len(deviations)
    if avg_dev < 0.15:
        return True
    dates = sorted(s["date"] for s in all_sells)
    if len(dates) >= 3:
        intervals = []
        for i in range(1, len(dates)):
            try:
                d1 = datetime.strptime(dates[i-1], "%Y-%m-%d")
                d2 = datetime.strptime(dates[i], "%Y-%m-%d")
                intervals.append((d2 - d1).days)
            except ValueError:
                pass
        if intervals and len(intervals) >= 2:
            avg_interval = sum(intervals) / len(intervals)
            if avg_interval > 0:
                interval_devs = [abs(iv - avg_interval) / avg_interval for iv in intervals]
                if sum(interval_devs) / len(interval_devs) < 0.25:
                    return True
    return False

# ============================================================
# Insider Score Computation
# ============================================================

def compute_insider_score(ticker, form4_results):
    buys = []
    sells = []
    all_by_insider = {}

    for f4 in form4_results:
        if f4 is None:
            continue
        insider = f4["insider"]
        title = f4["title"]
        for tx in f4["transactions"]:
            cls = classify_transaction(tx)
            entry = {**tx, "insider": insider, "title": title,
                     "is_officer": f4["is_officer"], "is_director": f4["is_director"],
                     "is_ten_pct": f4["is_ten_pct"]}
            if cls == "BUY":
                buys.append(entry)
            elif cls == "SELL":
                sells.append(entry)
                all_by_insider.setdefault(insider, []).append(entry)

    score = 0
    details = []

    if buys:
        c_suite_buys = [b for b in buys if is_c_suite(b["title"])]
        total_buy_val = sum(b["value"] for b in buys)
        if c_suite_buys:
            cs_val = sum(b["value"] for b in c_suite_buys)
            score += 15
            names = set(b["insider"] for b in c_suite_buys)
            details.append(f"+高管买入${cs_val:,.0f}({','.join(names)})")
        elif total_buy_val > 0:
            score += 8
            details.append(f"+内部人买入${total_buy_val:,.0f}")

        unique_buyers = set(b["insider"] for b in buys)
        if len(unique_buyers) >= 3:
            score += 5
            details.append(f"+集群买入({len(unique_buyers)}人)")

    sell_penalty = 0
    if sells:
        for insider, insider_sells in all_by_insider.items():
            title = insider_sells[0]["title"]
            if not is_c_suite(title):
                continue
            total_sell_val = sum(s["value"] for s in insider_sells)
            routine = is_routine_sell(insider, ticker, insider_sells)
            if routine:
                details.append(f"⚪{insider}卖${total_sell_val:,.0f}(routine)")
            else:
                if total_sell_val > 500000:
                    sell_penalty += 10
                    details.append(f"-{insider}异常卖出${total_sell_val:,.0f}")
                elif total_sell_val > 100000:
                    sell_penalty += 5
                    details.append(f"-{insider}卖出${total_sell_val:,.0f}")
        score -= min(sell_penalty, 15)

    if not buys and not sells:
        details.append("⚪无近期内部人交易")

    net_buy = sum(b["value"] for b in buys) - sum(s["value"] for s in sells)
    summary = {
        "buy_count": len(buys),
        "sell_count": len(sells),
        "buy_value": sum(b["value"] for b in buys),
        "sell_value": sum(s["value"] for s in sells),
        "net": net_buy,
        "buys": buys,
        "sells": sells,
    }

    return score, details, summary

# ============================================================
# State Management
# ============================================================

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "last_check": {},
            "seen_filings": {},
            "insider_scores": {},
            "alerts_sent": {},
        }


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ============================================================
# DingTalk
# ============================================================

def dingtalk_sign():
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
    hmac_code = hmac_mod.new(
        DINGTALK_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote(base64.b64encode(hmac_code).decode("utf-8"))
    return timestamp, sign


def send_dingtalk(report_md, title="内部人交易监控"):
    timestamp, sign = dingtalk_sign()
    url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": report_md},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=_ctx) as resp:
            result = json.loads(resp.read().decode())
        if result.get("errcode") == 0:
            return True
    except Exception as e:
        print(f"  [DingTalk ERROR] {e}")
    return False

# ============================================================
# Report Formatting
# ============================================================

def format_insider_alert(ticker, insider, title, tx_type, value, post_holdings, summary):
    if tx_type == "BUY":
        emoji = "🟢"
        label = "买入"
        verdict = "强烈正面信号（CEO真金白银，学术胜率55-60%）"
    else:
        emoji = "🔴"
        label = "异常卖出"
        verdict = "负面信号（非routine卖出，需关注）"

    lines = [
        f"### {emoji} 内部人{label} — {ticker}",
        "",
        f"**{insider}** ({title}) {label}",
        f"总值: ${value:,.0f} | 交易后持仓: {post_holdings:,.0f}股",
        f"近30天: {summary['buy_count']}买/{summary['sell_count']}卖",
        "",
        f"> {verdict}",
    ]
    return "\n".join(lines)


def format_history_report(all_results):
    lines = [
        f"### 👤 内部人交易30天汇总 ({datetime.now().strftime('%m/%d')})",
        "",
    ]

    buy_alerts = []
    sell_alerts = []
    neutral = []

    for ticker, (score, details, summary) in all_results.items():
        if summary["buy_count"] > 0 and score > 0:
            total_buy = summary["buy_value"]
            buyers = set(b["insider"] for b in summary["buys"])
            buy_alerts.append(f"**{ticker}**: {summary['buy_count']}笔买入 ${total_buy:,.0f} ({', '.join(buyers)})")
        elif score < 0:
            total_sell = summary["sell_value"]
            sell_alerts.append(f"**{ticker}**: {summary['sell_count']}笔卖出 ${total_sell:,.0f} | {' | '.join(details)}")
        else:
            if summary["buy_count"] + summary["sell_count"] > 0:
                neutral.append(f"**{ticker}**: {summary['buy_count']}买/{summary['sell_count']}卖 | {' | '.join(details)}")
            else:
                neutral.append(f"**{ticker}**: 无交易")

    if buy_alerts:
        lines.append("#### 🟢 买入信号")
        for a in buy_alerts:
            lines.append(f"- {a}")
        lines.append("")

    if sell_alerts:
        lines.append("#### 🔴 异常卖出")
        for a in sell_alerts:
            lines.append(f"- {a}")
        lines.append("")

    if neutral:
        lines.append("#### ⚪ 正常/无交易")
        for n in neutral:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("---")
    lines.append("👤 内部人交易监控 | SEC Form 4")
    return "\n".join(lines)


def format_daily_digest(all_results):
    has_signal = any(score != 0 for score, _, _ in all_results.values())
    if not has_signal:
        return None

    lines = ["#### 👤 内部人动向"]
    for ticker, (score, details, summary) in sorted(all_results.items()):
        if score > 0:
            lines.append(f"- {ticker}: {' | '.join(details)} ✅")
        elif score < 0:
            lines.append(f"- {ticker}: {' | '.join(details)} ⚠️")
        else:
            if summary["buy_count"] + summary["sell_count"] > 0:
                lines.append(f"- {ticker}: {' | '.join(details)} ⚪")
    return "\n".join(lines)

# ============================================================
# Main Scan Logic
# ============================================================

def scan_ticker(ticker, state, days=30, verbose=True):
    if ticker == "HYNIX":
        if verbose:
            print(f"  {ticker}: 港股标的，跳过SEC监控")
        return None

    if verbose:
        print(f"  {ticker}: 获取Form 4...")

    try:
        form4_list = get_recent_form4s(ticker, days=days)
    except Exception as e:
        print(f"  {ticker}: [ERROR] {e}")
        return None

    if not form4_list:
        if verbose:
            print(f"  {ticker}: 近{days}天无Form 4")
        return 0, ["⚪无近期Form 4"], {"buy_count": 0, "sell_count": 0,
                                        "buy_value": 0, "sell_value": 0, "net": 0,
                                        "buys": [], "sells": []}

    seen = set(state.get("seen_filings", {}).get(ticker, []))
    new_filings = [f for f in form4_list if f["accession"] not in seen]

    all_parsed = []
    for filing in form4_list:
        try:
            xml = fetch_form4_xml(filing["cik"], filing["accession"], filing["doc"])
            parsed = parse_form4(xml)
            if parsed:
                all_parsed.append(parsed)
            time.sleep(0.15)
        except Exception as e:
            if verbose:
                print(f"    [ERROR] {filing['accession']}: {e}")

    if verbose:
        print(f"  {ticker}: {len(form4_list)}个Form 4, {len(all_parsed)}个解析成功")

    score, details, summary = compute_insider_score(ticker, all_parsed)

    state.setdefault("seen_filings", {})[ticker] = [f["accession"] for f in form4_list]
    state.setdefault("last_check", {})[ticker] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    state.setdefault("insider_scores", {})[ticker] = {
        "score": score,
        "details": details,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "buy_count": summary["buy_count"],
        "sell_count": summary["sell_count"],
        "buy_value": summary["buy_value"],
        "sell_value": summary["sell_value"],
    }

    if _HAS_DB:
        try:
            mdb.save_insider_score(
                ticker, score, details,
                summary["buy_count"], summary["sell_count"],
                summary["buy_value"], summary["sell_value"])
            for parsed in all_parsed:
                for tx in parsed["transactions"]:
                    mdb.save_insider_tx(
                        ticker=ticker,
                        filing_date=tx.get("date", ""),
                        accession=parsed.get("accession", ""),
                        insider_name=parsed.get("insider", ""),
                        title=parsed.get("title", ""),
                        is_officer=parsed.get("is_officer", False),
                        is_director=parsed.get("is_director", False),
                        tx_type=classify_transaction(tx),
                        tx_code=tx.get("code", ""),
                        shares=tx.get("shares", 0),
                        price=tx.get("price", 0),
                        value=tx.get("value", 0),
                        post_holdings=tx.get("post_holdings"),
                        is_routine=1 if is_routine_sell(parsed.get("insider",""), ticker, [tx]) else 0,
                    )
        except Exception:
            pass

    new_alerts = []
    if new_filings and all_parsed:
        for parsed in all_parsed:
            for tx in parsed["transactions"]:
                cls = classify_transaction(tx)
                if cls == "BUY" and is_c_suite(parsed["title"]) and tx["value"] > 50000:
                    alert_key = f"{ticker}_{parsed['insider']}_buy_{tx['date']}"
                    if alert_key not in state.get("alerts_sent", {}):
                        new_alerts.append(format_insider_alert(
                            ticker, parsed["insider"], parsed["title"],
                            "BUY", tx["value"], tx["post_holdings"], summary))
                        state.setdefault("alerts_sent", {})[alert_key] = True
                elif cls == "SELL" and is_c_suite(parsed["title"]):
                    if not is_routine_sell(parsed["insider"], ticker,
                                          [s for s in summary["sells"]
                                           if s["insider"] == parsed["insider"]]):
                        if tx["value"] > 500000:
                            alert_key = f"{ticker}_{parsed['insider']}_sell_{tx['date']}"
                            if alert_key not in state.get("alerts_sent", {}):
                                new_alerts.append(format_insider_alert(
                                    ticker, parsed["insider"], parsed["title"],
                                    "SELL", tx["value"], tx["post_holdings"], summary))
                                state.setdefault("alerts_sent", {})[alert_key] = True

    return score, details, summary, new_alerts


def run_scan(tickers=None, dingtalk=False, history=False, days=30):
    if tickers is None:
        tickers = [t for t in MONITOR_TICKERS if t != "HYNIX"]

    state = load_state()
    all_results = {}
    all_alerts = []

    print(f"内部人交易监控 — 扫描 {len(tickers)} 个标的")
    print(f"回溯窗口: {days}天\n")

    for ticker in tickers:
        try:
            result = scan_ticker(ticker, state, days=days)
            if result is None:
                continue
            if len(result) == 4:
                score, details, summary, new_alerts = result
                all_alerts.extend(new_alerts)
            else:
                score, details, summary = result
            all_results[ticker] = (score, details, summary)

            detail_str = " | ".join(details)
            if score > 0:
                print(f"  → 🟢 信号分: +{score} | {detail_str}")
            elif score < 0:
                print(f"  → 🔴 信号分: {score} | {detail_str}")
            else:
                print(f"  → ⚪ 信号分: 0 | {detail_str}")

        except Exception as e:
            print(f"  {ticker}: [ERROR] {e}")
        time.sleep(0.3)

    save_state(state)

    if history:
        report = format_history_report(all_results)
        print(f"\n{report}")
        if dingtalk:
            send_dingtalk(report, "内部人交易汇总")
            print("  → 已推送钉钉")
    else:
        digest = format_daily_digest(all_results)
        if dingtalk and all_alerts:
            for alert in all_alerts:
                send_dingtalk(alert, "内部人交易警报")
                print(f"  → 实时警报已推送")
                time.sleep(1)
        if dingtalk and digest:
            send_dingtalk(digest, "内部人动向")
            print("  → 每日摘要已推送")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="SEC Form 4 Insider Transaction Monitor")
    parser.add_argument("tickers", nargs="*", help="Ticker symbols to scan")
    parser.add_argument("--dingtalk", action="store_true", help="Push alerts to DingTalk")
    parser.add_argument("--history", action="store_true", help="Show 30-day transaction summary")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers] if args.tickers else None
    run_scan(tickers=tickers, dingtalk=args.dingtalk, history=args.history, days=args.days)


if __name__ == "__main__":
    main()
