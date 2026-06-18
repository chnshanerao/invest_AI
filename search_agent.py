"""
有搜索能力的 Claude Agent
工具：SerpAPI（https://serpapi.com，100次/月免费）或 mock 模式
"""
import os
import json
import requests
import anthropic

client = anthropic.Anthropic()
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

# ── 系统提示（会被 prompt cache，重复请求省钱）──────────────────────────
SYSTEM = """你是一个专业的投资研究分析师。

规则：
- 凡是涉及实时数据（股价、估值、最新融资、近期新闻）必须先搜索，不得凭记忆回答
- 搜索后整合多个来源，给出有数字支撑的结论
- 对不确定的数据注明信息来源和日期"""

# ── 工具定义 ────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "web_search",
        "description": "搜索互联网获取最新信息。用于：股价、估值、融资动态、行业新闻等实时数据。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索词，中英文均可"},
                "num":   {"type": "integer", "description": "返回条数，默认5", "default": 5}
            },
            "required": ["query"]
        }
    }
]


# ── 工具实现 ────────────────────────────────────────────────────────────
def web_search(query: str, num: int = 5) -> str:
    if not SERPAPI_KEY:
        # 未配置 key 时返回 mock，方便测试代码流程
        return json.dumps({
            "note": "MOCK MODE — 设置 SERPAPI_KEY 环境变量获取真实结果",
            "results": [{"title": f"[mock] {query}", "snippet": "模拟结果内容", "link": "https://example.com"}]
        }, ensure_ascii=False)

    try:
        r = requests.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": SERPAPI_KEY, "num": num, "hl": "zh-cn"},
            timeout=10
        )
        data = r.json()
        results = [
            {"title": x.get("title"), "snippet": x.get("snippet"), "link": x.get("link"), "date": x.get("date")}
            for x in data.get("organic_results", [])[:num]
        ]
        return json.dumps({"query": query, "results": results}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def run_tool(name: str, inputs: dict) -> str:
    if name == "web_search":
        return web_search(inputs["query"], inputs.get("num", 5))
    return json.dumps({"error": f"unknown tool: {name}"})


# ── Agent Loop ──────────────────────────────────────────────────────────
def agent(question: str, max_rounds: int = 8) -> str:
    """
    标准 tool-use agent loop：
      用户消息 → Claude决策 → 若调工具 → 执行 → 结果还给Claude → 再决策 → 直到end_turn
    """
    messages = [{"role": "user", "content": question}]
    tool_call_count = 0

    for round_n in range(1, max_rounds + 1):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            # Prompt Caching：系统提示词固定，打上缓存标记
            # 同一系统提示的后续请求只收 0.1x 费用
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages
        )

        # 缓存命中情况（调试用）
        u = response.usage
        cache_hit = getattr(u, "cache_read_input_tokens", 0)
        print(f"[round {round_n}] stop={response.stop_reason} | "
              f"tokens(in={u.input_tokens} cache_read={cache_hit} out={u.output_tokens})")

        # 将 assistant 完整回复追加到对话历史
        # ⚠️ 必须追加完整 content（含 tool_use block），不能只追加文本
        messages.append({"role": "assistant", "content": response.content})

        # 完成 → 返回文本答案
        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text
            return "(no text output)"

        # 工具调用 → 执行所有工具，把结果一次性返回
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_call_count += 1
                    print(f"  → {block.name}({json.dumps(block.input, ensure_ascii=False)[:80]})")
                    result = run_tool(block.name, block.input)
                    print(f"  ← {len(result)} chars")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,   # 必须与 tool_use block 的 id 对应
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})

    return f"超过最大轮次 {max_rounds}（共调用工具 {tool_call_count} 次）"


# ── 主程序 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    q = "判断智谱AI的企业价值，给出具体数字估算。你有搜索能力，请先搜索获取最新信息再作判断。"
    print(f"问题: {q}\n{'─'*60}")
    answer = agent(q)
    print(f"\n{'─'*60}\n答案:\n{answer}")
