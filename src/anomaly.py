"""
简单的异常检测口径，供 LLM 工具调用，避免模型每次都要临时编统计逻辑
（口径不稳定、容易前后不一致）。

口径：把某个商品在目标日期的销量，和它过去 window_days 天（不含当天）
的均值/标准差比较，算出 z-score，超过 z_threshold 就认为是异常波动。

局限：如果数据库里历史天数不够（比如刚上线没几天），大部分商品还算不出
标准差，这时候不会报出异常，这是预期行为，不是 bug。
"""
from datetime import date, timedelta

from db import get_connection

DEFAULT_WINDOW_DAYS = 7
DEFAULT_Z_THRESHOLD = 2.0

_QUERY = """
WITH today AS (
    SELECT sku_id, ANY_VALUE(product_name) AS product_name, ANY_VALUE(model) AS model,
           SUM(sales_qty) AS today_qty
    FROM sales
    WHERE date = ?
    GROUP BY sku_id
),
history AS (
    SELECT sku_id, AVG(daily_qty) AS avg_qty, STDDEV_SAMP(daily_qty) AS std_qty
    FROM (
        SELECT sku_id, date, SUM(sales_qty) AS daily_qty
        FROM sales
        WHERE date >= ? AND date < ?
        GROUP BY sku_id, date
    )
    GROUP BY sku_id
)
SELECT
    t.sku_id, t.product_name, t.model, t.today_qty,
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
    """返回 target_date 当天，相比过去 window_days 天波动超过 z_threshold 个标准差的商品列表。"""
    d = date.fromisoformat(target_date)
    window_start = d - timedelta(days=window_days)

    con = get_connection(read_only=True)
    try:
        rows = con.execute(_QUERY, [d, window_start, d, z_threshold]).fetchdf()
    finally:
        con.close()
    return rows.to_dict(orient="records")
