"""
新品转化看板：funnel_daily 表——重点新品（Turbo 系列等）的渠道级流量转化数据。
"""
from datetime import timedelta

import streamlit as st

from db import get_connection


def render():
    st.title("🚀 新品转化看板")
    st.caption(
        "数据来自 funnel_daily 表。KPI 和趋势图只看每个系列的整体行（channel_l2 为空），"
        "下面的渠道排名表才是渠道细分明细，两者不要相加。"
    )

    con = get_connection(read_only=True)
    try:
        series_df = con.execute("SELECT DISTINCT series_code FROM funnel_daily ORDER BY series_code").fetchdf()
    finally:
        con.close()

    if series_df.empty:
        st.info("还没有导入 funnel_daily 数据，去左侧「数据导入」页面上传一份新品转化报表试试。")
        return

    series_list = series_df["series_code"].tolist()
    selected_series = st.selectbox("选择产品系列", series_list)
    days = st.slider("查看最近多少天", min_value=7, max_value=90, value=30, step=1)

    con = get_connection(read_only=True)
    try:
        max_date = con.execute(
            "SELECT MAX(date) FROM funnel_daily WHERE series_code = ?", [selected_series]
        ).fetchone()[0]
        start_date = max_date - timedelta(days=days)

        kpi = con.execute(
            "SELECT SUM(pv), SUM(uv), SUM(sales_qty), SUM(sales_amount) "
            "FROM funnel_daily WHERE series_code = ? AND channel_l2 IS NULL AND date BETWEEN ? AND ?",
            [selected_series, start_date, max_date],
        ).fetchone()

        trend_df = con.execute(
            "SELECT date, SUM(pv) AS pv, SUM(uv) AS uv, SUM(sales_qty) AS 销量 "
            "FROM funnel_daily WHERE series_code = ? AND channel_l2 IS NULL AND date BETWEEN ? AND ? "
            "GROUP BY date ORDER BY date",
            [selected_series, start_date, max_date],
        ).fetchdf()

        channel_df = con.execute(
            "SELECT channel_l1, channel_l2, SUM(sales_qty) AS 销量 "
            "FROM funnel_daily WHERE series_code = ? AND date BETWEEN ? AND ? AND channel_l2 IS NOT NULL "
            "GROUP BY channel_l1, channel_l2 ORDER BY 销量 DESC LIMIT 15",
            [selected_series, start_date, max_date],
        ).fetchdf()
    finally:
        con.close()

    st.caption(f"统计区间：{start_date} ~ {max_date}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总浏览量 PV", f"{int(kpi[0] or 0):,}")
    col2.metric("总访客数 UV", f"{int(kpi[1] or 0):,}")
    col3.metric("总销量（件）", f"{int(kpi[2] or 0):,}")
    col4.metric("总成交金额", f"¥{(kpi[3] or 0):,.0f}")

    st.subheader("每日流量趋势（PV / UV）")
    if not trend_df.empty:
        st.line_chart(trend_df.set_index("date")[["pv", "uv"]])
        st.subheader("每日销量趋势")
        st.line_chart(trend_df.set_index("date")["销量"])
    else:
        st.caption("这段时间没有数据")

    st.subheader("渠道销量排名（区间汇总）")
    if not channel_df.empty:
        st.dataframe(channel_df, use_container_width=True, hide_index=True)
    else:
        st.caption("没有渠道明细数据")
