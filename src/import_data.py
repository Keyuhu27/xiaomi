"""
把京东商智相关的 Excel 模板文件（如"数据源"sheet 里累积的历史数据）解析后
写入本地 DuckDB。

用法：
    python src/import_data.py                       # 处理 data/inbox/ 目录下所有文件
    python src/import_data.py path/to/file.xlsx      # 只处理指定文件

这个脚本不是按"文件"识别数据类型，而是打开工作簿后逐个 sheet 检查表头，
自动识别出 4 种已知的京东商智报表类型（sku_daily / funnel_daily /
keyword_brand_daily / keyword_sku_rank_daily，具体字段含义见 README 和
src/db.py 里的表结构注释），认不出的 sheet（汇总、透视表之类）会跳过。

日常使用流程：每天把京东商智下载的新数据粘贴进 Excel 模板对应的"数据源"
sheet 里（和你原来手工维护模板的习惯一样），然后把整份模板文件丢进
data/inbox/ 运行本脚本即可——重复导入同一天/同一系列/同一文件的数据会被
整体替换，不会产生重复行。
"""
import argparse
from datetime import timedelta
from pathlib import Path

import pandas as pd

from db import DATA_DIR, get_connection
from parsing import parse_range_estimate, to_bool_cn, to_date, to_float, to_id_str, to_int, to_text

INBOX_DIR = DATA_DIR / "inbox"
PROCESSED_DIR = INBOX_DIR / "processed"

# 每种报表用哪些列做"整体替换"的分区键：重新导入时，先删掉这些列取值都
# 相同的旧数据，再整体插入新数据，这样同一份数据重复导入不会重复计数。
# funnel_daily 用 (series_code, date) 而不是只用 series_code：这样不管是
# 重新导出某个系列的完整历史，还是只补传某一段时间的修正数据，都只会替换
# 文件里实际包含的那些日期，不会把该系列其它日期的历史数据一并删掉。
# keyword_brand_daily / keyword_sku_rank_daily 同理按 date 分区（这两张表
# 最初误以为是周度数据、按 source_file 整体替换，后来确认其实是每日数据，
# 改成按 date 分区更稳妥：以后不管是重新导出全量历史、还是只导出某一天的
# 增量，都只会替换对应日期的数据）。
PARTITION_COL = {
    "funnel_daily": ["series_code", "date"],
    "sku_daily": ["sales_date"],                # 按销售日期整体替换
    "keyword_brand_daily": ["date"],
    "keyword_sku_rank_daily": ["date"],
}

# 各指标的"成交子单量"等字段是整数、还是比率/金额这种浮点数
_FUNNEL_INT_METRICS = {
    "pv", "uv", "add_cart_customers", "follow_customers",
    "order_customers", "paying_customers", "sales_qty",
}
_FUNNEL_METRIC_FIELDS = {
    "浏览量(PV)": "pv",
    "访客数(UV)": "uv",
    "人均浏览量(人均PV)": "pv_per_uv",
    "平均停留时长(秒)": "avg_stay_seconds",
    "UV价值": "uv_value",
    "客单价": "aov",
    "加购客户数": "add_cart_customers",
    "关注客户数": "follow_customers",
    "加购转换率": "add_cart_rate",
    "下单客户数": "order_customers",
    "下单转换率": "order_rate",
    "下单金额": "order_amount",
    "成交客户数": "paying_customers",
    "成交转化率": "conversion_rate",
    "成交金额": "sales_amount",
    "成交子单量": "sales_qty",
}


def _raw(v):
    """保留原始文本，但把 pandas 读表格时整列被转成 float 导致的'8073.0'这种
    尾巴清理掉，恢复成'8073'（不影响真正的区间文本，如'10万~25万'本来就是字符串）。"""
    if v is None or (isinstance(v, float) and v != v):  # v != v 即 NaN
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def detect_report_type(header: list) -> str | None:
    hs = {h for h in header if h is not None}
    if {"浏览量(PV)", "成交子单量", "一级渠道"} <= hs:
        return "funnel_daily"
    if {"SKU", "库存件数", "昨日出库商品件数", "一级类目"} <= hs:
        return "sku_daily"
    if {"关键词", "在线商品数", "搜索人数"} <= hs:
        return "keyword_brand_daily"
    if {"SKUID", "商品信息", "排名"} <= hs:
        return "keyword_sku_rank_daily"
    return None


def _is_yoy_col(name) -> bool:
    """判断某一列是不是'同比'列。pandas 读表格遇到重复列名会自动改成
    '同比.1'/'同比.2'……这类后缀去重，所以不能只判断严格等于'同比'。"""
    return isinstance(name, str) and (name == "同比" or name.startswith("同比."))


def _funnel_metric_positions(header: list):
    """把每个指标列和紧跟其后的'同比'列配对，返回 [(db字段名, 指标列idx, 同比列idx或None), ...]。"""
    pairs = []
    for cn_name, field in _FUNNEL_METRIC_FIELDS.items():
        idx = header.index(cn_name)
        yoy_idx = idx + 1 if idx + 1 < len(header) and _is_yoy_col(header[idx + 1]) else None
        pairs.append((field, idx, yoy_idx))
    return pairs


_FUNNEL_OPTIONAL_FLAG_COLS = {
    "week_report": "周报周",
    "week_meeting": "周会周",
    "traffic_source": "聚合来源",
    "core_node": "核心节点",
    "is_last_7d": "是否近7天",
    "is_last_14d": "是否近14天",
    "is_reservation_period": "预约期",
    "is_launch_4h": "首销4小时",
    "is_launch_28h": "首销28小时",
    "is_launch_3d": "首销3天",
    "is_launch_7d": "首销7天",
    "is_launch_30d": "首销30天",
}
_FUNNEL_BOOL_FIELDS = {
    "is_last_7d", "is_last_14d", "is_reservation_period",
    "is_launch_4h", "is_launch_28h", "is_launch_3d", "is_launch_7d", "is_launch_30d",
}


def load_funnel_daily(header, rows_iter, sheet_name, source_file, series_code_override=None):
    """
    京东商智不同报表页面导出的"数据源"列不完全一样：完整的模板 sheet（如
    "数据源O10U"）会带 周报周/核心节点/首销Nx 等上下文列；单独重新导出某段
    时间的"流量来源"报表通常只有 日期/一级渠道/二级渠道 + 各项指标，没有这些
    上下文列。这里只要求日期+渠道+指标列，其余上下文列缺失就存 None/False，
    不因为缺列就放弃整个 sheet。
    """
    required_names = ["日期", "一级渠道", "二级渠道"]
    try:
        idx = {name: header.index(name) for name in required_names}
        metric_positions = _funnel_metric_positions(header)
    except ValueError as e:
        print(f"  [跳过] sheet '{sheet_name}' 缺少必要列: {e}")
        return None

    optional_idx = {field: header.index(cn) for field, cn in _FUNNEL_OPTIONAL_FLAG_COLS.items() if cn in header}

    if series_code_override:
        series_code = series_code_override
    elif sheet_name.startswith("数据源"):
        series_code = sheet_name[len("数据源"):]
    else:
        series_code = sheet_name

    records = []
    for row in rows_iter:
        d = to_date(row[idx["日期"]])
        if d is None:
            continue
        rec = {
            "date": d,
            "series_code": series_code,
            "channel_l1": to_text(row[idx["一级渠道"]]),
            "channel_l2": to_text(row[idx["二级渠道"]]),
            "source_file": source_file,
        }
        for field, cn in _FUNNEL_OPTIONAL_FLAG_COLS.items():
            if field not in optional_idx:
                rec[field] = None
            elif field in _FUNNEL_BOOL_FIELDS:
                rec[field] = to_bool_cn(row[optional_idx[field]])
            else:
                rec[field] = to_text(row[optional_idx[field]])
        for field, midx, yidx in metric_positions:
            raw = row[midx]
            rec[field] = to_int(raw) if field in _FUNNEL_INT_METRICS else to_float(raw)
            rec[f"{field}_yoy"] = to_float(row[yidx]) if yidx is not None else None
        records.append(rec)

    return pd.DataFrame.from_records(records) if records else None


def load_sku_daily(header, rows_iter, sheet_name, source_file):
    names = [
        "时间", "商品名称", "SKU", "品牌", "一级类目", "二级类目", "三级类目", "店铺名称",
        "RDC", "配送中心", "上下柜状态", "商品价格", "库存件数", "可用库存",
        "昨日出库商品件数", "近7日出库商品件数", "近14日出库商品件数", "近28日出库商品件数", "近30日出库商品件数",
    ]
    try:
        idx = {name: header.index(name) for name in names}
    except ValueError as e:
        print(f"  [跳过] sheet '{sheet_name}' 缺少必要列: {e}")
        return None

    records = []
    for row in rows_iter:
        snapshot_date = to_date(row[idx["时间"]])
        sku_id = to_id_str(row[idx["SKU"]])
        if snapshot_date is None or sku_id is None:
            continue
        records.append({
            "snapshot_date": snapshot_date,
            "sales_date": snapshot_date - timedelta(days=1),
            "sku_id": sku_id,
            "product_name": to_text(row[idx["商品名称"]]),
            "brand": to_text(row[idx["品牌"]]),
            "category_l1": to_text(row[idx["一级类目"]]),
            "category_l2": to_text(row[idx["二级类目"]]),
            "category_l3": to_text(row[idx["三级类目"]]),
            "store_name": to_text(row[idx["店铺名称"]]),
            "rdc": to_text(row[idx["RDC"]]),
            "distribution_center": to_text(row[idx["配送中心"]]),
            "shelf_status": to_text(row[idx["上下柜状态"]]),
            "price": to_float(row[idx["商品价格"]]),
            "stock_qty": to_int(row[idx["库存件数"]]),
            "available_stock": to_int(row[idx["可用库存"]]),
            "sales_qty": to_int(row[idx["昨日出库商品件数"]]),
            "sales_qty_7d": to_int(row[idx["近7日出库商品件数"]]),
            "sales_qty_14d": to_int(row[idx["近14日出库商品件数"]]),
            "sales_qty_28d": to_int(row[idx["近28日出库商品件数"]]),
            "sales_qty_30d": to_int(row[idx["近30日出库商品件数"]]),
            "source_file": source_file,
        })

    return pd.DataFrame.from_records(records) if records else None


def load_keyword_brand_daily(header, rows_iter, sheet_name, source_file):
    names = [
        "日期", "年", "月", "周", "SPU", "词条性质", "品牌", "子品牌", "是否近14天", "排名", "关键词",
        "搜索人数", "搜索次数", "点击人数", "点击次数", "点击率", "成交金额", "成交单量", "成交转化率", "在线商品数",
    ]
    try:
        idx = {name: header.index(name) for name in names}
    except ValueError as e:
        print(f"  [跳过] sheet '{sheet_name}' 缺少必要列: {e}")
        return None

    records = []
    for row in rows_iter:
        row_date = to_date(row[idx["日期"]])
        if row_date is None:
            continue
        records.append({
            "date": row_date,
            "year": to_text(row[idx["年"]]),
            "month": to_text(row[idx["月"]]),
            "week": to_text(row[idx["周"]]),
            "spu": to_text(row[idx["SPU"]]),
            "entry_type": to_text(row[idx["词条性质"]]),
            "brand": to_text(row[idx["品牌"]]),
            "sub_brand": to_text(row[idx["子品牌"]]),
            "is_last_14d": to_bool_cn(row[idx["是否近14天"]]),
            "rank": to_int(row[idx["排名"]]),
            "keyword": to_text(row[idx["关键词"]]),
            "search_users_raw": _raw(row[idx["搜索人数"]]), "search_users_est": parse_range_estimate(row[idx["搜索人数"]]),
            "search_count_raw": _raw(row[idx["搜索次数"]]), "search_count_est": parse_range_estimate(row[idx["搜索次数"]]),
            "click_users_raw": _raw(row[idx["点击人数"]]), "click_users_est": parse_range_estimate(row[idx["点击人数"]]),
            "click_count_raw": _raw(row[idx["点击次数"]]), "click_count_est": parse_range_estimate(row[idx["点击次数"]]),
            "click_rate_raw": _raw(row[idx["点击率"]]), "click_rate_est": parse_range_estimate(row[idx["点击率"]]),
            "sales_amount_raw": _raw(row[idx["成交金额"]]), "sales_amount_est": parse_range_estimate(row[idx["成交金额"]]),
            "sales_qty_raw": _raw(row[idx["成交单量"]]), "sales_qty_est": parse_range_estimate(row[idx["成交单量"]]),
            "conversion_rate_raw": _raw(row[idx["成交转化率"]]), "conversion_rate_est": parse_range_estimate(row[idx["成交转化率"]]),
            "online_sku_count": to_int(row[idx["在线商品数"]]),
            "source_file": source_file,
        })

    return pd.DataFrame.from_records(records) if records else None


def load_keyword_sku_rank_daily(header, rows_iter, sheet_name, source_file):
    names = [
        "时间", "SPU", "是近14天", "品牌", "月", "周", "是否近14天", "排名",
        "SKUID", "商品信息", "品牌ID", "品牌名称", "点击人数", "点击次数", "成交单量", "成交金额",
    ]
    try:
        idx = {name: header.index(name) for name in names}
    except ValueError as e:
        print(f"  [跳过] sheet '{sheet_name}' 缺少必要列: {e}")
        return None

    records = []
    for row in rows_iter:
        row_date = to_date(row[idx["时间"]])
        if row_date is None:
            continue
        records.append({
            "date": row_date,
            "spu": to_text(row[idx["SPU"]]),
            "is_last_14d_1": to_bool_cn(row[idx["是近14天"]]),
            "brand": to_text(row[idx["品牌"]]),
            "month": to_text(row[idx["月"]]),
            "week": to_text(row[idx["周"]]),
            "is_last_14d_2": to_bool_cn(row[idx["是否近14天"]]),
            "rank": to_int(row[idx["排名"]]),
            "sku_id": to_id_str(row[idx["SKUID"]]),
            "product_info": to_text(row[idx["商品信息"]]),
            "brand_id": to_id_str(row[idx["品牌ID"]]),
            "brand_name": to_text(row[idx["品牌名称"]]),
            "click_users_raw": _raw(row[idx["点击人数"]]), "click_users_est": parse_range_estimate(row[idx["点击人数"]]),
            "click_count_raw": _raw(row[idx["点击次数"]]), "click_count_est": parse_range_estimate(row[idx["点击次数"]]),
            "sales_qty_raw": _raw(row[idx["成交单量"]]), "sales_qty_est": parse_range_estimate(row[idx["成交单量"]]),
            "sales_amount_raw": _raw(row[idx["成交金额"]]), "sales_amount_est": parse_range_estimate(row[idx["成交金额"]]),
            "source_file": source_file,
        })

    return pd.DataFrame.from_records(records) if records else None


LOADERS = {
    "funnel_daily": load_funnel_daily,
    "sku_daily": load_sku_daily,
    "keyword_brand_daily": load_keyword_brand_daily,
    "keyword_sku_rank_daily": load_keyword_sku_rank_daily,
}


def write_table(con, table: str, df: pd.DataFrame, partition_cols):
    if isinstance(partition_cols, str):
        partition_cols = [partition_cols]
    where_clause = " AND ".join(f"{c} = ?" for c in partition_cols)

    for pval, group in df.groupby(partition_cols):
        params = list(pval) if isinstance(pval, tuple) else [pval]
        # 删除+插入包在一个事务里：插入失败时把删除也一起回滚，不然会把
        # 这个分区的旧数据删空、新数据又没插进去，表就被清空了。
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"DELETE FROM {table} WHERE {where_clause}", params)
            con.register("tmp_df", group)
            cols = ", ".join(group.columns)
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM tmp_df")
            con.unregister("tmp_df")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def import_workbook(file, source_name: str | None = None, series_code_override: str | None = None):
    """
    file: 本地文件路径（Path/str），或者任何 pandas 能读的文件对象（比如
    Streamlit st.file_uploader 返回的上传文件、BytesIO）——网页版"上传数据"
    功能就是靠这个支持上传文件直接导入，不用先落到 data/inbox/ 目录。
    source_name: 记录进 source_file 字段、日志打印用的文件名；传本地路径时
    可以不传，自动取文件名，上传文件场景必须传（比如 uploaded_file.name）。
    """
    if source_name is None:
        source_name = Path(file).name

    # 注意：这里用 pandas.read_excel（底层还是 openpyxl）而不是直接用
    # openpyxl 的 read_only 流式模式读取。实测发现部分京东商智导出的 xlsx
    # （尤其是单独重新导出的报表，不是完整模板文件）在 openpyxl 的
    # read_only 模式下会把表头读错（实测只读出第一列），pandas 这条路径
    # 没有这个问题，速度也足够（10万行级别的 sheet 在 20~30 秒内）。
    xl = pd.ExcelFile(file, engine="openpyxl")
    con = get_connection()
    summary = []
    try:
        for sheet_name in xl.sheet_names:
            header_only = xl.parse(sheet_name, nrows=0)
            header = list(header_only.columns)
            report_type = detect_report_type(header)
            if report_type is None:
                continue  # 汇总/透视表之类的辅助 sheet，跳过（先只读表头，省得整表解析）

            full_df = xl.parse(sheet_name)
            header = list(full_df.columns)  # 和上面理论上一致，重新取一次更保险
            rows_iter = full_df.itertuples(index=False, name=None)

            if report_type == "funnel_daily":
                df = load_funnel_daily(header, rows_iter, sheet_name, source_name, series_code_override)
            else:
                df = LOADERS[report_type](header, rows_iter, sheet_name, source_name)
            if df is None or df.empty:
                continue

            write_table(con, report_type, df, PARTITION_COL[report_type])
            summary.append((sheet_name, report_type, len(df)))
            print(f"  [完成] sheet '{sheet_name}' -> {report_type}: {len(df)} 行")
    finally:
        con.close()

    if not summary:
        print(f"  [提示] {source_name} 里没有识别出任何已知的数据源 sheet（可能都是汇总/透视表，已跳过）")
    return summary


def _move_to_processed(path: Path):
    from datetime import datetime
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    target = PROCESSED_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{path.name}"
    path.rename(target)


def process_inbox():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    files = [p for p in INBOX_DIR.iterdir() if p.is_file() and not p.name.startswith(".")]
    if not files:
        print(f"[提示] {INBOX_DIR} 里没有待导入的文件")
        return

    for path in files:
        print(f"[处理] {path.name}")
        try:
            import_workbook(path)
            _move_to_processed(path)
        except Exception as e:
            print(f"[失败] {path.name}: {e}")


def main():
    parser = argparse.ArgumentParser(description="导入京东商智相关 Excel 模板数据")
    parser.add_argument("file", nargs="?", help="指定单个文件；不传则处理 data/inbox/ 下所有文件")
    parser.add_argument(
        "--series-code",
        help=(
            "强制指定这份文件里 funnel_daily 数据的 series_code（如 O10U），"
            "用于单独重新导出、sheet 名不是'数据源XXX'格式的修正文件；"
            "只在指定单个文件时有效，处理 inbox 整批文件时不要用这个参数"
        ),
    )
    args = parser.parse_args()

    if args.file:
        print(f"[处理] {args.file}")
        import_workbook(Path(args.file), series_code_override=args.series_code)
    else:
        process_inbox()


if __name__ == "__main__":
    main()
