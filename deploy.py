#!/usr/bin/env python3
"""
deploy.py — Chokepoint投研系统 一键部署脚本

用法:
  python3 deploy.py              # 部署(初始化DB + 导入种子数据 + 启动)
  python3 deploy.py --init-only  # 仅初始化DB
  python3 deploy.py --seed-only  # 仅导入种子数据
  python3 deploy.py --start      # 仅启动服务
  python3 deploy.py --port 8088  # 指定端口(默认8088)

种子数据来源: seed_data.sql (196行, 包含18标的watchlist/research_thesis/
  company_profiles/valuation_model/supply_chain/valuation/fundamentals)

数据采集顺序:
  1. fundamentals_fetcher.py  → fundamentals (SEC XBRL)
  2. chokepoint_trader.py     → daily_bars + signals + valuation
  3. valuation_model.py       → valuation_model (计算)
  4. company_researcher.py    → company_profiles (需LLM API Key)
  5. sec_supply_chain.py      → supply_chain
  6. insider_monitor.py       → insider_tx + insider_scores
"""

import argparse
import os
import sqlite3
import subprocess
import sys
import time

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(WORKSPACE, "state")
DB_PATH = os.path.join(STATE_DIR, "chokepoint.db")
SEED_SQL = os.path.join(WORKSPACE, "seed_data.sql")


def init_db():
    """创建所有表结构"""
    print("[1/2] 初始化数据库表结构...")
    os.makedirs(STATE_DIR, exist_ok=True)
    import monitor_db as mdb
    mdb.init_db()
    # 验证
    conn = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    conn.close()
    print(f"  ✅ 创建 {len(tables)} 张表: {', '.join(tables)}")


def import_seed():
    """导入种子数据（18标的静态研究数据）"""
    print("[2/2] 导入种子数据...")
    if not os.path.exists(SEED_SQL):
        print(f"  ⚠️  seed_data.sql 不存在，跳过种子数据导入")
        print(f"  ℹ️  新环境需运行采集脚本获取数据")
        return

    conn = sqlite3.connect(DB_PATH)
    with open(SEED_SQL, 'r') as f:
        sql = f.read()
    statements = [s.strip() for s in sql.split(';\n') if s.strip()]
    for stmt in statements:
        try:
            conn.execute(stmt + ';')
        except sqlite3.OperationalError as e:
            if 'UNIQUE constraint' in str(e) or 'duplicate' in str(e).lower():
                pass  # 已存在，跳过
            else:
                print(f"  ⚠️  {e}")

    conn.commit()
    # 统计
    tables = ['watchlist', 'research_thesis', 'company_profiles',
              'valuation_model', 'supply_chain', 'valuation', 'fundamentals']
    for t in tables:
        count = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  📊 {t}: {count} 条")
    conn.close()
    print("  ✅ 种子数据导入完成")


def start_server(port=8088):
    """启动Web服务"""
    print(f"\n启动 Chokepoint Web Server — http://0.0.0.0:{port}")
    os.chdir(WORKSPACE)
    from aiohttp import web
    import chokepoint_web
    app = chokepoint_web.create_app()
    web.run_app(app, host="0.0.0.0", port=port)


def run_collect(module):
    """运行单个采集模块"""
    scripts = {
        "trader": "chokepoint_trader.py",
        "fundamentals": "fundamentals_fetcher.py",
        "valuation": "valuation_model.py",
        "research": "company_researcher.py",
        "supply": "sec_supply_chain.py",
        "insider": "insider_monitor.py",
    }
    if module not in scripts:
        print(f"未知模块: {module}")
        return False
    path = os.path.join(WORKSPACE, scripts[module])
    if not os.path.exists(path):
        print(f"脚本不存在: {path}")
        return False
    print(f"  运行 {scripts[module]}...")
    proc = subprocess.Popen(
        [sys.executable, path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=WORKSPACE,
    )
    stdout, _ = proc.communicate(timeout=300)
    ok = proc.returncode == 0
    print(f"  {'✅' if ok else '❌'} {scripts[module]} (exit={proc.returncode})")
    return ok


def collect_all():
    """运行所有数据采集（首次部署后或定期更新）"""
    print("采集实时数据...")
    # 顺序: fundamentals → trader(含valuation) → valuation_model(计算)
    modules = ["fundamentals", "trader", "valuation", "insider"]
    for m in modules:
        run_collect(m)
    print("采集完成")
    print("⚠️  company_researcher 和 sec_supply_chain 需要 LLM API Key，请在Web设置Tab配置后手动触发")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chokepoint 投研系统部署")
    parser.add_argument("--init-only", action="store_true", help="仅初始化数据库")
    parser.add_argument("--seed-only", action="store_true", help="仅导入种子数据")
    parser.add_argument("--start", action="store_true", help="仅启动服务")
    parser.add_argument("--collect", action="store_true", help="运行数据采集")
    parser.add_argument("--port", type=int, default=8088, help="服务端口")
    args = parser.parse_args()

    if args.init_only:
        init_db()
        sys.exit(0)

    if args.seed_only:
        import_seed()
        sys.exit(0)

    if args.collect:
        collect_all()
        sys.exit(0)

    if args.start:
        start_server(args.port)
        sys.exit(0)

    # 默认: 完整部署
    init_db()
    import_seed()
    start_server(args.port)