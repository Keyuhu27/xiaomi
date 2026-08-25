"""
本地聊天/看板界面。

启动方式：
    streamlit run src/chat_app.py

在浏览器里用自然语言问销量数据库问题，比如：
    - 今天 Redmi K80 的销量是多少？
    - 今天数据有没有异常？
    - 最近 7 天哪个型号卖得最好？
"""
import os
from datetime import date

import streamlit as st
from anthropic import Anthropic
from dotenv import load_dotenv

from db import get_connection
from tools import TOOLS, dispatch

load_dotenv()

# 需要更省钱可以换成更便宜的型号，比如 claude-haiku-4-5-20251001
MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """你是一个销量数据分析助手，帮助用户查询和分析本地 DuckDB 数据库里的京东商智每日销量数据。
数据库里只有一张表 sales，字段见 run_sql 工具描述。

回答问题时：
- 涉及"今天/某天数据是否有异常"类问题，优先调用 check_anomalies 工具，而不是自己临时写统计 SQL。
- 其它问题（查销量、查销售额、排名、趋势对比等）用 run_sql 工具查询。
- 用简洁的中文回答，给出具体数字，不要只给结论不给数据支撑。
- 如果查不到数据（比如当天还没导入），直接说明，不要编造数字。
"""

st.set_page_config(page_title="销量数据助手", page_icon="📊")
st.title("📊 销量数据助手")

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    st.error("没有找到 ANTHROPIC_API_KEY，请复制 .env.example 为 .env 并填入你的 key，然后重启。")
    st.stop()

client = Anthropic(api_key=api_key)

with st.sidebar:
    st.subheader("今日概览")
    con = get_connection(read_only=True)
    try:
        today = date.today()
        row = con.execute(
            "SELECT COUNT(DISTINCT sku_id), SUM(sales_qty), SUM(sales_amount) "
            "FROM sales WHERE date = ?",
            [today],
        ).fetchone()
    finally:
        con.close()

    if row and row[0]:
        st.metric("在售型号数", row[0])
        st.metric("总销量", int(row[1] or 0))
        st.metric("总销售额", f"¥{row[2]:,.0f}" if row[2] else "¥0")
    else:
        st.info("今天还没有导入数据。把导出的报表放进 data/inbox/，然后运行：\n\npython src/import_data.py")

if "api_messages" not in st.session_state:
    st.session_state.api_messages = []  # 传给 Claude API 的完整历史（含工具调用）
if "display_messages" not in st.session_state:
    st.session_state.display_messages = []  # 只用于在页面上展示的纯文本历史

for msg in st.session_state.display_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


def run_turn(user_text: str) -> str:
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


user_text = st.chat_input("问点什么，比如：今天数据有没有异常？")
if user_text:
    st.session_state.display_messages.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    with st.spinner("分析中..."):
        answer = run_turn(user_text)

    st.session_state.display_messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant"):
        st.markdown(answer)
