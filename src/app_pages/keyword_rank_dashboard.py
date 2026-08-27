"""
商品排名竞对看板：keyword_sku_rank_weekly 表——关键词/型号下的商品排名监控（周度，估算值）。
"""
import streamlit as st

from db import get_connection


def render():
    st.title("🏆 商品排名竞对监控")
    st.caption(
        "数据来自 keyword_sku_rank_weekly 表，含自家和竞品 SKU，周度数据。"
        "带 _est 的字段是脱敏区间的中点估算值，不是精确数字。"
    )

    con = get_connection(read_only=True)
    try:
        spu_df = con.execute(
            "SELECT DISTINCT spu FROM keyword_sku_rank_weekly WHERE spu IS NOT NULL ORDER BY spu"
        ).fetchdf()
    finally:
        con.close()

    if spu_df.empty:
        st.info("还没有导入 keyword_sku_rank_weekly 数据，去左侧「数据导入」页面上传一份商品排名竞对报表试试。")
        return

    spu_list = spu_df["spu"].tolist()
    selected_spu = st.selectbox("选择型号分类（SPU）", spu_list)

    con = get_connection(read_only=True)
    try:
        df = con.execute(
            "SELECT week_date, rank, brand_name, product_info, "
            "click_users_est, sales_qty_est, sales_amount_est "
            "FROM keyword_sku_rank_weekly WHERE spu = ? "
            "ORDER BY week_date DESC, rank ASC LIMIT 200",
            [selected_spu],
        ).fetchdf()
    finally:
        con.close()

    st.dataframe(df, use_container_width=True, hide_index=True)
