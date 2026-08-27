"""
关键词竞对看板：keyword_brand_weekly 表——行业关键词/品牌词条监控（周度，估算值）。
"""
import streamlit as st

from db import get_connection


def render():
    st.title("🔍 关键词竞对监控")
    st.caption(
        "数据来自 keyword_brand_weekly 表，覆盖全行业（不只是自家），周度数据。"
        "带 _est 的字段是脱敏区间的中点估算值，不是精确数字。"
    )

    con = get_connection(read_only=True)
    try:
        brands_df = con.execute(
            "SELECT DISTINCT brand FROM keyword_brand_weekly WHERE brand IS NOT NULL ORDER BY brand"
        ).fetchdf()
    finally:
        con.close()

    if brands_df.empty:
        st.info("还没有导入 keyword_brand_weekly 数据，去左侧「数据导入」页面上传一份关键词竞对报表试试。")
        return

    brand_list = ["全部"] + brands_df["brand"].tolist()
    selected_brand = st.selectbox("筛选品牌", brand_list)
    keyword_filter = st.text_input("按关键词搜索（可选）", "")

    where = []
    params = []
    if selected_brand != "全部":
        where.append("brand = ?")
        params.append(selected_brand)
    if keyword_filter.strip():
        where.append("keyword ILIKE ?")
        params.append(f"%{keyword_filter.strip()}%")
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""

    con = get_connection(read_only=True)
    try:
        df = con.execute(
            f"SELECT week_date, brand, keyword, rank, "
            f"search_users_est, click_users_est, sales_qty_est, sales_amount_est, conversion_rate_est "
            f"FROM keyword_brand_weekly {where_clause} "
            f"ORDER BY week_date DESC, rank ASC LIMIT 500",
            params,
        ).fetchdf()
    finally:
        con.close()

    st.caption("最多显示 500 行，匹配更多时请用上面的筛选条件缩小范围。")
    st.dataframe(df, use_container_width=True, hide_index=True)
