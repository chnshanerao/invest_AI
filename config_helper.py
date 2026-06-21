#!/usr/bin/env python3
"""
统一配置读取 — 所有模块从 system_settings 表读配置，fallback 到默认值。
用户在 Web 设置面板配一次，全系统生效。
"""
import monitor_db as db

_DEFAULTS = {
    "dingtalk_webhook": "",
    "dingtalk_secret": "",
    "sec_email": "investor@example.com",
    "auto_update_enabled": "0",
    "update_interval_hours": "6",
}


def get_config(key, default=None):
    val = db.get_setting(key)
    if val is not None:
        return val
    return default if default is not None else _DEFAULTS.get(key, "")


def get_dingtalk_config():
    return get_config("dingtalk_webhook"), get_config("dingtalk_secret")


def get_sec_email():
    return get_config("sec_email", _DEFAULTS["sec_email"])


def get_watchlist_tickers():
    conn = db.get_conn()
    wl = db.get_watchlist(conn)
    conn.close()
    return [w["ticker"] for w in wl]
