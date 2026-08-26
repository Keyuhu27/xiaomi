"""
聊天/看板界面。本地跑，或者部署到 Railway 这类平台上都可以用。

本地启动方式：
    streamlit run src/chat_app.py

在浏览器里用自然语言问销量数据库问题，比如：
    - 今天 Redmi K80 的销量是多少？
    - 今天数据有没有异常？
    - 最近 7 天哪个型号卖得最好？

数据更新：在左侧"数据导入"里直接上传京东商智相关的 Excel 文件即可，不需要
命令行（部署到 Railway 后没有本地文件系统可放 data/inbox/，只能这样传）。
"""
import os

import streamlit as st
from anthropic import Anthropic
from dotenv import load_dotenv

from db import get_connection
from import_data import import_workbook
from tools import TOOLS, dispatch

load_dotenv()

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

st.set_page_config(page_title="销量数据助手", page_icon="📊")


def _check_password() -> bool:
    """
    简单的共享密码门：设置了 APP_PASSWORD 环境变量才会启用。部署到 Railway
    之类的公网环境时务必设置这个变量，不然任何拿到 URL 的人都能进来问数据、
    消耗你的 Claude API 额度。本地开发不设置这个变量就不会要求输入密码。
    """
    app_password = os.environ.get("APP_PASSWORD")
    if not app_password:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("📊 销量数据助手")
    pwd = st.text_input("请输入访问密码", type="password")
    if pwd:
        if pwd == app_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("密码不对")
    return False


if not _check_password():
    st.stop()

st.title("📊 销量数据助手")

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    st.error("没有找到 ANTHROPIC_API_KEY，请配置这个环境变量后重启（本地开发可以复制 .env.example 为 .env）。")
    st.stop()

client = Anthropic(api_key=api_key)

with st.sidebar:
    st.subheader("数据导入")
    uploaded_files = st.file_uploader(
        "把京东商智相关的 Excel 文件拖到这里（可一次选多个）",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
    )
    with st.expander("高级选项"):
        series_code_override = st.text_input(
            "强制指定系列代号（如 O10U）",
            value="",
            help=(
                "只有单独重新导出某个系列部分时间的修正文件、sheet 名不是"
                "'数据源XXX'格式时才需要填；正常的完整模板文件留空即可"
            ),
        ).strip() or None

    if uploaded_files and st.button("开始导入", type="primary"):
        for f in uploaded_files:
            with st.spinner(f"正在导入 {f.name} ..."):
                try:
                    summary = import_workbook(f, source_name=f.name, series_code_override=series_code_override)
                    if summary:
                        for sheet_name, report_type, n in summary:
                            st.success(f"{f.name} / {sheet_name} → {report_type}：{n} 行")
                    else:
                        st.warning(f"{f.name} 里没有识别出已知的报表类型（汇总/透视表 sheet 会被跳过）")
                except Exception as e:
                    st.error(f"{f.name} 导入失败：{e}")

    st.divider()
    st.subheader("今日概览（sku_daily）")
    con = get_connection(read_only=True)
    try:
        latest_date = con.execute("SELECT MAX(sales_date) FROM sku_daily").fetchone()[0]
        row = None
        if latest_date:
            # rdc='全国' 是京东商智已经算好的全国汇总行，不能再对全表 SUM（会和区域拆分行重复计数）
            row = con.execute(
                "SELECT COUNT(DISTINCT sku_id), SUM(sales_qty) FROM sku_daily "
                "WHERE sales_date = ? AND rdc = '全国'",
                [latest_date],
            ).fetchone()
    finally:
        con.close()

    if row and row[0]:
        st.caption(f"最新销售日期：{latest_date}")
        st.metric("在售 SKU 数", row[0])
        st.metric("总销量（件）", int(row[1] or 0))
    else:
        st.info("还没有导入数据，用上面的\"数据导入\"上传一份京东商智相关的 Excel 文件试试。")

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
