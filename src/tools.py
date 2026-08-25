"""
提供给 Claude 的工具定义（Anthropic tool use）：
  - run_sql：自由的只读 SQL 查询，覆盖大部分"查数字"类问题
  - check_anomalies：内置的异常检测口径，涉及"是否异常"类问题时优先用它，
    避免模型每次现场发明一套统计逻辑，导致结果前后不一致
"""
import json

from anomaly import check_anomalies as _check_anomalies
from db import get_connection

TOOLS = [
    {
        "name": "run_sql",
        "description": (
            "在本地数据库（DuckDB）上执行一条只读 SQL 查询（SELECT / WITH），返回结果。"
            "数据库里有 4 张表，对应京东商智 4 类不同的报表（口径不同，不要混用）：\n"
            "\n"
            "1) sku_daily —— 全量商品每日库存/销量快照，覆盖所有 SKU，回答"
            "'今天/某天某型号卖了多少'优先查这张表。"
            "字段：sales_date(实际销售日期), snapshot_date(导出快照日期), sku_id, product_name, "
            "brand, category_l1/l2/l3, store_name, rdc/distribution_center(区域配送中心/配送"
            "中心), shelf_status, price, stock_qty(库存件数), available_stock(可用库存), "
            "sales_qty(当天销量/出库件数), sales_qty_7d/14d/28d/30d(对应天数的滚动累计销量，不是"
            "单日数据)。同一个 sku_id 在同一个 sales_date 会按 rdc 拆成多行：rdc='全国' 是京东"
            "商智已经算好的全国汇总（一个 sku_id 一天只有一行），其余 rdc=具体城市名的是区域拆分"
            "明细，两者相加会重复计数。查'某型号今天卖了多少'这类总量问题，只查 rdc='全国' 的行"
            "即可，不要对全表 SUM；只有明确要看分城市的区域明细时才用 rdc != '全国' 的行。\n"
            "\n"
            "2) funnel_daily —— 重点新品（如 Redmi Turbo 系列）的每日全链路流量转化数据，"
            "按产品系列(series_code)和渠道(channel_l1/channel_l2)细分，channel_l2 为空的行是该"
            "一级渠道的汇总行。字段：date, series_code, channel_l1, channel_l2, pv(浏览量), "
            "uv(访客数), uv_value, aov(客单价), add_cart_customers(加购), order_customers(下单), "
            "order_amount(下单金额), paying_customers(成交客户数), conversion_rate(成交转化率), "
            "sales_amount(成交金额), sales_qty(成交子单量=销量)，以及对应的 *_yoy 同比字段"
            "（不是所有行都有同比数据）。还有 is_launch_4h/28h/3d/7d/30d 等布尔字段，标记这一天"
            "是否在首销后对应时间窗口内。\n"
            "\n"
            "3) keyword_brand_weekly —— 行业关键词/品牌词条竞对监控，周度数据，覆盖全行业"
            "（不只是自家）。字段：week_date, spu, brand, keyword(关键词), rank(排名), "
            "以及 search_users/search_count/click_users/click_count/sales_amount/sales_qty/"
            "conversion_rate 各自的 _raw（原始区间文本，如'10万~25万'）和 _est（区间中点估算"
            "数值，用于排序/趋势分析，不是精确值，回答时要说明是估算）。\n"
            "\n"
            "4) keyword_sku_rank_weekly —— 关键词/型号下的商品排名竞对监控（含自家和竞品"
            "SKU），周度数据。字段：week_date, spu(型号分类), rank(排名), sku_id, product_info"
            "(商品全名), brand_name, 以及 click_users/click_count/sales_qty/sales_amount 的 "
            "_raw/_est 字段（同上，_est 是区间估算值）。\n"
            "\n"
            "按型号/商品名称模糊匹配时用 ILIKE '%关键词%'。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要执行的 SQL SELECT 语句"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_anomalies",
        "description": (
            "基于 sku_daily 表，检测某一天相对过去若干天的销量异常波动（基于历史均值/标准差的 "
            "z-score）。涉及'今天数据是否异常/有没有问题'这类问题时，优先用这个工具，而不是自己写"
            "统计 SQL。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "要检查的日期，格式 YYYY-MM-DD"},
                "window_days": {"type": "integer", "description": "对比的历史窗口天数，默认 7"},
                "z_threshold": {"type": "number", "description": "判定异常的 z-score 阈值，默认 2.0"},
            },
            "required": ["date"],
        },
    },
]


def run_sql(query: str) -> str:
    stripped = query.strip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        return json.dumps({"error": "只允许执行 SELECT / WITH 查询"}, ensure_ascii=False)

    con = get_connection(read_only=True)
    try:
        df = con.execute(query).fetchdf()
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        con.close()
    return df.to_json(orient="records", force_ascii=False, date_format="iso")


def dispatch(name: str, tool_input: dict) -> str:
    if name == "run_sql":
        return run_sql(tool_input["query"])
    if name == "check_anomalies":
        result = _check_anomalies(
            tool_input["date"],
            tool_input.get("window_days", 7),
            tool_input.get("z_threshold", 2.0),
        )
        return json.dumps(result, ensure_ascii=False, default=str)
    raise ValueError(f"未知工具: {name}")
