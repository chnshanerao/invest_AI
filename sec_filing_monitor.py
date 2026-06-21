#!/usr/bin/env python3
"""
SEC Filing Event Monitor — SEC公告事件监控

监控EDGAR上的8-K/10-K/10-Q/SC 13D/S-3等公告事件，
分类事件类型并评估对投资决策的影响。

用法：
  python3 sec_filing_monitor.py              # 扫描全部标的
  python3 sec_filing_monitor.py COHR LEU     # 扫描指定标的
  python3 sec_filing_monitor.py --dingtalk   # 推送钉钉
  python3 sec_filing_monitor.py --days 14    # 回溯14天
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
from datetime import datetime, timedelta

# ============================================================
# 配置
# ============================================================

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE, "state")
STATE_FILE = os.path.join(STATE_DIR, "filing_state.json")
CIK_CACHE = os.path.join(STATE_DIR, "10k_cache", "_cik_map.json")

import config_helper as cfg
DINGTALK_WEBHOOK, DINGTALK_SECRET = cfg.get_dingtalk_config()
MONITOR_TICKERS = cfg.get_watchlist_tickers()

EVENT_TYPES = {
    "8-K":    {"importance": "HIGH",   "label": "重大事件"},
    "8-K/A":  {"importance": "HIGH",   "label": "重大事件修正"},
    "10-K":   {"importance": "MEDIUM", "label": "年报"},
    "10-K/A": {"importance": "MEDIUM", "label": "年报修正"},
    "10-Q":   {"importance": "MEDIUM", "label": "季报"},
    "10-Q/A": {"importance": "MEDIUM", "label": "季报修正"},
    "20-F":   {"importance": "MEDIUM", "label": "年报(外国)"},
    "SC 13D": {"importance": "HIGH",   "label": "大股东主动增持"},
    "SC 13D/A":{"importance": "HIGH",  "label": "大股东增持修正"},
    "SC 13G": {"importance": "LOW",    "label": "大股东被动持仓"},
    "S-3":    {"importance": "HIGH",   "label": "增发登记"},
    "S-1":    {"importance": "HIGH",   "label": "IPO/增发"},
    "DEF 14A":{"importance": "LOW",    "label": "委托投票书"},
}

ITEM_MAP = {
    "1.01": ("MATERIAL_CONTRACT", "重大合同"),
    "1.02": ("BANKRUPTCY", "破产/接管"),
    "2.01": ("ACQUISITION", "收购/处置资产"),
    "2.02": ("EARNINGS", "财报"),
    "2.04": ("TRIGGER_EVENT", "触发事件"),
    "2.05": ("COST_EXIT", "重组/减值"),
    "2.06": ("MATERIAL_IMPAIRMENT", "重大减值"),
    "3.01": ("DELISTING", "退市通知"),
    "3.02": ("EQUITY_SALE", "未注册股权出售"),
    "4.01": ("AUDITOR_CHANGE", "审计师变更"),
    "5.02": ("EXEC_CHANGE", "高管变动"),
    "5.03": ("BYLAWS_CHANGE", "章程修改"),
    "7.01": ("FD_DISCLOSURE", "FD披露/Guidance"),
    "8.01": ("OTHER", "其他事件"),
}

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


def get_recent_filings(ticker, days=7):
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
    descs = filings.get("primaryDocDescription", [])

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    results = []
    for i in range(len(forms)):
        form = forms[i]
        if form not in EVENT_TYPES and form != "4" and form != "4/A":
            continue
        if form in ("4", "4/A"):
            continue
        if dates[i] < cutoff:
            break
        results.append({
            "form": form,
            "date": dates[i],
            "accession": accessions[i],
            "doc": docs[i] if i < len(docs) else "",
            "description": descs[i] if i < len(descs) else "",
            "cik": cik,
        })
    return results


def fetch_filing_text(cik, accession, doc):
    acc_nodash = accession.replace("-", "")
    if "/" in doc:
        doc = doc.split("/")[-1]
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
    raw = _http_get(url).decode("utf-8", errors="replace")
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text[:20000]

# ============================================================
# 8-K Item Classification
# ============================================================

def classify_8k_items(text):
    items = []
    for item_num, (code, label) in ITEM_MAP.items():
        pattern = rf'Item\s+{re.escape(item_num)}'
        if re.search(pattern, text, re.IGNORECASE):
            items.append({"item": item_num, "code": code, "label": label})
    return items

# ============================================================
# Filing Score Computation
# ============================================================

def compute_filing_score(ticker, filings_with_items):
    score = 0
    details = []

    for filing in filings_with_items:
        form = filing["form"]
        date = filing["date"]

        if form.startswith("8-K"):
            items = filing.get("items", [])
            for item in items:
                code = item["code"]
                if code == "EXEC_CHANGE":
                    score -= 10
                    details.append(f"-高管变动(8-K 5.02 {date})")
                elif code == "MATERIAL_CONTRACT":
                    score += 5
                    details.append(f"+重大合同(8-K 1.01 {date})")
                elif code == "EARNINGS":
                    details.append(f"⚪财报(8-K 2.02 {date})")
                elif code == "ACQUISITION":
                    details.append(f"⚪收购/处置(8-K 2.01 {date})")
                elif code == "MATERIAL_IMPAIRMENT":
                    score -= 5
                    details.append(f"-重大减值(8-K 2.06 {date})")
                elif code == "COST_EXIT":
                    score -= 3
                    details.append(f"-重组/减值(8-K 2.05 {date})")
                elif code == "FD_DISCLOSURE":
                    details.append(f"⚪Guidance(8-K 7.01 {date})")

        elif form.startswith("S-3") or form.startswith("S-1"):
            score -= 5
            details.append(f"-增发登记({form} {date})")

        elif form.startswith("SC 13D"):
            score += 5
            details.append(f"+大股东增持({form} {date})")

        elif form in ("10-K", "10-K/A", "20-F"):
            details.append(f"⚪年报({form} {date})")

        elif form in ("10-Q", "10-Q/A"):
            details.append(f"⚪季报({form} {date})")

    score = max(-15, min(15, score))
    return score, details

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
            "filing_scores": {},
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


def send_dingtalk(report_md, title="SEC Filing监控"):
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

def format_report(all_results):
    lines = [
        f"### 📋 SEC Filing 事件 ({datetime.now().strftime('%m/%d')})",
        "",
    ]

    high_events = []
    medium_events = []
    low_events = []

    for ticker, (score, details, filings) in all_results.items():
        for filing in filings:
            form = filing["form"]
            date = filing["date"]
            evt = EVENT_TYPES.get(form, {})
            importance = evt.get("importance", "LOW")
            label = evt.get("label", form)

            items_str = ""
            if filing.get("items"):
                item_labels = [f"Item {it['item']} {it['label']}" for it in filing["items"]]
                items_str = f" ({', '.join(item_labels)})"

            entry = f"**{ticker}** — {form} {label}{items_str} {date}"

            if importance == "HIGH":
                high_events.append(entry)
            elif importance == "MEDIUM":
                medium_events.append(entry)
            else:
                low_events.append(entry)

    if not high_events and not medium_events and not low_events:
        lines.append("近期无新SEC公告事件")
        lines.append("")
    else:
        if high_events:
            lines.append("#### 🔴 重大事件")
            for e in high_events:
                lines.append(f"- {e}")
            lines.append("")
        if medium_events:
            lines.append("#### 🟡 常规公告")
            for e in medium_events:
                lines.append(f"- {e}")
            lines.append("")
        if low_events:
            lines.append("#### ⚪ 低优先级")
            for e in low_events:
                lines.append(f"- {e}")
            lines.append("")

    lines.append("---")
    lines.append("📋 SEC Filing监控 | EDGAR")
    return "\n".join(lines)

# ============================================================
# Main Scan Logic
# ============================================================

def scan_ticker(ticker, state, days=7, verbose=True):
    if verbose:
        print(f"  {ticker}: 获取近{days}天Filing...")

    try:
        filings = get_recent_filings(ticker, days=days)
    except Exception as e:
        print(f"  {ticker}: [ERROR] {e}")
        return None

    if not filings:
        if verbose:
            print(f"  {ticker}: 近{days}天无相关Filing")
        return 0, [], []

    seen = set(state.get("seen_filings", {}).get(ticker, []))
    new_filings = [f for f in filings if f["accession"] not in seen]

    for filing in filings:
        if filing["form"].startswith("8-K"):
            try:
                text = fetch_filing_text(filing["cik"], filing["accession"], filing["doc"])
                filing["items"] = classify_8k_items(text)
                time.sleep(0.15)
            except Exception as e:
                filing["items"] = []
                if verbose:
                    print(f"    [WARN] 8-K解析失败: {e}")
        else:
            filing["items"] = []

    score, details = compute_filing_score(ticker, filings)

    state.setdefault("seen_filings", {})[ticker] = [f["accession"] for f in filings]
    state.setdefault("last_check", {})[ticker] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    state.setdefault("filing_scores", {})[ticker] = {
        "score": score,
        "details": details,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    if _HAS_DB:
        try:
            mdb.save_filing_score(ticker, score, details)
            evt_types = {
                "8-K": {"importance": "HIGH"}, "8-K/A": {"importance": "HIGH"},
                "10-K": {"importance": "MEDIUM"}, "10-Q": {"importance": "MEDIUM"},
                "SC 13D": {"importance": "HIGH"}, "S-3": {"importance": "HIGH"},
                "S-1": {"importance": "HIGH"},
            }
            for f in filings:
                imp = evt_types.get(f["form"], {}).get("importance", "LOW")
                mdb.save_filing(
                    ticker=ticker, form=f["form"], filing_date=f["date"],
                    accession=f["accession"], importance=imp,
                    items=f.get("items"), score_delta=0)
        except Exception:
            pass

    if verbose:
        n_8k = sum(1 for f in filings if f["form"].startswith("8-K"))
        n_other = len(filings) - n_8k
        print(f"  {ticker}: {len(filings)}个Filing ({n_8k}个8-K, {n_other}个其他)")
        if details:
            detail_str = " | ".join(details)
            if score > 0:
                print(f"  → 🟢 信号分: +{score} | {detail_str}")
            elif score < 0:
                print(f"  → 🔴 信号分: {score} | {detail_str}")
            else:
                print(f"  → ⚪ 信号分: 0 | {detail_str}")

    return score, details, filings


def run_scan(tickers=None, dingtalk=False, days=7):
    if tickers is None:
        tickers = MONITOR_TICKERS

    state = load_state()
    all_results = {}

    print(f"SEC Filing事件监控 — 扫描 {len(tickers)} 个标的")
    print(f"回溯窗口: {days}天\n")

    for ticker in tickers:
        try:
            result = scan_ticker(ticker, state, days=days)
            if result is None:
                continue
            score, details, filings = result
            all_results[ticker] = (score, details, filings)
        except Exception as e:
            print(f"  {ticker}: [ERROR] {e}")
        time.sleep(0.3)

    save_state(state)

    has_events = any(len(filings) > 0 for _, _, filings in all_results.values())
    if has_events:
        report = format_report(all_results)
        print(f"\n{report}")
        if dingtalk:
            send_dingtalk(report, "SEC Filing事件")
            print("  → 已推送钉钉")
    else:
        print("\n近期无新SEC Filing事件")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="SEC Filing Event Monitor")
    parser.add_argument("tickers", nargs="*", help="Ticker symbols to scan")
    parser.add_argument("--dingtalk", action="store_true", help="Push alerts to DingTalk")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers] if args.tickers else None
    run_scan(tickers=tickers, dingtalk=args.dingtalk, days=args.days)


if __name__ == "__main__":
    main()
