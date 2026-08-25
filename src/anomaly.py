"""
简单的异常检测口径，供 LLM 工具调用，避免模型每次都要临时编统计逻辑
（口径不稳定、容易前后不一致）。

基于 sku_daily 表（全量商品每日出库/销量快照）。口径：把某个 SKU 在目标
销售日期(sales_date)的销量(sales_qty)，和它过去 window_days 天（不含当天）
的均值/标准差比较，算出 z-score，超过 z_threshold 就认为是异常波动。

局限：如果数据库里历史天数不够（比如刚上线没几天），大部分 SKU 还算不出
标准差，这时候不会报出异常，这是预期行为，不是 bug。
"""
from datetime import date, timedelta

from db import get_connection

DEFAULT_WINDOW_DAYS = 7
DEFAULT_Z_THRESHOLD = 2.0

_QUERY = """
-- 注意：sku_daily 里每个 SKU 每天有一行 rdc='全国'（京东商智已经算好的全国汇总），
-- 另外还有若干 rdc=具体城市 的区域拆分行，二者相加会重复计数，
-- 所以这里只取 rdc='全国' 的行，不能对全表 SUM。
WITH today AS (
    SELECT sku_id, ANY_VALUE(product_name) AS product_name, ANY_VALUE(brand) AS brand,
           SUM(sales_qty) AS today_qty
    FROM sku_daily
    WHERE sales_date = ? AND rdc = '全国'
    GROUP BY sku_id
),
history AS (
    SELECT sku_id, AVG(daily_qty) AS avg_qty, STDDEV_SAMP(daily_qty) AS std_qty
    FROM (
        SELECT sku_id, sales_date, SUM(sales_qty) AS daily_qty
        FROM sku_daily
        WHERE sales_date >= ? AND sales_date < ? AND rdc = '全国'
        GROUP BY sku_id, sales_date
    )
    GROUP BY sku_id
)
SELECT
    t.sku_id, t.product_name, t.brand, t.today_qty,
    h.avg_qty, h.std_qty,
    (t.today_qty - h.avg_qty) / h.std_qty AS z_score
FROM today t
JOIN history h ON h.sku_id = t.sku_id
WHERE h.std_qty IS NOT NULL AND h.std_qty > 0
  AND ABS((t.today_qty - h.avg_qty) / h.std_qty) >= ?
ORDER BY ABS((t.today_qty - h.avg_qty) / h.std_qty) DESC
"""


def check_anomalies(
    target_date: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> list[dict]:
    """返回 target_date 当天，相比过去 window_days 天波动超过 z_threshold 个标准差的 SKU 列表。"""
    d = date.fromisoformat(target_date)
    window_start = d - timedelta(days=window_days)

    con = get_connection(read_only=True)
    try:
        rows = con.execute(_QUERY, [d, window_start, d, z_threshold]).fetchdf()
    finally:
        con.close()
    return rows.to_dict(orient="records")
