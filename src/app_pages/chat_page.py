"""
聊天问答页面：用自然语言问销量数据库问题。
"""
import os

import streamlit as st
from anthropic import Anthropic

from tools import TOOLS, dispatch

# 需要更省钱可以换成更便宜的型号，比如 claude-haiku-4-5-20251001
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """你是一个销量数据分析助手，帮助用户查询和分析本地 DuckDB 数据库里的京东商智数据。
数据库里有 4 张表，对应 4 类不同的京东商智报表，字段和口径的详细说明见 run_sql 工具描述，
关键区别：
- sku_daily：全量商品每日销量快照，回答"今天/某天卖了多少"优先查这张表。
- funnel_daily：重点新品（Turbo 系列等）的渠道级流量转化数据。
- keyword_brand_weekly / keyword_sku_rank_weekly：行业关键词竞对监控，周度，数值多是脱敏区间的
  估算值（字段名带 _est），不是精确数字，涉及这两张表的数字要提醒用户这是估算。

回答问题时：
- 涉及"今天/某天数据是否有异常"类问题，优先调用 check_anomalies 工具，而不是自己临时写统计 SQL
  （这个工具基于 sku_daily 表）。
- 其它问题（查销量、查销售额、排名、趋势对比等）用 run_sql 工具查询，先想清楚该查哪张表。
- 用简洁的中文回答，给出具体数字，不要只给结论不给数据支撑。
- 如果查不到数据（比如当天还没导入），直接说明，不要编造数字。
"""


def _run_turn(client, user_text: str) -> str:
    st.session_state.api_messages.append({"role": "user", "content": user_text})
    messages = st.session_state.api_messages

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text")

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = dispatch(block.name, block.input)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )
        messages.append({"role": "user", "content": tool_results})


def render():
    st.title("💬 聊天问答")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("没有找到 ANTHROPIC_API_KEY，请配置这个环境变量后重启（本地开发可以复制 .env.example 为 .env）。")
        st.stop()

    client = Anthropic(api_key=api_key)

    if "api_messages" not in st.session_state:
        st.session_state.api_messages = []  # 传给 Claude API 的完整历史（含工具调用）
    if "display_messages" not in st.session_state:
        st.session_state.display_messages = []  # 只用于在页面上展示的纯文本历史

    for msg in st.session_state.display_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_text = st.chat_input("问点什么，比如：今天数据有没有异常？")
    if user_text:
        st.session_state.display_messages.append({"role": "user", "content": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)

        with st.spinner("分析中..."):
            answer = _run_turn(client, user_text)

        st.session_state.display_messages.append({"role": "assistant", "content": answer})
        with st.chat_message("assistant"):
            st.markdown(answer)
