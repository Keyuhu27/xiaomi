"""
关键词竞对看板：keyword_brand_daily 表——行业关键词/品牌词条监控（每日，估算值）。

三个视图（对应用户的三个需求）：
  - 📅 单日排名：挑一天，看当天全部关键词的排名/搜索人数/成交单量/成交转化率
  - 📈 搜索趋势：挑几个关键词 + 一段时间，看这几项指标的走势
  - 🏷️ 品牌排名汇总：挑一天，把当天的排名按品牌拆成并排的几列（对照京东热搜榜单的
    "各品牌一列"的看法）
"""
import streamlit as st

from db import get_connection

_METRIC_COLS = [
    "date", "rank", "brand", "spu", "keyword",
    "search_users_raw", "search_users_est",
    "sales_qty_raw", "sales_qty_est",
    "conversion_rate_raw", "conversion_rate_est",
]


def _get_dates(con):
    # fetchdf() 把 DATE 列变成 pandas Timestamp，转成原生 date 对象，
    # 不然下拉框/日期选择器会带一截 00:00:00，st.date_input 的
    # min_value/max_value 也需要干净的 date 对象。
    raw = con.execute("SELECT DISTINCT date FROM keyword_brand_daily ORDER BY date DESC").fetchdf()["date"]
    return [d.date() for d in raw]


def _render_daily_rank(con, dates):
    st.subheader("选一天，看当天全部关键词的排名")
    selected_date = st.selectbox("日期", dates, index=0, key="kbd_daily_date")

    brands_df = con.execute(
        "SELECT DISTINCT brand FROM keyword_brand_daily WHERE brand IS NOT NULL ORDER BY brand"
    ).fetchdf()
    brand_options = ["全部"] + brands_df["brand"].tolist()
    col1, col2 = st.columns([1, 2])
    selected_brand = col1.selectbox("品牌筛选", brand_options, key="kbd_daily_brand")
    keyword_filter = col2.text_input("关键词包含（可选）", "", key="kbd_daily_kw")

    where = ["date = ?"]
    params = [selected_date]
    if selected_brand != "全部":
        where.append("brand = ?")
        params.append(selected_brand)
    if keyword_filter.strip():
        where.append("keyword ILIKE ?")
        params.append(f"%{keyword_filter.strip()}%")

    df = con.execute(
        f"SELECT {', '.join(_METRIC_COLS)} FROM keyword_brand_daily "
        f"WHERE {' AND '.join(where)} ORDER BY rank ASC LIMIT 500",
        params,
    ).fetchdf()

    st.caption(f"{selected_date} 共 {len(df)} 条（最多显示 500 行，用筛选条件缩小范围看更多）")
    st.dataframe(df, use_container_width=True, hide_index=True, height=600)


def _render_trend(con, dates):
    st.subheader("选几个关键词 + 一段时间，看指标走势")
    min_date, max_date = dates[-1], dates[0]

    kw_filter = st.text_input("先按关键词包含筛一批候选（比如 'turbo5'）", "", key="kbd_trend_kwfilter")
    if not kw_filter.strip():
        st.info("先输入一个关键词片段筛一批候选，再从下面选具体要看的关键词。")
        return

    candidates_df = con.execute(
        "SELECT DISTINCT keyword FROM keyword_brand_daily "
        "WHERE keyword IS NOT NULL AND keyword ILIKE ? ORDER BY keyword LIMIT 200",
        [f"%{kw_filter.strip()}%"],
    ).fetchdf()
    candidate_list = candidates_df["keyword"].tolist()

    if not candidate_list:
        st.info("没有匹配的关键词，换个筛选词试试。")
        return

    selected_keywords = st.multiselect(
        "选关键词（最多建议选 8 个，太多线会挤在一起看不清）",
        candidate_list,
        default=candidate_list[: min(5, len(candidate_list))],
        key="kbd_trend_kw",
    )
    date_range = st.date_input(
        "时间范围", value=(min_date, max_date), min_value=min_date, max_value=max_date,
        key="kbd_trend_range",
    )
    if not selected_keywords or not isinstance(date_range, tuple) or len(date_range) != 2:
        st.info("选至少一个关键词、并选好完整的时间范围。")
        return

    start_date, end_date = date_range
    placeholders = ", ".join(["?"] * len(selected_keywords))
    df = con.execute(
        f"SELECT date, keyword, search_users_est, sales_qty_est, conversion_rate_est "
        f"FROM keyword_brand_daily "
        f"WHERE keyword IN ({placeholders}) AND date BETWEEN ? AND ? "
        f"ORDER BY date",
        [*selected_keywords, start_date, end_date],
    ).fetchdf()

    if df.empty:
        st.caption("这段时间没有匹配的数据")
        return

    st.caption("以下都是脱敏区间的中点估算值，不是精确数字，仅用于看趋势方向。")

    st.markdown("**搜索人数趋势（估算）**")
    st.line_chart(df.pivot(index="date", columns="keyword", values="search_users_est"))

    st.markdown("**成交单量趋势（估算）**")
    st.line_chart(df.pivot(index="date", columns="keyword", values="sales_qty_est"))

    st.markdown("**成交转化率趋势（估算）**")
    st.line_chart(df.pivot(index="date", columns="keyword", values="conversion_rate_est"))


def _render_brand_summary(con, dates):
    st.subheader("选一天，按品牌拆开看排名（对照京东热搜榜单的排法）")
    selected_date = st.selectbox("日期", dates, index=0, key="kbd_summary_date")

    brands_df = con.execute(
        "SELECT DISTINCT brand FROM keyword_brand_daily "
        "WHERE brand IS NOT NULL AND date = ? ORDER BY brand",
        [selected_date],
    ).fetchdf()
    brand_list = brands_df["brand"].tolist()
    if not brand_list:
        st.info("这一天没有数据")
        return

    df = con.execute(
        "SELECT brand, rank, keyword, search_users_raw, search_users_est "
        "FROM keyword_brand_daily WHERE date = ? ORDER BY rank ASC",
        [selected_date],
    ).fetchdf()

    cols = st.columns(len(brand_list))
    for col, brand in zip(cols, brand_list):
        with col:
            st.markdown(f"**{brand}**")
            sub = df[df["brand"] == brand][["rank", "keyword", "search_users_est"]]
            st.dataframe(sub, use_container_width=True, hide_index=True, height=500)


def render():
    st.title("🔍 关键词竞对监控")
    st.caption(
        "数据来自 keyword_brand_daily 表，覆盖全行业（不只是自家），每日数据。"
        "带 _est 的字段是脱敏区间的中点估算值，不是精确数字。"
    )

    con = get_connection(read_only=True)
    try:
        dates = _get_dates(con)
        if not dates:
            st.info("还没有导入 keyword_brand_daily 数据，去左侧「数据导入」页面上传一份关键词竞对报表试试。")
            return

        tab1, tab2, tab3 = st.tabs(["📅 单日排名", "📈 搜索趋势", "🏷️ 品牌排名汇总"])
        with tab1:
            _render_daily_rank(con, dates)
        with tab2:
            _render_trend(con, dates)
        with tab3:
            _render_brand_summary(con, dates)
    finally:
        con.close()
