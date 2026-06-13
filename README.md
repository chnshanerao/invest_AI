# AI供应链瓶颈投研系统 + A股ETF趋势交易系统

两套独立的量化投资工具，纯Python实现，零第三方依赖（仅stdlib）。

---

## 一、Chokepoint 投研系统（美股）

基于 **Serenity瓶颈投资法（Chokepoint Theory）** 的AI供应链研究驱动型投资监测系统。

### 投资方法论

核心理念：在AI基础设施供应链中找到 **物理瓶颈** — 不可绕过、不可替代、供不应求的环节，投资其中的小盘隐形冠军。

**决策链：**
```
产业链研究(为什么买) → 估值(贵不贵) → 技术面(什么时候买) → 交易指令
```

**Serenity五问筛选法：**
1. 这个组件是否在物理上不可跳过？（光掩模→芯片制造必须经过）
2. 是否只有1-2家供应商？（寡头/垄断=定价权）
3. 下游客户是否有替代选择？（锁定效应）
4. 产能是否能快速扩张？（不能=瓶颈持续）
5. 管理层是否在买入自家股票？（仅CEO买入为弱正信号，卖出不说明问题）

### 产业链拆解

```
AI数据中心
├── GPU计算集群
│   ├── HBM高带宽内存 ─────── MU(Micron) / HYNIX(SK海力士)
│   ├── 先进封装(CoWoS)
│   │   ├── 封装检测 ──────── CAMT(Camtek)
│   │   └── 光掩模 ─────────── PLAB(Photronics)
│   ├── SerDes连接芯片 ────── CRDO(Credo)
│   ├── GPU功率模块 ────────── VICR(Vicor)
│   └── 封装IP ──────────── ADEA(Adeia)
├── 光互联网络
│   ├── 800G/1.6T光模块 ───── COHR(Coherent)
│   ├── EML激光器 ──────────── LITE(Lumentum)
│   └── InP衬底 ────────────── AXTI(AXT)
├── 电力(核能)
│   ├── 小型模块堆SMR ────── SMR(NuScale)
│   ├── 核燃料(LEU) ────────── LEU(Centrus)
│   ├── 核电服务 ────────────── NNE(Nano Nuclear)
│   └── 电网接入 ────────────── WLDN(Willdan)
└── 基础材料
    ├── 硅金属 ──────────────── GSM(Ferroglobe)
    └── MOSFET ─────────────── MX(Magnachip)
```

### 数据源

| 数据类型 | API来源 | 具体字段 | 更新频率 |
|---------|--------|---------|---------|
| 日K线(OHLCV) | Sina Finance `stock.finance.sina.com.cn` | 开高低收量 | 每日 |
| 实时行情/估值 | Sina Finance `hq.sinajs.cn/list=gb_{ticker}` | fields[1]=价格, [12]=市值, [13]=PE, [8]=52周高, [9]=52周低 | 实时 |
| 季度基本面 | SEC EDGAR XBRL `data.sec.gov/api/xbrl/companyfacts/` | Revenue, EPS, GrossProfit, NetIncome, CostOfRevenue | 季度 |
| CIK映射 | SEC `sec.gov/files/company_tickers.json` | ticker→CIK编号 | 缓存 |
| 供应链关系 | SEC 10-K全文 `efts.sec.gov` | sole-source/single-source关键词扫描 | 年度 |
| 宏观指标 | Sina Finance `hq.sinajs.cn` | SOX(费城半导体), VXX(恐慌), USD/JPY | 每日 |
| 港股(HYNIX) | 腾讯财经 `web.ifzq.gtimg.cn` | HK ETF 07709 价格 | 每日 |

### 技术分析信号评分（0-100分）

| 因子 | 分值 | 计算方法 |
|------|------|---------|
| 趋势(SMA) | 0-30 | 多头排列(20>50>200)=30分, 站上20MA=10分 |
| 动量(MACD/RSI) | 0-25 | MACD金叉+15, RSI超卖反弹+15, 超买-10 |
| 波动(Bollinger) | 0-20 | 触下轨反弹+15, 中轨上方+10 |
| 量价 | 0-15 | 放量上涨+15, 缩量回调+10, 放量下跌-5 |
| 入场区间 | 0-10 | 区间内+10, 低于区间+8 |

| 总分 | 信号 | 含义 |
|------|------|------|
| ≥75 | STRONG_BUY | 多因子共振，建议入场 |
| 60-74 | BUY | 偏多，可分批建仓 |
| 40-59 | HOLD | 中性，持有观望 |
| 25-39 | CAUTION | 偏空，谨慎 |
| <25 | SELL | 多空转向，回避 |

### 估值指标

- **P/E(TTM)** — 从Sina实时获取
- **P/S(TTM)** — 市值 ÷ 最近4季度Revenue合计（SEC XBRL）
- **距52周高点%** — 跌幅越大=越便宜（<-30%为绿色=cheap）
- **毛利率趋势** — SEC XBRL季度GrossProfit/Revenue

### 使用方法

```bash
# 1. 数据采集

# 更新历史K线数据
python3 chokepoint_trader.py --update-history

# 采集SEC季度基本面 + Sina实时估值
python3 fundamentals_fetcher.py

# 扫描技术面信号（每日运行）
python3 chokepoint_trader.py

# 扫描SEC Filing事件
python3 sec_filing_monitor.py

# 2. Web系统

# 启动Web服务器
python3 chokepoint_web.py
# 浏览器访问 http://localhost:8088

# 3. 单个标的分析
python3 chokepoint_trader.py --ticker COHR

# 4. 数据初始化（首次使用）
python3 migrate_to_db.py
```

### Web系统功能（6个Tab）

| Tab | 功能 |
|-----|------|
| 投资总览 | 宏观指标(SOX/VXX/JPY) + 全标的卡片(论点+估值+信号) |
| 研究详情 | 投资逻辑全文 + 季度Revenue/毛利率图表 + 估值面板 |
| 交易策略 | K线图(SMA20/50+成交量) + 信号Score折线 + 技术指标 + 交易建议 |
| 产业链 | 交互式SVG拆解图 — GPU/光互联/核电/材料全链路可视化 |
| 需求侧 | 超大客户CapEx追踪(MSFT/GOOG/META/AMZN) |
| 管理 | 标的CRUD + 手动采集触发 |

---

## 二、A股ETF趋势交易系统

基于自适应ATR追踪止损的右侧趋势跟踪系统，覆盖36个A股行业/策略ETF。

### 核心理念

- **只做右侧** — 趋势确认后入场，不抄底不猜底
- **自适应止损** — 涨得越多止损越紧，自动锁住利润
- **大赚小亏** — 让利润奔跑，快速砍掉亏损

### 500天回测结果

| 指标 | 数值 |
|------|------|
| 平均收益 | **+47.1%**（同期上证+26.3%） |
| 盈利比例 | 26/36（72%的ETF盈利） |
| 总交易 | 355笔，胜率48% |
| 头部标的 | 芯片+178%, 通信+155%, 半导体+153% |

### 市场环境分段回测

| 市场环境 | 交易笔数 | 胜率 | 平均盈利 | 平均亏损 | 盈亏比 | 合计PnL |
|---------|---------|------|---------|---------|--------|---------|
| **牛市** | 167笔 | 48% | +14.2% | -3.3% | **4.4** | +854% |
| **熊市** | 55笔 | **62%** | +12.5% | -5.3% | 2.4 | +313% |
| **震荡** | 133笔 | 42% | +8.7% | -3.2% | 2.7 | +238% |

三种环境全部盈利，系统具备全天候适应性。

### 数据源

| 数据 | API | 用途 |
|------|-----|------|
| 历史日K线 | 腾讯财经 `web.ifzq.gtimg.cn` | 技术指标计算、回测 |
| 实时行情 | 新浪财经 `hq.sinajs.cn` | 盘中监测 |

### 使用方法

```bash
# 信号扫描
python3 a_etf_trend.py scan

# 单个ETF详情
python3 a_etf_trend.py signal sz159516

# 每日例行（更新+扫描+推送）
python3 a_etf_trend.py daily --dingtalk

# 回测
python3 a_etf_trend.py backtest sz159516
python3 a_etf_trend.py backtest-all

# Web Dashboard
python3 a_etf_web.py --port 8888
```

### 交易逻辑

**入场信号（4条件全满足）：**

| 条件 | 实现 | 含义 |
|------|------|------|
| 价格 > MA20 | `close > SMA(close, 20)` | 站上中期均线 |
| MA20上行 | `MA20(今) > MA20(5日前)` | 均线拐头确认 |
| MACD柱 > 0 | `MACD_histogram > 0` | 动量为正 |
| 量价确认 | `5日均量 > 20日均量` 或 量比>1.2且上涨 | 资金流入 |

**自适应ATR止损（核心）：**
```
trailing_stop = highest_close - K × ATR(20)
K = max(1.2, 3.0 - gain_adj - accel_adj)
```
刚入场K=3.0（宽松），涨10%→K=2.7，涨30%→K=2.1，暴涨→K=1.2（最紧）。

---

## 项目结构

```
├── chokepoint_trader.py        # US: 技术指标引擎 + K线采集 + 信号评分
├── fundamentals_fetcher.py     # US: SEC XBRL基本面 + Sina估值采集
├── monitor_db.py               # US: SQLite统一数据库层(13张表)
├── chokepoint_web.py           # US: aiohttp Web服务器(port 8088)
├── migrate_to_db.py            # US: 数据迁移 + 初始化
├── insider_monitor.py          # US: 内部人交易监测(SEC Form 4)
├── sec_filing_monitor.py       # US: SEC Filing事件监测
├── web/                        # US: 前端
│   ├── index.html              #   6-Tab布局
│   ├── app.js                  #   研究驱动型交互逻辑
│   └── style.css               #   暗色主题
├── a_etf_trend.py              # A股: 36个ETF趋势交易主系统
├── a_etf_web.py                # A股: Web Dashboard
├── a_trend_trader.py           # A股: 5因子趋势评分 + 数据采集
├── a_sector_scanner.py         # A股: 行业轮动扫描器
├── a_stock_monitor.py          # A股: 持仓监控 + 钉钉推送
└── state/                      # 运行时数据（自动创建）
    ├── chokepoint.db           #   US投研数据库
    └── price_history.db        #   US K线数据库
```

## 前置条件

- **Python 3.8+**（无需安装任何第三方库）
- **SQLite**（Python自带）
- 网络可访问Sina/SEC API
- Web系统需要 `aiohttp`（`pip install aiohttp`）
- 钉钉推送需配置 Webhook（可选）

## License

MIT
