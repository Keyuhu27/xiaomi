"""
京东商智导出表格里常见的几种"讨厌"格式的小工具解析函数：
  - 是/否 文本 -> 布尔值
  - 竞对数据常见的脱敏区间文本（如"10万~25万"、"0%~1%"、"10~50"）
    -> 取区间中点作为估算数值（保留原始文本，估算值只是辅助）
  - 数字/日期的安全转换（转不了就返回 None，不抛异常中断整个导入）
"""
import datetime as _dt
import re

import pandas as _pd

_PERCENT_RANGE = re.compile(r"^(-?[\d.]+)%\s*[~-]\s*(-?[\d.]+)%$")
_PERCENT_SINGLE = re.compile(r"^(-?[\d.]+)%$")
_NUM_RANGE = re.compile(r"^([\d.]+)(万|亿)?\s*[~-]\s*([\d.]+)(万|亿)?$")
_NUM_SINGLE = re.compile(r"^-?[\d.]+$")

_UNIT_MULTIPLIER = {"万": 1e4, "亿": 1e8, None: 1}


def _is_missing(value) -> bool:
    """
    None，或者 pandas 读表格时给的各种"空"：float('nan')、pd.NaT。
    用 pd.isna() 统一判断，比自己挨个判断类型稳——尤其 pd.NaT 这种坑：
    它其实继承自 datetime.datetime，isinstance 判断会当成正常日期，
    'NaT'.date() 还不报错、直接返回 NaT 本身，不用 pd.isna() 很容易漏判。
    """
    if value is None:
        return True
    try:
        return bool(_pd.isna(value))
    except (TypeError, ValueError):
        return False


def to_bool_cn(value) -> bool | None:
    """把'是'/'否'这类文本转成布尔值；不认识的值返回 None。"""
    if _is_missing(value):
        return None
    s = str(value).strip()
    if s == "是":
        return True
    if s == "否":
        return False
    return None


def parse_range_estimate(value) -> float | None:
    """
    把京东商智竞对数据里常见的脱敏区间文本转成一个估算数值（区间中点）。
    例如 "10万~25万" -> 175000.0，"0%~1%" -> 0.005，"10~50" -> 30.0。
    已经是数字的直接返回；无法识别的格式返回 None（不猜测，宁可留空）。
    """
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")  # 去掉千分位逗号，如 "1,000~2,000"
    if s in ("", "-", "--", "NA", "N/A"):
        return None

    m = _PERCENT_RANGE.match(s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2 / 100

    m = _PERCENT_SINGLE.match(s)
    if m:
        return float(m.group(1)) / 100

    m = _NUM_RANGE.match(s)
    if m:
        n1, u1, n2, u2 = m.groups()
        # "5~10万" 这种写法里左边通常省略单位，跟右边一致
        if u1 is None and u2 is not None:
            u1 = u2
        v1 = float(n1) * _UNIT_MULTIPLIER[u1]
        v2 = float(n2) * _UNIT_MULTIPLIER[u2]
        return (v1 + v2) / 2

    if _NUM_SINGLE.match(s):
        return float(s)

    return None


def to_float(value) -> float | None:
    """
    安全转 float：空值/非法字符串返回 None，不抛异常。
    兼容百分比文本，如 "-41.81%" -> -0.4181（和同一字段里的原始小数口径一致）。
    """
    if _is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if s in ("", "-", "--", "NA", "N/A"):
        return None
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(value) -> int | None:
    f = to_float(value)
    return int(f) if f is not None else None


def to_text(value) -> str | None:
    """普通文本字段的安全转换：pandas 读出来的空单元格(NaN)统一转成 None，
    不然会把字面意思的 'nan' 字符串存进数据库。"""
    if _is_missing(value):
        return None
    return value if isinstance(value, str) else str(value)


def to_id_str(value) -> str | None:
    """
    把 SKU 编码/品牌 ID 这类"应该是字符串"的 ID 字段安全转成字符串。
    pandas 读表格时，一列如果混了空值，整列会被转成 float64，
    好端端的 100290805125 会变成 100290805125.0——这里把这种情况转回不带
    小数点的整数字符串，避免同一个 ID 因为来源不同（openpyxl 原样是 int，
    pandas 读出来是 float）而在数据库里变成两种不同的字符串。
    """
    if _is_missing(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def to_date(value) -> _dt.date | None:
    """兼容 openpyxl/pandas 给的 datetime 对象，或者文本型日期（如 '2026-08-19'）。"""
    if _is_missing(value):
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(s[:10])
    except ValueError:
        return None
