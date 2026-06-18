#!/usr/bin/env python3
"""
company_researcher.py — 从SEC 10-K年报中提取公司深度研究档案

功能：
  1. 下载10-K HTML（复用sec_supply_chain.py缓存）
  2. 提取Item 1(Business) / Item 1A(Risk Factors) / Item 7(MD&A)章节
  3. 关键词结构化提取：产品线、客户、供应商、竞争格局、技术壁垒
  4. 可选LLM增强分析（通过system_settings配置API key）
  5. 结果写入company_profiles表

用法：
  python3 company_researcher.py                # 研究所有watchlist标的
  python3 company_researcher.py COHR MU        # 研究指定标的
  python3 company_researcher.py --llm COHR     # 启用LLM深度分析
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import ssl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor_db as mdb
from sec_supply_chain import fetch_10k, extract_text, get_cik, get_latest_10k_url

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def extract_10k_sections(text):
    """从10-K全文中提取Item 1/1A/7主要章节。"""
    sections = {}

    patterns = [
        ("item1", r'(?:ITEM|Item)\s*1[\.\s\-—:]+\s*Bus\w+', r'(?:ITEM|Item)\s*1[Aa][\.\s\-—:]'),
        ("item1a", r'(?:ITEM|Item)\s*1[Aa][\.\s\-—:]+\s*Risk\s*Factor', r'(?:ITEM|Item)\s*1[Bb][\.\s\-—:]'),
        ("item7", r'(?:ITEM|Item)\s*7[\.\s\-—:]+\s*(?:Management|MD)', r'(?:ITEM|Item)\s*7[Aa][\.\s\-—:]'),
    ]

    for key, start_pat, end_pat in patterns:
        starts = list(re.finditer(start_pat, text, re.IGNORECASE))
        if not starts:
            continue
        best = starts[-1]
        end_matches = list(re.finditer(end_pat, text[best.end():], re.IGNORECASE))
        if end_matches:
            end_pos = best.end() + end_matches[0].start()
        else:
            end_pos = best.end() + 50000
        section = text[best.start():min(end_pos, len(text))]
        if len(section) > 200:
            sections[key] = section[:80000]

    return sections


def analyze_with_keywords(sections):
    """关键词匹配提取结构化信息，输出中文框架。"""
    item1 = sections.get("item1", "")
    item1a = sections.get("item1a", "")
    item7 = sections.get("item7", "")

    overview_parts = []
    if item1:
        sentences = re.split(r'(?<=[.!?])\s+', item1[:10000])
        for s in sentences[:30]:
            if len(s) > 30 and any(w in s.lower() for w in
                    ["develop", "design", "manufacture", "provide", "offer",
                     "deliver", "produce", "leading", "global", "technology",
                     "solution", "product", "service", "semiconductor", "optical",
                     "nuclear", "energy", "power", "memory", "chip", "headquartered",
                     "founded", "incorporated", "principal"]):
                overview_parts.append(s.strip())
                if len(overview_parts) >= 5:
                    break

    products = []
    product_patterns = [
        r'(?:our|the company\'?s?)\s+(?:principal |primary |key |main |core )?(?:products?|solutions?|offerings?|services?)\s+(?:include|consist|encompass|are)\s*:?\s*([^.]{20,300})',
        r'(?:we|the company)\s+(?:develop|design|manufacture|produce|offer|provide|sell)s?\s+([^.]{20,200})',
        r'(?:product|segment|division|business unit)s?\s*(?:include|consist of|are)\s*:?\s*([^.]{20,300})',
    ]
    for pat in product_patterns:
        for m in re.finditer(pat, item1[:15000], re.IGNORECASE):
            prod = m.group(1).strip()[:200]
            if len(prod) > 20 and prod not in products:
                products.append(prod)
    products = products[:8]

    customers = []
    customer_patterns = [
        r'(?:significant|major|key|large|principal)\s+(?:customer|client)s?\s+(?:include|are|such as)\s*:?\s*([^.]{10,300})',
        r'(?:customer|client|buyer)s?\s+(?:include|are|consist|such as)\s*:?\s*([^.]{10,300})',
        r'(?:we|the company)\s+(?:sell|provide|supply|deliver)\s+(?:to|for)\s+([^.]{10,200})',
    ]
    for pat in customer_patterns:
        for m in re.finditer(pat, item1[:20000], re.IGNORECASE):
            cust = m.group(1).strip()[:200] if m.lastindex else m.group(0).strip()[:200]
            if len(cust) > 10 and cust not in customers:
                customers.append(cust)
    customers = customers[:6]

    suppliers = []
    supplier_patterns = [
        r'(?:supplier|vendor|source)s?\s+(?:include|are|such as)\s*:?\s*([^.]{10,300})',
        r'(?:we|the company)\s+(?:purchase|procure|source|obtain|buy)\s+(?:from|through)\s+([^.]{10,200})',
        r'(?:sole[\s\-]source|single[\s\-]source|limited[\s\-]supplier)[^.]{10,200}',
    ]
    for pat in supplier_patterns:
        for m in re.finditer(pat, item1[:20000], re.IGNORECASE):
            sup = m.group(1).strip()[:200] if m.lastindex else m.group(0).strip()[:200]
            if len(sup) > 10 and sup not in suppliers:
                suppliers.append(sup)
    suppliers = suppliers[:6]

    compete_parts = []
    compete_patterns = [
        r'(?:compet(?:ition|itive|e|itor))\s+[^.]{10,400}',
        r'(?:market share|market position|competitive advantage|barrier to entry)\s+[^.]{10,300}',
    ]
    for pat in compete_patterns:
        for m in re.finditer(pat, item1[:20000], re.IGNORECASE):
            compete_parts.append(m.group(0).strip()[:250])
    compete_text = " | ".join(compete_parts[:4])

    tech_parts = []
    tech_patterns = [
        r'(?:patent|proprietary technology|trade secret)\s+[^.]{10,300}',
        r'(?:intellectual property)\s+[^.]{10,300}',
        r'(?:barrier to entry|switching cost|lock-in|customer retention)\s+[^.]{10,200}',
    ]
    for pat in tech_patterns:
        for m in re.finditer(pat, item1[:20000], re.IGNORECASE):
            tech_parts.append(m.group(0).strip()[:250])
    tech_text = " | ".join(tech_parts[:4])

    patent_match = re.search(r'(\d+)\s*patents?\s*(?:granted|issued|held|globally|in)', item1[:20000], re.IGNORECASE)
    patent_info = f"（持有{patent_match.group(1)}项专利）" if patent_match else ""

    market_parts = []
    market_patterns = [
        r'(?:total addressable|addressable|TAM|SAM)\s*market\s*[^.]{10,300}',
        r'(?:market\s+(?:size|opportunity|worth|valued|estimated))\s+[^.]{10,300}',
        r'\$\s*\d+(?:\.\d+)?\s*(?:billion|million|trillion)\s+(?:market|opportunity|industry)[^.]{0,200}',
    ]
    for pat in market_patterns:
        for m in re.finditer(pat, item1[:20000] + item7[:10000], re.IGNORECASE):
            market_parts.append(m.group(0).strip()[:200])
    market_text = " | ".join(market_parts[:3]) if market_parts else "（年报未明确披露TAM/SAM）"

    risk_parts = []
    if item1a:
        risk_sentences = re.split(r'(?<=[.!?])\s+', item1a[:12000])
        for s in risk_sentences:
            if len(s) > 40 and any(w in s.lower() for w in
                    ["significant risk", "material adverse", "could harm",
                     "sole source", "single source", "depend on", "rely on",
                     "concentrated", "limited supplier", "geopolitical",
                     "tariff", "regulation", "competition", "customer concentration"]):
                risk_parts.append(s.strip()[:200])
                if len(risk_parts) >= 5:
                    break

    return {
        "business_overview": " ".join(overview_parts) if overview_parts else "（10-K Item 1业务描述提取中，建议启用LLM模式获取更精准的中文摘要）",
        "products_services": products if products else ["（待LLM分析提取产品线详情）"],
        "competitive_position": compete_text if compete_text else "（待LLM分析提取竞争格局）",
        "technology_moat": (tech_text + patent_info) if tech_text else (patent_info or "（待LLM分析提取技术壁垒）"),
        "customers": customers if customers else ["（待LLM分析提取客户信息）"],
        "suppliers": suppliers if suppliers else ["（待LLM分析提取供应商信息）"],
        "risk_factors": " | ".join(risk_parts) if risk_parts else "（待LLM分析提取风险因素）",
        "market_size": market_text,
    }


def analyze_with_llm(sections, api_key, api_url, model):
    """调用LLM API做深度结构化分析（中文输出）。"""
    item1 = sections.get("item1", "")[:30000]
    item1a = sections.get("item1a", "")[:10000]
    item7 = sections.get("item7", "")[:10000]

    prompt = f"""你是一位专业的投资研究分析师。请分析以下公司10-K年报章节，用中文输出结构化研究报告。

## Item 1 - 业务描述（原文节选）:
{item1[:15000]}

## Item 1A - 风险因素（原文节选）:
{item1a[:5000]}

## Item 7 - 管理层讨论与分析（原文节选）:
{item7[:5000]}

请返回JSON格式，所有内容用中文撰写，遵循以下研究框架：

{{
  "business_overview": "公司做什么：用2-3句话概括核心业务、主营产品/服务、在产业链中的位置",
  "products_services": ["产品线1：名称 — 功能描述 — 收入占比（如有）", "产品线2：...", ...],
  "competitive_position": "竞争格局：市场份额、主要竞争对手、差异化优势、行业地位",
  "technology_moat": "技术壁垒/护城河：专利数量、专有技术、客户锁定效应、转换成本、先发优势",
  "customers": ["客户类型/名称 — 关系描述", ...],
  "suppliers": ["供应商/上游依赖 — 替代性分析", ...],
  "risk_factors": "核心风险（按重要性排序）：1. 风险A 2. 风险B 3. 风险C ... （最多5条，每条一句话）",
  "market_size": "市场空间：TAM/SAM规模、增长率、渗透率（引用年报数据）"
}}

要求：
1. 所有内容必须用中文
2. 基于年报原文事实，不要编造数据
3. 竞争格局要点名竞争对手
4. 护城河要具体——专利数量、技术代际差距、客户绑定年限等
5. 风险要聚焦实质性风险，跳过通用法律风险

只返回有效JSON，不要markdown格式。"""

    if "anthropic" in api_url.lower():
        return _call_anthropic(prompt, api_key, api_url, model)
    else:
        return _call_openai_compatible(prompt, api_key, api_url, model)


def _call_anthropic(prompt, api_key, api_url, model):
    url = api_url.rstrip("/")
    if not url.endswith("/messages"):
        url += "/messages"
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    resp = urllib.request.urlopen(req, context=_ctx, timeout=120)
    data = json.loads(resp.read())
    text = data.get("content", [{}])[0].get("text", "")
    return _parse_llm_json(text)


def _call_openai_compatible(prompt, api_key, api_url, model):
    url = api_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    resp = urllib.request.urlopen(req, context=_ctx, timeout=120)
    data = json.loads(resp.read())
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return _parse_llm_json(text)


def _parse_llm_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


def research_ticker(ticker, use_llm=False):
    """完整研究流程: 下载10-K → 提取章节 → 分析 → 入库"""
    print(f"\n{'='*50}")
    print(f"  Researching {ticker}")
    print(f"{'='*50}")

    filepath = fetch_10k(ticker)
    if not filepath:
        print(f"  [SKIP] No 10-K available for {ticker}")
        return False

    text = extract_text(filepath)
    print(f"  10-K text: {len(text)//1000}K chars")

    sections = extract_10k_sections(text)
    print(f"  Extracted sections: {', '.join(sections.keys()) or 'none'}")
    if not sections:
        print(f"  [SKIP] Could not extract sections from {ticker}")
        return False

    llm_result = None
    analysis_source = "10k_extract"

    if use_llm:
        api_key = mdb.get_setting("llm_api_key")
        api_url = mdb.get_setting("llm_api_url", "https://api.anthropic.com/v1")
        model = mdb.get_setting("llm_model", "claude-sonnet-4-20250514")
        if api_key:
            print(f"  Running LLM analysis ({model})...")
            try:
                llm_result = analyze_with_llm(sections, api_key, api_url, model)
                if llm_result:
                    analysis_source = "llm"
                    print(f"  LLM analysis complete")
                else:
                    print(f"  [WARN] LLM returned unparseable response, falling back to keywords")
            except Exception as e:
                print(f"  [ERROR] LLM call failed: {e}, falling back to keywords")
        else:
            print(f"  [INFO] No LLM API key configured, using keyword extraction")

    if llm_result:
        profile = llm_result
    else:
        profile = analyze_with_keywords(sections)

    raw_sections_json = json.dumps(
        {k: v[:5000] for k, v in sections.items()},
        ensure_ascii=False
    )

    _, filing_date = get_latest_10k_url(ticker)

    mdb.save_company_profile(
        ticker=ticker,
        business_overview=profile.get("business_overview", ""),
        products_services=json.dumps(profile.get("products_services", []), ensure_ascii=False),
        competitive_position=profile.get("competitive_position", ""),
        technology_moat=profile.get("technology_moat", ""),
        customers=json.dumps(profile.get("customers", []), ensure_ascii=False),
        suppliers=json.dumps(profile.get("suppliers", []), ensure_ascii=False),
        risk_factors=profile.get("risk_factors", ""),
        market_size=profile.get("market_size", ""),
        raw_sections=raw_sections_json,
        analysis_source=analysis_source,
        last_filing=filing_date,
    )

    print(f"  ✓ Profile saved ({analysis_source})")
    if profile.get("business_overview"):
        print(f"    Overview: {profile['business_overview'][:100]}...")
    if profile.get("products_services"):
        prods = profile["products_services"]
        if isinstance(prods, list):
            print(f"    Products: {len(prods)} items")
    return True


def run_all(use_llm=False):
    """批量研究所有watchlist标的。"""
    mdb.init_db()
    watchlist = mdb.get_watchlist()
    tickers = [w["ticker"] for w in watchlist]
    print(f"Company Researcher — scanning {len(tickers)} tickers")

    success = 0
    for ticker in tickers:
        try:
            if research_ticker(ticker, use_llm=use_llm):
                success += 1
        except Exception as e:
            print(f"  [ERROR] {ticker}: {e}")
        time.sleep(0.5)

    print(f"\nDone: {success}/{len(tickers)} profiles saved")


def main():
    parser = argparse.ArgumentParser(description="Company Researcher — 10-K深度研究")
    parser.add_argument("tickers", nargs="*", help="Ticker symbols (omit for all watchlist)")
    parser.add_argument("--llm", action="store_true", help="Enable LLM analysis")
    args = parser.parse_args()

    mdb.init_db()

    if args.tickers:
        for ticker in args.tickers:
            research_ticker(ticker.upper(), use_llm=args.llm)
            time.sleep(0.5)
    else:
        run_all(use_llm=args.llm)


if __name__ == "__main__":
    main()
