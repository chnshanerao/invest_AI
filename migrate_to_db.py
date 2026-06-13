#!/usr/bin/env python3
"""
migrate_to_db.py — 一次性数据迁移脚本

将现有JSON状态文件和硬编码WATCHLIST迁移到chokepoint.db
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor_db as mdb

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE, "state")


def migrate_watchlist():
    from chokepoint_trader import WATCHLIST
    conn = mdb.get_conn()
    count = 0

    core_tickers = {"COHR", "LITE", "MU", "LEU", "HYNIX", "PLAB", "CAMT"}
    downgraded_tickers = {"CRDO", "AXTI", "VICR"}

    for ticker, cfg in WATCHLIST.items():
        if ticker in core_tickers:
            category = "core"
        elif ticker in downgraded_tickers:
            category = "downgrade"
        else:
            category = "observe"

        entry_zone = cfg.get("entry_zone", [None, None])
        mdb.save_watchlist_item({
            "ticker": ticker,
            "name": cfg.get("name"),
            "layer": cfg.get("layer"),
            "score": cfg.get("score"),
            "target_usd": cfg.get("target_usd", 0),
            "stop_loss": cfg.get("stop_loss", -0.15),
            "entry_low": entry_zone[0] if entry_zone else None,
            "entry_high": entry_zone[1] if len(entry_zone) > 1 else None,
            "category": category,
            "source": cfg.get("source", "sina_us"),
            "hk_code": cfg.get("hk_code"),
            "currency": cfg.get("currency", "USD"),
            "downgrade": cfg.get("downgrade"),
            "note": cfg.get("note"),
        }, conn=conn)
        count += 1

    conn.commit()
    conn.close()
    print(f"  watchlist: {count} tickers migrated")


def migrate_signals():
    path = os.path.join(STATE_DIR, "trader_state.json")
    if not os.path.exists(path):
        print("  signals: trader_state.json not found, skipped")
        return

    with open(path) as f:
        data = json.load(f)

    conn = mdb.get_conn()
    count = 0
    seen = set()
    for ticker, entries in data.get("signals_history", {}).items():
        for entry in entries:
            key = (ticker, entry["date"])
            if key in seen:
                continue
            seen.add(key)
            mdb.save_signal(
                ticker=ticker,
                date=entry["date"],
                price=entry.get("price"),
                total_score=entry.get("score"),
                signal=entry.get("signal"),
                conn=conn,
            )
            count += 1

    conn.commit()
    conn.close()
    print(f"  signals: {count} entries migrated (deduped)")


def migrate_positions():
    path = os.path.join(STATE_DIR, "trader_state.json")
    if not os.path.exists(path):
        return

    with open(path) as f:
        data = json.load(f)

    conn = mdb.get_conn()
    count = 0
    for ticker, pos in data.get("positions", {}).items():
        mdb.save_position(
            ticker=ticker,
            batch=pos.get("batch", 0),
            avg_cost=pos.get("avg_cost", 0),
            shares=pos.get("shares", 0),
            total_invested=pos.get("total_invested", 0),
            entry_date=pos.get("entry_date"),
            peak_price=pos.get("peak_price", 0),
            conn=conn,
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"  positions: {count} entries migrated")


def migrate_insider_scores():
    path = os.path.join(STATE_DIR, "insider_state.json")
    if not os.path.exists(path):
        print("  insider_scores: not found, skipped")
        return

    with open(path) as f:
        data = json.load(f)

    conn = mdb.get_conn()
    count = 0
    for ticker, entry in data.get("insider_scores", {}).items():
        mdb.save_insider_score(
            ticker=ticker,
            score=entry.get("score", 0),
            details=entry.get("details", []),
            buy_count=entry.get("buy_count", 0),
            sell_count=entry.get("sell_count", 0),
            buy_value=entry.get("buy_value", 0),
            sell_value=entry.get("sell_value", 0),
            conn=conn,
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"  insider_scores: {count} entries migrated")


def migrate_filing_scores():
    path = os.path.join(STATE_DIR, "filing_state.json")
    if not os.path.exists(path):
        print("  filing_scores: not found, skipped")
        return

    with open(path) as f:
        data = json.load(f)

    conn = mdb.get_conn()
    count = 0
    for ticker, entry in data.get("filing_scores", {}).items():
        mdb.save_filing_score(
            ticker=ticker,
            score=entry.get("score", 0),
            details=entry.get("details", []),
            conn=conn,
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"  filing_scores: {count} entries migrated")


def migrate_supply_chain():
    path = os.path.join(STATE_DIR, "10k_cache", "scan_results.json")
    if not os.path.exists(path):
        print("  supply_chain: not found, skipped")
        return

    with open(path) as f:
        data = json.load(f)

    conn = mdb.get_conn()
    count = 0
    for ticker, result in data.items():
        for mtype, mcount in result.get("by_type", {}).items():
            mdb.save_supply_chain(
                ticker=ticker,
                mention_type=mtype,
                mention_count=mcount,
                entities=result.get("entities", []),
                conn=conn,
            )
            count += 1

    conn.commit()
    conn.close()
    print(f"  supply_chain: {count} entries migrated")


def main():
    print("Migrating data to chokepoint.db...\n")
    mdb.init_db()

    migrate_watchlist()
    migrate_signals()
    migrate_positions()
    migrate_insider_scores()
    migrate_filing_scores()
    migrate_supply_chain()

    print(f"\nDone. Database at: {mdb.DB_PATH}")

    conn = mdb.get_conn()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    for t in tables:
        name = t["name"]
        count = conn.execute(f"SELECT COUNT(*) as c FROM {name}").fetchone()["c"]
        print(f"  {name}: {count} rows")
    conn.close()


if __name__ == "__main__":
    main()
