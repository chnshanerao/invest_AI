#!/usr/bin/env python3
"""
scheduler.py — Pipeline自动调度器

Pipeline顺序: fundamentals → valuation → trader → health_check
读取system_settings的auto_update_enabled和update_interval_hours。
在aiohttp启动时注册为后台线程。
"""
import subprocess
import sys
import threading
import time
import os
from datetime import datetime

import monitor_db as db
import config_helper as cfg

WORKSPACE = os.path.dirname(os.path.abspath(__file__))

STAGES = [
    ("fundamentals", "fundamentals_fetcher.py", 300),
    ("valuation_model", "valuation_model.py", 120),
    ("trader", "chokepoint_trader.py", 300),
    ("health_check", "thesis_health.py", 60),
]


def run_pipeline(trigger="auto"):
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stage_results = {}
    error_msg = None
    print(f"\n=== Pipeline Start ({trigger}) {started_at} ===")

    for name, script, timeout in STAGES:
        print(f"  [{name}] Running {script}...")
        t0 = time.time()
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(WORKSPACE, script)],
                capture_output=True, text=True, timeout=timeout,
                cwd=WORKSPACE,
            )
            elapsed = time.time() - t0
            ok = result.returncode == 0
            stage_results[name] = {
                "ok": ok,
                "time": round(elapsed, 1),
                "output": result.stdout[-500:] if result.stdout else "",
            }
            status = "✓" if ok else "✗"
            print(f"  [{name}] {status} ({elapsed:.1f}s)")
            if not ok and result.stderr:
                print(f"    stderr: {result.stderr[-200:]}")
                stage_results[name]["error"] = result.stderr[-200:]
        except subprocess.TimeoutExpired:
            stage_results[name] = {"ok": False, "time": timeout, "error": "timeout"}
            print(f"  [{name}] TIMEOUT ({timeout}s)")
        except Exception as e:
            stage_results[name] = {"ok": False, "error": str(e)}
            print(f"  [{name}] ERROR: {e}")

    all_ok = all(s.get("ok") for s in stage_results.values())
    status = "success" if all_ok else "partial"
    db.save_pipeline_run(started_at, status, stage_results, trigger, error_msg)
    print(f"=== Pipeline Done: {status} ===\n")

    _push_warnings_dingtalk()

    return stage_results


def _push_warnings_dingtalk():
    webhook, secret = cfg.get_dingtalk_config()
    if not webhook:
        return
    warnings = db.get_active_warnings()
    high = [w for w in warnings if w.get("severity") == "high"]
    if not high:
        return
    try:
        import urllib.request, json, hashlib, hmac, base64
        ts = str(int(time.time() * 1000))
        sign_str = f"{ts}\n{secret}"
        sign = base64.b64encode(
            hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).digest()
        ).decode()
        url = f"{webhook}&timestamp={ts}&sign={sign}"
        lines = [f"⚠ 投研预警 ({len(high)}个高危)"]
        for w in high[:5]:
            lines.append(f"• {w['ticker']}: {w['message']}")
        body = json.dumps({"msgtype": "text", "text": {"content": "\n".join(lines)}}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[DingTalk push failed] {e}")


def _scheduler_loop():
    while True:
        try:
            enabled = cfg.get_config("auto_update_enabled", "0")
            interval = int(cfg.get_config("update_interval_hours", "6"))
            if enabled != "1":
                time.sleep(300)
                continue

            runs = db.get_pipeline_runs(limit=1)
            if runs:
                last = runs[0]
                try:
                    last_time = datetime.strptime(last["started_at"], "%Y-%m-%d %H:%M:%S")
                    elapsed_hours = (datetime.now() - last_time).total_seconds() / 3600
                    if elapsed_hours < interval:
                        time.sleep(300)
                        continue
                except (ValueError, TypeError):
                    pass

            run_pipeline("auto")
        except Exception as e:
            print(f"[Scheduler error] {e}")
        time.sleep(300)


def start_background(app=None):
    enabled = cfg.get_config("auto_update_enabled", "0")
    interval = cfg.get_config("update_interval_hours", "6")
    print(f"[Scheduler] auto_update={'ON' if enabled=='1' else 'OFF'}, interval={interval}h")
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="pipeline-scheduler")
    t.start()
    return t


if __name__ == "__main__":
    print("=== Manual Pipeline Run ===")
    run_pipeline("manual")
