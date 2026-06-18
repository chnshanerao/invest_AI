#!/usr/bin/env python3
"""
monitor_db.py — Chokepoint投研监测系统 统一数据库层

提供 state/chokepoint.db 的 schema 初始化和 CRUD 函数。
所有采集脚本和 Web 服务通过此模块读写数据库。
"""

import json
import os
import sqlite3
from datetime import datetime

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE, "state")
DB_PATH = os.path.join(STATE_DIR, "chokepoint.db")
PRICE_DB = os.path.join(STATE_DIR, "price_history.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY, name TEXT, layer TEXT,
    score INTEGER, target_usd REAL DEFAULT 0,
    stop_loss REAL DEFAULT -0.15,
    entry_low REAL, entry_high REAL,
    category TEXT DEFAULT 'observe',
    source TEXT DEFAULT 'sina_us',
    hk_code TEXT, currency TEXT DEFAULT 'USD',
    downgrade TEXT, note TEXT,
    created_at TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    ticker TEXT, date TEXT, price REAL,
    tech_score INTEGER, insider_score INTEGER, filing_score INTEGER,
    total_score INTEGER, signal TEXT, details TEXT,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS insider_tx (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT, filing_date TEXT, accession TEXT,
    insider_name TEXT, title TEXT,
    is_officer INTEGER, is_director INTEGER,
    tx_type TEXT, tx_code TEXT,
    shares REAL, price REAL, value REAL,
    post_holdings REAL, is_routine INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS insider_scores (
    ticker TEXT PRIMARY KEY, score INTEGER,
    details TEXT, buy_count INTEGER, sell_count INTEGER,
    buy_value REAL, sell_value REAL, scan_date TEXT
);

CREATE TABLE IF NOT EXISTS filing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT, form TEXT, filing_date TEXT,
    accession TEXT UNIQUE, importance TEXT,
    items TEXT, score_delta INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS filing_scores (
    ticker TEXT PRIMARY KEY, score INTEGER,
    details TEXT, scan_date TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT PRIMARY KEY, batch INTEGER DEFAULT 0,
    avg_cost REAL DEFAULT 0, shares REAL DEFAULT 0,
    total_invested REAL DEFAULT 0,
    entry_date TEXT, peak_price REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS macro_snapshots (
    date TEXT PRIMARY KEY,
    sox REAL, sox_chg REAL, vxx REAL, vxx_chg REAL,
    usdjpy REAL, fear_level TEXT,
    conditions_met INTEGER, entry_ready INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS supply_chain (
    ticker TEXT, mention_type TEXT, mention_count INTEGER,
    entities TEXT, scan_date TEXT,
    PRIMARY KEY (ticker, mention_type)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT, period TEXT,
    revenue REAL, eps REAL, gross_profit REAL,
    cost_of_revenue REAL, net_income REAL,
    shares_outstanding REAL,
    revenue_yoy REAL, gross_margin REAL,
    source TEXT DEFAULT 'xbrl',
    updated_at TEXT,
    PRIMARY KEY (ticker, period)
);

CREATE TABLE IF NOT EXISTS valuation (
    ticker TEXT PRIMARY KEY,
    price REAL, market_cap REAL,
    pe_ttm REAL, ps_ttm REAL,
    high_52w REAL, low_52w REAL,
    pct_from_high REAL, pct_from_low REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS research_thesis (
    ticker TEXT PRIMARY KEY,
    thesis TEXT, moat TEXT,
    catalysts TEXT, risks TEXT,
    verdict TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS demand_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, quarter TEXT,
    capex REAL, capex_yoy REAL,
    ai_capex_guidance TEXT,
    date TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS company_profiles (
    ticker TEXT PRIMARY KEY,
    business_overview TEXT,
    products_services TEXT,
    competitive_position TEXT,
    technology_moat TEXT,
    customers TEXT,
    suppliers TEXT,
    risk_factors TEXT,
    market_size TEXT,
    raw_sections TEXT,
    analysis_source TEXT DEFAULT '10k_extract',
    last_filing TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS valuation_model (
    ticker TEXT PRIMARY KEY,
    current_mcap REAL,
    current_tier TEXT,
    ttm_revenue REAL,
    revenue_cagr REAL,
    gross_margin REAL,
    bear_rev_y3 REAL, bear_ps REAL, bear_mcap REAL, bear_upside REAL,
    base_rev_y3 REAL, base_ps REAL, base_mcap REAL, base_upside REAL,
    bull_rev_y3 REAL, bull_ps REAL, bull_mcap REAL, bull_upside REAL,
    is_sweet_spot INTEGER DEFAULT 0,
    has_100b_path INTEGER DEFAULT 0,
    micro_warning INTEGER DEFAULT 0,
    calc_details TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_bars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    UNIQUE(ticker, date)
);
"""


def get_conn(db_path=None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ---- Watchlist ----

def get_watchlist(conn=None):
    c = conn or get_conn()
    rows = c.execute("SELECT * FROM watchlist ORDER BY category, ticker").fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


def get_ticker_info(ticker, conn=None):
    c = conn or get_conn()
    row = c.execute("SELECT * FROM watchlist WHERE ticker=?", (ticker,)).fetchone()
    if not conn:
        c.close()
    return dict(row) if row else None


def save_watchlist_item(item, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO watchlist
        (ticker, name, layer, score, target_usd, stop_loss,
         entry_low, entry_high, category, source, hk_code, currency,
         downgrade, note, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         name=excluded.name, layer=excluded.layer, score=excluded.score,
         target_usd=excluded.target_usd, stop_loss=excluded.stop_loss,
         entry_low=excluded.entry_low, entry_high=excluded.entry_high,
         category=excluded.category, source=excluded.source,
         hk_code=excluded.hk_code, currency=excluded.currency,
         downgrade=excluded.downgrade, note=excluded.note,
         updated_at=excluded.updated_at
    """, (
        item["ticker"], item.get("name"), item.get("layer"),
        item.get("score"), item.get("target_usd", 0),
        item.get("stop_loss", -0.15),
        item.get("entry_low"), item.get("entry_high"),
        item.get("category", "observe"),
        item.get("source", "sina_us"),
        item.get("hk_code"), item.get("currency", "USD"),
        item.get("downgrade"), item.get("note"),
        now, now,
    ))
    if not conn:
        c.commit()
        c.close()


def delete_watchlist_item(ticker, conn=None):
    c = conn or get_conn()
    c.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,))
    if not conn:
        c.commit()
        c.close()


# ---- Signals ----

def save_signal(ticker, date, price, total_score, signal,
                tech_score=None, insider_score=None, filing_score=None,
                details=None, conn=None):
    c = conn or get_conn()
    c.execute("""INSERT INTO signals
        (ticker, date, price, tech_score, insider_score, filing_score,
         total_score, signal, details)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker, date) DO UPDATE SET
         price=excluded.price, tech_score=excluded.tech_score,
         insider_score=excluded.insider_score, filing_score=excluded.filing_score,
         total_score=excluded.total_score, signal=excluded.signal,
         details=excluded.details
    """, (ticker, date, price, tech_score, insider_score, filing_score,
          total_score, signal,
          json.dumps(details, ensure_ascii=False) if details else None))
    if not conn:
        c.commit()
        c.close()


def get_signals(ticker, limit=60, conn=None):
    c = conn or get_conn()
    rows = c.execute(
        "SELECT * FROM signals WHERE ticker=? ORDER BY date DESC LIMIT ?",
        (ticker, limit)
    ).fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


def get_latest_signals(conn=None):
    c = conn or get_conn()
    rows = c.execute("""
        SELECT s.* FROM signals s
        INNER JOIN (SELECT ticker, MAX(date) as max_date FROM signals GROUP BY ticker) m
        ON s.ticker = m.ticker AND s.date = m.max_date
        ORDER BY s.total_score DESC
    """).fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


# ---- Insider ----

def save_insider_tx(ticker, filing_date, accession, insider_name, title,
                    is_officer, is_director, tx_type, tx_code,
                    shares, price, value, post_holdings=None,
                    is_routine=0, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO insider_tx
        (ticker, filing_date, accession, insider_name, title,
         is_officer, is_director, tx_type, tx_code,
         shares, price, value, post_holdings, is_routine, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT DO NOTHING
    """, (ticker, filing_date, accession, insider_name, title,
          int(is_officer), int(is_director), tx_type, tx_code,
          shares, price, value, post_holdings, int(is_routine), now))
    if not conn:
        c.commit()
        c.close()


def save_insider_score(ticker, score, details, buy_count, sell_count,
                       buy_value, sell_value, conn=None):
    c = conn or get_conn()
    c.execute("""INSERT INTO insider_scores
        (ticker, score, details, buy_count, sell_count, buy_value, sell_value, scan_date)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         score=excluded.score, details=excluded.details,
         buy_count=excluded.buy_count, sell_count=excluded.sell_count,
         buy_value=excluded.buy_value, sell_value=excluded.sell_value,
         scan_date=excluded.scan_date
    """, (ticker, score,
          json.dumps(details, ensure_ascii=False) if isinstance(details, list) else details,
          buy_count, sell_count, buy_value, sell_value,
          datetime.now().strftime("%Y-%m-%d")))
    if not conn:
        c.commit()
        c.close()


def get_insider_txs(ticker=None, days=30, conn=None):
    c = conn or get_conn()
    if ticker:
        rows = c.execute("""SELECT * FROM insider_tx
            WHERE ticker=? AND filing_date >= date('now', ?)
            ORDER BY filing_date DESC""",
            (ticker, f"-{days} days")).fetchall()
    else:
        rows = c.execute("""SELECT * FROM insider_tx
            WHERE filing_date >= date('now', ?)
            ORDER BY filing_date DESC""",
            (f"-{days} days",)).fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


def get_insider_scores(conn=None):
    c = conn or get_conn()
    rows = c.execute("SELECT * FROM insider_scores").fetchall()
    if not conn:
        c.close()
    return {r["ticker"]: dict(r) for r in rows}


# ---- Filing Events ----

def save_filing(ticker, form, filing_date, accession, importance,
                items=None, score_delta=0, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO filing_events
        (ticker, form, filing_date, accession, importance, items, score_delta, created_at)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(accession) DO NOTHING
    """, (ticker, form, filing_date, accession, importance,
          json.dumps(items, ensure_ascii=False) if items else None,
          score_delta, now))
    if not conn:
        c.commit()
        c.close()


def save_filing_score(ticker, score, details, conn=None):
    c = conn or get_conn()
    c.execute("""INSERT INTO filing_scores
        (ticker, score, details, scan_date)
        VALUES (?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         score=excluded.score, details=excluded.details, scan_date=excluded.scan_date
    """, (ticker, score,
          json.dumps(details, ensure_ascii=False) if isinstance(details, list) else details,
          datetime.now().strftime("%Y-%m-%d")))
    if not conn:
        c.commit()
        c.close()


def get_filings(ticker=None, days=14, conn=None):
    c = conn or get_conn()
    if ticker:
        rows = c.execute("""SELECT * FROM filing_events
            WHERE ticker=? AND filing_date >= date('now', ?)
            ORDER BY filing_date DESC""",
            (ticker, f"-{days} days")).fetchall()
    else:
        rows = c.execute("""SELECT * FROM filing_events
            WHERE filing_date >= date('now', ?)
            ORDER BY filing_date DESC""",
            (f"-{days} days",)).fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


def get_filing_scores(conn=None):
    c = conn or get_conn()
    rows = c.execute("SELECT * FROM filing_scores").fetchall()
    if not conn:
        c.close()
    return {r["ticker"]: dict(r) for r in rows}


# ---- Positions ----

def save_position(ticker, batch=0, avg_cost=0, shares=0,
                  total_invested=0, entry_date=None, peak_price=0, conn=None):
    c = conn or get_conn()
    c.execute("""INSERT INTO positions
        (ticker, batch, avg_cost, shares, total_invested, entry_date, peak_price)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         batch=excluded.batch, avg_cost=excluded.avg_cost,
         shares=excluded.shares, total_invested=excluded.total_invested,
         entry_date=excluded.entry_date, peak_price=excluded.peak_price
    """, (ticker, batch, avg_cost, shares, total_invested, entry_date, peak_price))
    if not conn:
        c.commit()
        c.close()


def get_positions(conn=None):
    c = conn or get_conn()
    rows = c.execute("SELECT * FROM positions WHERE shares > 0").fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


# ---- Macro ----

def save_macro(date, sox=None, sox_chg=None, vxx=None, vxx_chg=None,
               usdjpy=None, fear_level=None, conditions_met=0,
               entry_ready=0, conn=None):
    c = conn or get_conn()
    c.execute("""INSERT INTO macro_snapshots
        (date, sox, sox_chg, vxx, vxx_chg, usdjpy, fear_level,
         conditions_met, entry_ready)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
         sox=excluded.sox, sox_chg=excluded.sox_chg,
         vxx=excluded.vxx, vxx_chg=excluded.vxx_chg,
         usdjpy=excluded.usdjpy, fear_level=excluded.fear_level,
         conditions_met=excluded.conditions_met, entry_ready=excluded.entry_ready
    """, (date, sox, sox_chg, vxx, vxx_chg, usdjpy, fear_level,
          conditions_met, entry_ready))
    if not conn:
        c.commit()
        c.close()


def get_macro_latest(conn=None):
    c = conn or get_conn()
    row = c.execute("SELECT * FROM macro_snapshots ORDER BY date DESC LIMIT 1").fetchone()
    if not conn:
        c.close()
    return dict(row) if row else None


def get_macro_history(days=30, conn=None):
    c = conn or get_conn()
    rows = c.execute("""SELECT * FROM macro_snapshots
        WHERE date >= date('now', ?) ORDER BY date""",
        (f"-{days} days",)).fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


# ---- Supply Chain ----

def save_supply_chain(ticker, mention_type, mention_count, entities,
                      scan_date=None, conn=None):
    c = conn or get_conn()
    c.execute("""INSERT INTO supply_chain
        (ticker, mention_type, mention_count, entities, scan_date)
        VALUES (?,?,?,?,?)
        ON CONFLICT(ticker, mention_type) DO UPDATE SET
         mention_count=excluded.mention_count, entities=excluded.entities,
         scan_date=excluded.scan_date
    """, (ticker, mention_type, mention_count,
          json.dumps(entities, ensure_ascii=False) if isinstance(entities, list) else entities,
          scan_date or datetime.now().strftime("%Y-%m-%d")))
    if not conn:
        c.commit()
        c.close()


def get_supply_chain(conn=None):
    c = conn or get_conn()
    rows = c.execute("SELECT * FROM supply_chain ORDER BY ticker").fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


# ---- Price History (read-only from price_history.db) ----

def get_price_bars(ticker, days=120, conn=None):
    try:
        c = conn or sqlite3.connect(PRICE_DB)
        c.row_factory = sqlite3.Row
        rows = c.execute("""SELECT * FROM daily_bars
            WHERE ticker=? ORDER BY date DESC LIMIT ?""",
            (ticker, days)).fetchall()
        if not conn:
            c.close()
        return [dict(r) for r in reversed(rows)]
    except sqlite3.OperationalError:
        return []


# ---- Fundamentals ----

def save_fundamentals(ticker, period, revenue=None, eps=None,
                      gross_profit=None, cost_of_revenue=None,
                      net_income=None, shares_outstanding=None,
                      revenue_yoy=None, gross_margin=None, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO fundamentals
        (ticker, period, revenue, eps, gross_profit, cost_of_revenue,
         net_income, shares_outstanding, revenue_yoy, gross_margin, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker, period) DO UPDATE SET
         revenue=excluded.revenue, eps=excluded.eps,
         gross_profit=excluded.gross_profit,
         cost_of_revenue=excluded.cost_of_revenue,
         net_income=excluded.net_income,
         shares_outstanding=excluded.shares_outstanding,
         revenue_yoy=excluded.revenue_yoy,
         gross_margin=excluded.gross_margin,
         updated_at=excluded.updated_at
    """, (ticker, period, revenue, eps, gross_profit, cost_of_revenue,
          net_income, shares_outstanding, revenue_yoy, gross_margin, now))
    if not conn:
        c.commit()
        c.close()


def get_fundamentals(ticker, limit=8, conn=None):
    c = conn or get_conn()
    rows = c.execute("""SELECT * FROM fundamentals
        WHERE ticker=? ORDER BY period DESC LIMIT ?""",
        (ticker, limit)).fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in reversed(rows)]


# ---- Valuation ----

def save_valuation(ticker, price, market_cap, pe_ttm, ps_ttm,
                   high_52w, low_52w, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    pct_from_high = ((price - high_52w) / high_52w * 100) if high_52w else None
    pct_from_low = ((price - low_52w) / low_52w * 100) if low_52w else None
    c.execute("""INSERT INTO valuation
        (ticker, price, market_cap, pe_ttm, ps_ttm,
         high_52w, low_52w, pct_from_high, pct_from_low, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         price=excluded.price, market_cap=excluded.market_cap,
         pe_ttm=excluded.pe_ttm, ps_ttm=excluded.ps_ttm,
         high_52w=excluded.high_52w, low_52w=excluded.low_52w,
         pct_from_high=excluded.pct_from_high, pct_from_low=excluded.pct_from_low,
         updated_at=excluded.updated_at
    """, (ticker, price, market_cap, pe_ttm, ps_ttm,
          high_52w, low_52w, pct_from_high, pct_from_low, now))
    if not conn:
        c.commit()
        c.close()


def get_valuation(ticker=None, conn=None):
    c = conn or get_conn()
    if ticker:
        row = c.execute("SELECT * FROM valuation WHERE ticker=?", (ticker,)).fetchone()
        if not conn:
            c.close()
        return dict(row) if row else None
    rows = c.execute("SELECT * FROM valuation ORDER BY ticker").fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


# ---- Research Thesis ----

def save_thesis(ticker, thesis=None, moat=None, catalysts=None,
                risks=None, verdict=None, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO research_thesis
        (ticker, thesis, moat, catalysts, risks, verdict, updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         thesis=COALESCE(excluded.thesis, research_thesis.thesis),
         moat=COALESCE(excluded.moat, research_thesis.moat),
         catalysts=COALESCE(excluded.catalysts, research_thesis.catalysts),
         risks=COALESCE(excluded.risks, research_thesis.risks),
         verdict=COALESCE(excluded.verdict, research_thesis.verdict),
         updated_at=excluded.updated_at
    """, (ticker, thesis, moat,
          json.dumps(catalysts, ensure_ascii=False) if isinstance(catalysts, list) else catalysts,
          risks, verdict, now))
    if not conn:
        c.commit()
        c.close()


def get_thesis(ticker=None, conn=None):
    c = conn or get_conn()
    if ticker:
        row = c.execute("SELECT * FROM research_thesis WHERE ticker=?", (ticker,)).fetchone()
        if not conn:
            c.close()
        return dict(row) if row else None
    rows = c.execute("SELECT * FROM research_thesis ORDER BY ticker").fetchall()
    if not conn:
        c.close()
    return {r["ticker"]: dict(r) for r in rows}


# ---- Demand Signals ----

def save_demand_signal(source, quarter, capex, capex_yoy=None,
                       ai_capex_guidance=None, date=None, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO demand_signals
        (source, quarter, capex, capex_yoy, ai_capex_guidance, date, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (source, quarter, capex, capex_yoy, ai_capex_guidance,
          date or datetime.now().strftime("%Y-%m-%d"), now))
    if not conn:
        c.commit()
        c.close()


def get_demand_signals(conn=None):
    c = conn or get_conn()
    rows = c.execute("""SELECT * FROM demand_signals
        ORDER BY quarter DESC, source""").fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


# ---- Company Profiles ----

def save_company_profile(ticker, business_overview=None, products_services=None,
                         competitive_position=None, technology_moat=None,
                         customers=None, suppliers=None, risk_factors=None,
                         market_size=None, raw_sections=None,
                         analysis_source='10k_extract', last_filing=None, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO company_profiles
        (ticker, business_overview, products_services, competitive_position,
         technology_moat, customers, suppliers, risk_factors, market_size,
         raw_sections, analysis_source, last_filing, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         business_overview=COALESCE(excluded.business_overview, company_profiles.business_overview),
         products_services=COALESCE(excluded.products_services, company_profiles.products_services),
         competitive_position=COALESCE(excluded.competitive_position, company_profiles.competitive_position),
         technology_moat=COALESCE(excluded.technology_moat, company_profiles.technology_moat),
         customers=COALESCE(excluded.customers, company_profiles.customers),
         suppliers=COALESCE(excluded.suppliers, company_profiles.suppliers),
         risk_factors=COALESCE(excluded.risk_factors, company_profiles.risk_factors),
         market_size=COALESCE(excluded.market_size, company_profiles.market_size),
         raw_sections=COALESCE(excluded.raw_sections, company_profiles.raw_sections),
         analysis_source=excluded.analysis_source,
         last_filing=COALESCE(excluded.last_filing, company_profiles.last_filing),
         updated_at=excluded.updated_at
    """, (ticker, business_overview, products_services, competitive_position,
          technology_moat, customers, suppliers, risk_factors, market_size,
          raw_sections, analysis_source, last_filing, now))
    if not conn:
        c.commit()
        c.close()


def get_company_profile(ticker=None, conn=None):
    c = conn or get_conn()
    if ticker:
        row = c.execute("SELECT * FROM company_profiles WHERE ticker=?", (ticker,)).fetchone()
        if not conn:
            c.close()
        return dict(row) if row else None
    rows = c.execute("SELECT * FROM company_profiles ORDER BY ticker").fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


# ---- System Settings ----

def save_setting(key, value, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO system_settings (key, value, updated_at)
        VALUES (?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, value, now))
    if not conn:
        c.commit()
        c.close()


def get_setting(key, default=None, conn=None):
    c = conn or get_conn()
    row = c.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    if not conn:
        c.close()
    return row["value"] if row else default


# ---- Valuation Model ----

def save_valuation_model(ticker, data, conn=None):
    c = conn or get_conn()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    c.execute("""INSERT INTO valuation_model
        (ticker, current_mcap, current_tier, ttm_revenue, revenue_cagr, gross_margin,
         bear_rev_y3, bear_ps, bear_mcap, bear_upside,
         base_rev_y3, base_ps, base_mcap, base_upside,
         bull_rev_y3, bull_ps, bull_mcap, bull_upside,
         is_sweet_spot, has_100b_path, micro_warning,
         calc_details, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
         current_mcap=excluded.current_mcap, current_tier=excluded.current_tier,
         ttm_revenue=excluded.ttm_revenue, revenue_cagr=excluded.revenue_cagr,
         gross_margin=excluded.gross_margin,
         bear_rev_y3=excluded.bear_rev_y3, bear_ps=excluded.bear_ps,
         bear_mcap=excluded.bear_mcap, bear_upside=excluded.bear_upside,
         base_rev_y3=excluded.base_rev_y3, base_ps=excluded.base_ps,
         base_mcap=excluded.base_mcap, base_upside=excluded.base_upside,
         bull_rev_y3=excluded.bull_rev_y3, bull_ps=excluded.bull_ps,
         bull_mcap=excluded.bull_mcap, bull_upside=excluded.bull_upside,
         is_sweet_spot=excluded.is_sweet_spot, has_100b_path=excluded.has_100b_path,
         micro_warning=excluded.micro_warning,
         calc_details=excluded.calc_details, updated_at=excluded.updated_at
    """, (ticker, data.get("current_mcap"), data.get("current_tier"),
          data.get("ttm_revenue"), data.get("revenue_cagr"), data.get("gross_margin"),
          data.get("bear_rev_y3"), data.get("bear_ps"), data.get("bear_mcap"), data.get("bear_upside"),
          data.get("base_rev_y3"), data.get("base_ps"), data.get("base_mcap"), data.get("base_upside"),
          data.get("bull_rev_y3"), data.get("bull_ps"), data.get("bull_mcap"), data.get("bull_upside"),
          data.get("is_sweet_spot", 0), data.get("has_100b_path", 0), data.get("micro_warning", 0),
          json.dumps(data.get("calc_details", {}), ensure_ascii=False) if isinstance(data.get("calc_details"), dict) else data.get("calc_details"),
          now))
    if not conn:
        c.commit()
        c.close()


def get_valuation_model(ticker=None, conn=None):
    c = conn or get_conn()
    if ticker:
        row = c.execute("SELECT * FROM valuation_model WHERE ticker=?", (ticker,)).fetchone()
        if not conn:
            c.close()
        return dict(row) if row else None
    rows = c.execute("SELECT * FROM valuation_model ORDER BY ticker").fetchall()
    if not conn:
        c.close()
    return [dict(r) for r in rows]


def get_all_settings(conn=None):
    c = conn or get_conn()
    rows = c.execute("SELECT key, value FROM system_settings").fetchall()
    if not conn:
        c.close()
    return {r["key"]: r["value"] for r in rows}


# ---- Dashboard aggregate ----

def get_dashboard_data():
    conn = get_conn()
    wl = get_watchlist(conn)
    signals = get_latest_signals(conn)
    macro = get_macro_latest(conn)
    positions = get_positions(conn)
    theses = get_thesis(conn=conn)
    valuations = get_valuation(conn=conn)
    vm_list = get_valuation_model(conn=conn)
    demand = get_demand_signals(conn)
    conn.close()

    sig_map = {s["ticker"]: s for s in signals}
    val_map = {v["ticker"]: v for v in valuations} if isinstance(valuations, list) else {}
    vm_map = {v["ticker"]: v for v in vm_list} if isinstance(vm_list, list) else {}
    for item in wl:
        t = item["ticker"]
        item["signal"] = sig_map.get(t, {})
        item["thesis"] = theses.get(t, {})
        item["valuation"] = val_map.get(t, {})
        item["valuation_model"] = vm_map.get(t, {})

    return {
        "watchlist": wl,
        "macro": macro,
        "positions": [dict(p) for p in positions],
        "demand": demand[:5],
        "stats": {
            "total": len(wl),
            "buy_signals": sum(1 for s in signals if s.get("signal") in ("BUY", "STRONG_BUY")),
            "positions": len(positions),
        },
    }


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
