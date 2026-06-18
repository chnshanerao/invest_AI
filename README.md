# Chokepoint投研系统 — AI供应链瓶颈投资研究平台

基于 **Serenity瓶颈投资法 (Chokepoint Theory)** 的美股AI供应链深度研究系统。核心逻辑：找AI产业链上**物理上绕不开、供给高度集中、扩产周期长**的瓶颈环节，精选18个标的深度覆盖。

## 投资哲学

> "You don't need to find the next Nvidia. You need to find the road that EVERY AI chip must travel on."

- **瓶颈即壁垒** — 物理上无法绕过的环节（材料/设备/封装/连接），才是真正的护城河
- **$5-50B 甜区** — 当前中小市值、未来有 $100B+ 潜力的隐形冠军
- **关键少数** — 不要50个标的，要18个深度研究过的瓶颈节点
- **基本面+技术面双驱动** — 估值模型算潜在市值，技术信号判入场时机

## 18标的覆盖

### 核心持仓 (7个 BUY)
| Ticker | 名称 | 瓶颈环节 | 市值档次 |
|--------|------|---------|---------|
| **CRDO** | Credo Technology | SerDes/AEC连接芯片 | 🟢 Mid |
| **CAMT** | Camtek | 先进封装检测 | 🟡 Small |
| **COHR** | Coherent | 光模块800G/1.6T | 🔵 Large |
| **LITE** | Lumentum | EML激光器 | 🟡 Small |
| **LEU** | Centrus Energy | HALEU核燃料 | 🟡 Small |
| **MU** | Micron | HBM内存 | 🔵 Large |
| **HYNIX** | SK Hynix | HBM内存 (韩国) | 🔵 Large |

### 观察 (7个 HOLD)
| Ticker | 名称 | 瓶颈环节 |
|--------|------|---------|
| ALAB | Astera Labs | PCIe Retimer |
| ADEA | Adeia | 封装IP/混合键合 |
| PLAB | Photronics | 光掩模 |
| VICR | Vicor | 功率模块 |
| SMR | NuScale | 小型核反应堆 |
| WLDN | Willdan | 电网接入 |
| UCTT | Ultra Clean | 半导体设备部件 |

### 降级/回避 (4个 AVOID)
| Ticker | 名称 | 原因 |
|--------|------|------|
| GSM | Ferroglobe | 硅金属商品化，无定价权 |
| AXTI | AXT Inc | InP衬底需求未爆发 |
| MX | MagnaChip | MOSFET竞争激烈 |
| NNE | NANO Nuclear | 收入为零，概念炒作 |

## 估值模型 — 3年Revenue Forward

每个标的计算三情景潜在市值（完全透明，可审计）：

```
Step 1: TTM Revenue (4季度滚动求和)
Step 2: Revenue CAGR (多年CAGR，硬上限±20%)
Step 3: 3年Revenue预测 (增长衰减模型)
Step 4: Terminal P/S (公式化: 3.0 + growth_adj + margin_adj, 钳位1.5-25x)
Step 5: 潜在市值 = Y3_Revenue × Terminal_PS
Step 6: 市值分档 (Mega $200B+ / Large $50-200B / Mid $10-50B / Small $2-10B / Micro <$2B)
```

三种情景：**Bear** (CAGR×0.6)、**Base** (CAGR×1.0)、**Bull** (CAGR×1.3)

## Web Dashboard

启动命令：`python3 chokepoint_web.py --port 8088`

**Dashboard**: 三层分类（核心/观察/降级），每张卡片显示市值档次+潜在市值+估值模型+信号分

**研究详情**: 投资逻辑 → 护城河 → 催化剂 → 风险 → 估值模型三情景对比 → 基本面图表 → 10-K供应链扫描

**交易策略**: K线图（Lightweight Charts）+ 技术指标 + 信号分趋势 + 入场建议 + 止损计算

**供应链地图**: 可视化AI数据中心全链路（GPU→光互联→核能→材料），点击节点直达研究详情

**需求追踪**: 四大云厂商（MSFT/GOOG/META/AMZN）CapEx趋势 + AI投资指引

## CLI命令

```bash
# 采集数据（基本面/技术面/公司研究/估值模型）
curl -X POST http://localhost:8088/api/collect/fundamentals
curl -X POST http://localhost:8088/api/collect/trader
curl -X POST http://localhost:8088/api/collect/research
curl -X POST http://localhost:8088/api/collect/valuation

# 运行估值模型
python3 valuation_model.py

# 公司深度研究
python3 company_researcher.py CRDO
```

## 项目结构

```
├── chokepoint_web.py         # Web API — FastAPI/uvicorn
├── chokepoint_trader.py      # 技术面信号引擎 — 多因子评分+入场判定
├── monitor_db.py             # 数据层 — SQLite CRUD (12张表)
├── valuation_model.py        # 估值模型 — 3年Revenue Forward
├── company_researcher.py     # LLM公司研究 — 10-K提取+结构化分析
├── search_agent.py           # 多源搜索代理
├── sec_filing_monitor.py     # SEC Filing监听
├── sec_supply_chain.py       # 10-K供应链关键词扫描
├── fundamentals_fetcher.py   # 基本面数据采集 (SEC XBRL)
├── insider_monitor.py        # 内部人交易监控
├── kol_digest.py             # KOL观点聚合
├── market_scanner.py         # 盘中轻量扫描
├── memory_monitor.py         # 完整报告生成
├── web/
│   ├── index.html            # 前端 — 7个Tab
│   ├── app.js                # 核心逻辑 — 估值模型渲染+图表
│   ├── style.css             # 暗色主题 — 估值模型面板样式
│   └── video_slides.html     # CRDO YouTube视频幻灯片
├── youtube_script.md         # CRDO YouTube视频脚本
├── reports/
│   └── chokepoint_research_all.md  # 18标的完整研究档案 (EP.1-EP.18)
└── state/                    # 运行时数据
    ├── chokepoint.db         #   SQLite数据库
    └── 10k_cache/            #   10-K缓存
```

## 数据源

| 数据 | API | 用途 |
|------|-----|------|
| 基本面 | SEC XBRL (edgar.xbrl) | Revenue/EPS/毛利率/净收入 (8期) |
| 估 值 | 新浪财经 `hq.sinajs.cn` | 价格/市值/PE/PS/52周 |
| 技术面 | Yahoo Finance | K线+量价 (120日) |
| 10-K | SEC EDGAR | 公司研究/供应链扫描 (缓存) |
| 内部人 | OpenInsider | 内部人交易记录 |
| 需 求 | 云厂商季报 | MSFT/GOOG/META/AMZN CapEx |
| 研 究 | LLM (Claude API) | 深度公司分析+估值计算 |

## 前置条件

- Python 3.8+
- SQLite (Python自带)
- 网络可访问新浪财经/SEC EDGAR API
- LLM研究需配置 API Key (Web → 设置Tab)

## 方法论

详见 `reports/chokepoint_research_all.md` 附录"授人以渔"章节，包含：
- 瓶颈五问 (物理不可绕过? 供给集中? 替代品? 产能扩张? 内部人买入?)
- 估值模型完整公式
- 标的筛选标准
- 模型局限性说明

## License

MIT