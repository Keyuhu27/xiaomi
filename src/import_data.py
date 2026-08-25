"""
把京东商智导出的销量报表（xlsx/csv）清洗后写入本地 DuckDB。

用法：
    python src/import_data.py                       # 处理 data/inbox/ 目录下所有文件
    python src/import_data.py path/to/file.xlsx      # 只处理指定文件
    python src/import_data.py path/to/file.xlsx --date 2026-08-25   # 文件里没有日期列时，手动指定报表日期

★★★ 首次使用前必读 ★★★
京东商智不同报表模块导出的列名可能不一样。请打开一份你自己实际导出的文件，
对照下面的 COLUMN_ALIASES，把真实的列名加进对应字段的候选列表里（放在越靠前
优先级越高）。脚本运行时如果找不到必需字段，会打印出文件里实际的列名，方便
你对照修改。
"""
import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from db import get_connection

INBOX_DIR = Path(__file__).resolve().parent.parent / "data" / "inbox"
PROCESSED_DIR = INBOX_DIR / "processed"

# 目标字段 -> 可能出现在京东商智导出表格里的候选列名
COLUMN_ALIASES = {
    "sku_id": ["商品编码", "商品ID", "商品编号", "SKU编码", "sku_id"],
    "product_name": ["商品名称", "商品标题", "product_name"],
    "model": ["型号", "商品型号", "规格", "model"],
    "category": ["商品分类", "类目", "category"],
    "sales_qty": ["销售量", "支付件数", "销量", "sales_qty"],
    "sales_amount": ["销售额", "支付金额", "成交金额", "sales_amount"],
    "visitors": ["访客数", "浏览量", "visitors"],
    "conversion_rate": ["转化率", "支付转化率", "conversion_rate"],
}
DATE_ALIASES = ["日期", "统计日期", "date"]

REQUIRED_FIELDS = ["sku_id", "sales_qty"]


def _find_column(columns, aliases):
    for alias in aliases:
        for col in columns:
            if str(col).strip() == alias:
                return col
    return None


def _resolve_columns(df: pd.DataFrame) -> dict:
    resolved = {}
    for field, aliases in COLUMN_ALIASES.items():
        col = _find_column(df.columns, aliases)
        if col is not None:
            resolved[field] = col

    missing_required = [f for f in REQUIRED_FIELDS if f not in resolved]
    if missing_required:
        print(f"[警告] 没找到必需字段: {missing_required}")
        print(f"       文件实际列名: {list(df.columns)}")
        print("       请打开 src/import_data.py，把真实列名加进 COLUMN_ALIASES 对应列表。")
    return resolved


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suffix == ".csv":
        # 京东商智导出的 csv 常见是 gbk 编码
        last_err = None
        for enc in ("utf-8-sig", "gbk", "utf-8"):
            try:
                return pd.read_csv(path, encoding=enc)
            except UnicodeDecodeError as e:
                last_err = e
        raise ValueError(f"无法识别 {path.name} 的编码") from last_err
    raise ValueError(f"不支持的文件类型: {suffix}")


def parse_file(path: Path, report_date: date | None) -> pd.DataFrame:
    raw = _read_table(path)
    resolved = _resolve_columns(raw)
    if "sku_id" not in resolved:
        raise ValueError(f"{path.name} 缺少商品编码列，无法导入，请检查 COLUMN_ALIASES")

    out = pd.DataFrame()
    for field, col in resolved.items():
        out[field] = raw[col]

    for field in ("sales_qty", "visitors"):
        if field in out:
            out[field] = pd.to_numeric(out[field], errors="coerce").fillna(0).astype("int64")
    for field in ("sales_amount", "conversion_rate"):
        if field in out:
            out[field] = pd.to_numeric(out[field], errors="coerce")

    date_col = _find_column(raw.columns, DATE_ALIASES)
    if date_col is not None:
        out["date"] = pd.to_datetime(raw[date_col]).dt.date
    else:
        out["date"] = report_date or date.today()

    out["source_file"] = path.name
    out = out.dropna(subset=["sku_id"])
    out["sku_id"] = out["sku_id"].astype(str).str.strip()
    return out


def import_file(path: Path, report_date: date | None = None):
    df = parse_file(path, report_date)
    if df.empty:
        print(f"[跳过] {path.name} 没有可导入的数据行")
        return

    con = get_connection()
    total_rows = 0
    for d, group in df.groupby("date"):
        existing = con.execute("SELECT COUNT(*) FROM sales WHERE date = ?", [d]).fetchone()[0]
        if existing:
            print(f"[提示] {d} 已有 {existing} 条记录，将被本次导入整体替换")
        con.execute("DELETE FROM sales WHERE date = ?", [d])

        con.register("df_import", group)
        cols = ", ".join(group.columns)
        con.execute(f"INSERT INTO sales ({cols}) SELECT {cols} FROM df_import")
        con.unregister("df_import")
        total_rows += len(group)

    con.close()
    print(f"[完成] {path.name} -> {total_rows} 条记录写入 {df['date'].nunique()} 个日期")


def _move_to_processed(path: Path):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    target = PROCESSED_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{path.name}"
    path.rename(target)


def process_inbox():
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        p for p in INBOX_DIR.iterdir()
        if p.is_file() and not p.name.startswith(".")
    ]
    if not files:
        print(f"[提示] {INBOX_DIR} 里没有待导入的文件")
        return

    for path in files:
        try:
            import_file(path)
            _move_to_processed(path)
        except Exception as e:
            print(f"[失败] {path.name}: {e}")


def main():
    parser = argparse.ArgumentParser(description="导入京东商智导出的销量报表")
    parser.add_argument("file", nargs="?", help="指定单个文件；不传则处理 data/inbox/ 下所有文件")
    parser.add_argument("--date", help="报表日期 YYYY-MM-DD；不传则用文件里的日期列，否则用今天")
    args = parser.parse_args()

    report_date = date.fromisoformat(args.date) if args.date else None

    if args.file:
        import_file(Path(args.file), report_date)
    else:
        process_inbox()


if __name__ == "__main__":
    main()
