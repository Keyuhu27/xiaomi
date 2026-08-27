"""
数据导入页面：上传京东商智相关的 Excel 文件，直接解析导入数据库。
"""
import streamlit as st

from import_data import import_workbook


def render():
    st.title("📤 数据导入")
    st.caption(
        "把京东商智相关的 Excel 文件拖到这里，会自动逐个 sheet 识别是哪类报表并导入对应的表"
        "（认不出的汇总/透视表 sheet 会跳过）。"
    )

    uploaded_files = st.file_uploader(
        "选择文件（可一次选多个）",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
    )
    with st.expander("高级选项"):
        series_code_override = st.text_input(
            "强制指定系列代号（如 O10U）",
            value="",
            help=(
                "只有单独重新导出某个系列部分时间的修正文件、sheet 名不是"
                "“数据源XXX”格式时才需要填；正常的完整模板文件留空即可"
            ),
        ).strip() or None

    if uploaded_files and st.button("开始导入", type="primary"):
        for f in uploaded_files:
            with st.spinner(f"正在导入 {f.name} ..."):
                try:
                    summary = import_workbook(f, source_name=f.name, series_code_override=series_code_override)
                    if summary:
                        for sheet_name, report_type, n in summary:
                            st.success(f"{f.name} / {sheet_name} → {report_type}：{n} 行")
                    else:
                        st.warning(f"{f.name} 里没有识别出已知的报表类型（汇总/透视表 sheet 会被跳过）")
                except Exception as e:
                    st.error(f"{f.name} 导入失败：{e}")
        st.info("导入完成，可以去左侧对应的看板页面查看最新数据。")
