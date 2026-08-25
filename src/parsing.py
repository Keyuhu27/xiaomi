"""
京东商智导出表格里常见的几种"讨厌"格式的小工具解析函数：
  - 是/否 文本 -> 布尔值
  - 竞对数据常见的脱敏区间文本（如"10万~25万"、"0%~1%"、"10~50"）
    -> 取区间中点作为估算数值（保留原始文本，估算值只是辅助）
  - 数字/日期的安全转换（转不了就返回 None，不抛异常中断整个导入）
"""
import datetime as _dt
import re

_PERCENT_RANGE = re.compile(r"^(-?[\d.]+)%\s*[~-]\s*(-?[\d.]+)%$")
_PERCENT_SINGLE = re.compile(r"^(-?[\d.]+)%$")
_NUM_RANGE = re.compile(r"^([\d.]+)(万|亿)?\s*[~-]\s*([\d.]+)(万|亿)?$")
_NUM_SINGLE = re.compile(r"^-?[\d.]+$")

_UNIT_MULTIPLIER = {"万": 1e4, "亿": 1e8, None: 1}


def to_bool_cn(value) -> bool | None:
    """把'是'/'否'这类文本转成布尔值；不认识的值返回 None。"""
    if value is None:
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
    if value is None:
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
    """安全转 float：空值/非法字符串返回 None，不抛异常。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if s in ("", "-", "--", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(value) -> int | None:
    f = to_float(value)
    return int(f) if f is not None else None


def to_date(value) -> _dt.date | None:
    """兼容 openpyxl 给的 datetime 对象，或者文本型日期（如 '2026-08-19'）。"""
    if value is None:
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
