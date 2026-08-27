"""
销量看板：sku_daily 表——全量商品每日库存/出库快照。
"""
from datetime import timedelta

import streamlit as st

from db import get_connection


def render():
    st.title("📦 销量看板")
    st.caption(
        "数据来自 sku_daily 表，只统计 rdc='全国' 的汇总行，不和区域拆分行重复计数。"
        "“估算销售额”是按商品挂牌价 × 销量粗略估算，不是真实成交金额（这张表没有成交金额字段）。"
    )

    con = get_connection(read_only=True)
    try:
        dates_df = con.execute(
            "SELECT DISTINCT sales_date FROM sku_daily ORDER BY sales_date DESC"
        ).fetchdf()
    finally:
        con.close()

    if dates_df.empty:
        st.info("还没有导入 sku_daily 数据，去左侧「数据导入」页面上传一份京东商智的库存/出库明细报表试试。")
        return

    # fetchdf() 把 DATE 列变成 pandas Timestamp，直接显示会带一截 00:00:00，
    # 转成原生 date 对象让下拉框和后面的标题显示更干净。
    available_dates = [d.date() for d in dates_df["sales_date"]]
    selected_date = st.selectbox("选择日期", available_dates, index=0)

    con = get_connection(read_only=True)
    try:
        kpi = con.execute(
            "SELECT COUNT(DISTINCT sku_id), SUM(sales_qty), SUM(sales_qty * price) "
            "FROM sku_daily WHERE sales_date = ? AND rdc = '全国'",
            [selected_date],
        ).fetchone()

        top_df = con.execute(
            "SELECT product_name, sku_id, sales_qty "
            "FROM sku_daily WHERE sales_date = ? AND rdc = '全国' "
            "ORDER BY sales_qty DESC LIMIT 15",
            [selected_date],
        ).fetchdf()

        trend_df = con.execute(
            "SELECT sales_date, SUM(sales_qty) AS total_qty "
            "FROM sku_daily WHERE rdc = '全国' AND sales_date >= ? "
            "GROUP BY sales_date ORDER BY sales_date",
            [selected_date - timedelta(days=30)],
        ).fetchdf()
    finally:
        con.close()

    col1, col2, col3 = st.columns(3)
    col1.metric("在售 SKU 数", kpi[0] or 0)
    col2.metric("当日总销量（件）", int(kpi[1] or 0))
    col3.metric("估算销售额（元）", f"¥{(kpi[2] or 0):,.0f}")

    st.subheader("最近 30 天总销量趋势")
    if not trend_df.empty:
        st.line_chart(trend_df.set_index("sales_date")["total_qty"])
    else:
        st.caption("暂无趋势数据")

    st.subheader(f"{selected_date} 畅销 Top 15")
    if not top_df.empty:
        st.bar_chart(top_df.set_index("product_name")["sales_qty"])
        st.dataframe(top_df, use_container_width=True, hide_index=True)
    else:
        st.caption("这一天没有销量数据")
