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
            "在本地销量数据库（DuckDB）上执行一条只读 SQL 查询（SELECT / WITH），返回结果。"
            "唯一的表是 sales，字段：date (DATE), sku_id, product_name, model, category, "
            "sales_qty (销量/件数), sales_amount (销售额), visitors (访客数), "
            "conversion_rate (转化率), source_file。"
            "一个 sku_id 在同一个 date 只有一行。按型号/商品名称模糊匹配时用 ILIKE '%关键词%'。"
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
            "检测某一天相对过去若干天的销量异常波动（基于历史均值/标准差的 z-score）。"
            "涉及'今天数据是否异常/有没有问题'这类问题时，优先用这个工具，而不是自己写统计 SQL。"
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
