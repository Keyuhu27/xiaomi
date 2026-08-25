"""
DuckDB 连接与建表。

数据库是一个本地文件（data/sales.duckdb），不需要单独起服务。
"""
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sales.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
    date DATE NOT NULL,
    sku_id VARCHAR NOT NULL,
    product_name VARCHAR,
    model VARCHAR,
    category VARCHAR,
    sales_qty BIGINT,
    sales_amount DOUBLE,
    visitors BIGINT,
    conversion_rate DOUBLE,
    source_file VARCHAR,
    imported_at TIMESTAMP DEFAULT current_timestamp
);
"""

# 约定：同一个 date 的数据由 import_data.py 整体删除重建，
# 所以这里不强制 (date, sku_id) 唯一约束，避免不同 DuckDB 版本对
# 约束/upsert 语法支持不一致的问题，保持导入逻辑简单可控。


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if read_only and not DB_PATH.exists():
        # 数据库文件还不存在（比如第一次打开聊天界面、还没导入过数据），
        # 先建好表结构，避免只读模式下打开一个不存在的文件报错。
        tmp = duckdb.connect(str(DB_PATH))
        tmp.execute(SCHEMA)
        tmp.close()

    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
    return con
