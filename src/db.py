"""
DuckDB 连接与建表。

数据库是一个本地文件（data/sales.duckdb），不需要单独起服务。

数据库里有 4 张表，对应京东商智 4 类不同的报表（不是同一张"销量表"，
详见 README）：
  - sku_daily              全量商品每日库存/出库快照，覆盖所有 SKU，
                            是回答"今天/某天某型号卖了多少"最核心的表
  - funnel_daily            重点新品（如 Redmi Turbo 系列）的每日全链路
                            流量转化数据，按渠道细分
  - keyword_brand_weekly     行业关键词/品牌词条竞对监控（周度，数值多为
                            脱敏区间估算值）
  - keyword_sku_rank_weekly   关键词/型号下的商品排名竞对监控（周度，同上）
"""
import os
from pathlib import Path

import duckdb

# 本地开发默认用仓库里的 data/ 目录；部署到 Railway 时把 DATA_DIR 环境变量
# 指向挂载的持久化 volume（比如 /data），这样数据库文件不会在每次重新部署
# 时被清空。
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "sales.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sku_daily (
    sales_date DATE NOT NULL,       -- 实际发生销售的日期（= 快照日期的前一天）
    snapshot_date DATE NOT NULL,    -- 导出快照当天的日期
    sku_id VARCHAR NOT NULL,
    product_name VARCHAR,
    brand VARCHAR,
    category_l1 VARCHAR,
    category_l2 VARCHAR,
    category_l3 VARCHAR,
    store_name VARCHAR,
    rdc VARCHAR,                    -- 区域配送中心（同一个 SKU 同一天会按 RDC/配送中心拆成多行）
    distribution_center VARCHAR,    -- 配送中心
    shelf_status VARCHAR,           -- 上下柜状态
    price DOUBLE,
    stock_qty BIGINT,               -- 库存件数
    available_stock BIGINT,         -- 可用库存
    sales_qty BIGINT,               -- 昨日出库商品件数，即 sales_date 当天的销量
    sales_qty_7d BIGINT,            -- 近7日出库商品件数（滚动汇总，非单日）
    sales_qty_14d BIGINT,
    sales_qty_28d BIGINT,
    sales_qty_30d BIGINT,
    source_file VARCHAR,
    imported_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS funnel_daily (
    date DATE NOT NULL,
    series_code VARCHAR NOT NULL,   -- 数据源sheet名，如 P10/P10U/O10/O10U，对应机型见 README
    week_report VARCHAR,
    week_meeting VARCHAR,
    traffic_source VARCHAR,         -- 聚合来源
    core_node VARCHAR,              -- 核心节点
    is_last_7d BOOLEAN,
    is_last_14d BOOLEAN,
    is_reservation_period BOOLEAN,
    is_launch_4h BOOLEAN,
    is_launch_28h BOOLEAN,
    is_launch_3d BOOLEAN,
    is_launch_7d BOOLEAN,
    is_launch_30d BOOLEAN,
    channel_l1 VARCHAR,
    channel_l2 VARCHAR,
    pv BIGINT, pv_yoy DOUBLE,
    uv BIGINT, uv_yoy DOUBLE,
    pv_per_uv DOUBLE, pv_per_uv_yoy DOUBLE,
    avg_stay_seconds DOUBLE, avg_stay_seconds_yoy DOUBLE,
    uv_value DOUBLE, uv_value_yoy DOUBLE,
    aov DOUBLE, aov_yoy DOUBLE,
    add_cart_customers BIGINT, add_cart_customers_yoy DOUBLE,
    follow_customers BIGINT, follow_customers_yoy DOUBLE,
    add_cart_rate DOUBLE, add_cart_rate_yoy DOUBLE,
    order_customers BIGINT, order_customers_yoy DOUBLE,
    order_rate DOUBLE, order_rate_yoy DOUBLE,
    order_amount DOUBLE, order_amount_yoy DOUBLE,
    paying_customers BIGINT, paying_customers_yoy DOUBLE,
    conversion_rate DOUBLE, conversion_rate_yoy DOUBLE,
    sales_amount DOUBLE, sales_amount_yoy DOUBLE,   -- 成交金额
    sales_qty BIGINT, sales_qty_yoy DOUBLE,         -- 成交子单量 = 销量
    source_file VARCHAR,
    imported_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS keyword_brand_weekly (
    week_date DATE NOT NULL,        -- 该周对应的日期
    year VARCHAR, month VARCHAR, week VARCHAR,
    spu VARCHAR,
    entry_type VARCHAR,             -- 词条性质
    brand VARCHAR,
    sub_brand VARCHAR,               -- 子品牌
    is_last_14d BOOLEAN,
    rank INTEGER,
    keyword VARCHAR,
    search_users_raw VARCHAR, search_users_est DOUBLE,
    search_count_raw VARCHAR, search_count_est DOUBLE,
    click_users_raw VARCHAR, click_users_est DOUBLE,
    click_count_raw VARCHAR, click_count_est DOUBLE,
    click_rate_raw VARCHAR, click_rate_est DOUBLE,
    sales_amount_raw VARCHAR, sales_amount_est DOUBLE,
    sales_qty_raw VARCHAR, sales_qty_est DOUBLE,
    conversion_rate_raw VARCHAR, conversion_rate_est DOUBLE,
    online_sku_count BIGINT,
    source_file VARCHAR,
    imported_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS keyword_sku_rank_weekly (
    week_date DATE NOT NULL,
    spu VARCHAR,                    -- 型号分类，比如 K80、一加Ace5（含竞品）
    is_last_14d_1 BOOLEAN,          -- 原表里的"是近14天"列
    brand VARCHAR,
    month VARCHAR, week VARCHAR,
    is_last_14d_2 BOOLEAN,          -- 原表里的"是否近14天"列（和上面是两个独立列）
    rank INTEGER,
    sku_id VARCHAR,
    product_info VARCHAR,
    brand_id VARCHAR,
    brand_name VARCHAR,
    click_users_raw VARCHAR, click_users_est DOUBLE,
    click_count_raw VARCHAR, click_count_est DOUBLE,
    sales_qty_raw VARCHAR, sales_qty_est DOUBLE,     -- 成交单量
    sales_amount_raw VARCHAR, sales_amount_est DOUBLE,
    source_file VARCHAR,
    imported_at TIMESTAMP DEFAULT current_timestamp
);
"""


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
