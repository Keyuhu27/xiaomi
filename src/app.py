"""
应用入口：密码门 + 多页面导航。本地跑，或者部署到 Railway 这类平台上都可以用。

本地启动方式：
    streamlit run src/app.py

页面：
    - 💬 聊天问答：用自然语言问销量数据库问题
    - 📦 销量看板 / 🚀 新品转化看板 / 🔍 关键词竞对 / 🏆 商品排名竞对：
      按表分类的固定看板，趋势图 + 排行榜 + 明细表
    - 📤 数据导入：上传京东商智相关的 Excel 文件

数据更新走「数据导入」页面上传，不需要命令行（部署到 Railway 后没有本地文件
系统可放 data/inbox/，只能这样传）。
"""
import os

import streamlit as st
from dotenv import load_dotenv

from app_pages import (
    chat_page,
    funnel_dashboard,
    import_page,
    keyword_brand_dashboard,
    keyword_rank_dashboard,
    sku_dashboard,
)

load_dotenv()

st.set_page_config(page_title="销量数据助手", page_icon="📊", layout="wide")


def _check_password() -> bool:
    """
    简单的共享密码门：设置了 APP_PASSWORD 环境变量才会启用。部署到 Railway
    之类的公网环境时务必设置这个变量，不然任何拿到 URL 的人都能进来看数据、
    消耗你的 Claude API 额度。本地开发不设置这个变量就不会要求输入密码。
    """
    app_password = os.environ.get("APP_PASSWORD")
    if not app_password:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("📊 销量数据助手")
    pwd = st.text_input("请输入访问密码", type="password")
    if pwd:
        if pwd == app_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("密码不对")
    return False


if not _check_password():
    st.stop()

pg = st.navigation([
    # 每个页面模块的入口函数都叫 render，Streamlit 默认按函数名推断 URL
    # 路径会互相冲突（报 "Multiple Pages specified with URL pathname"），
    # 所以这里手动指定各自的 url_path。
    st.Page(chat_page.render, title="聊天问答", icon="💬", url_path="chat", default=True),
    st.Page(sku_dashboard.render, title="销量看板", icon="📦", url_path="sku-dashboard"),
    st.Page(funnel_dashboard.render, title="新品转化看板", icon="🚀", url_path="funnel-dashboard"),
    st.Page(keyword_brand_dashboard.render, title="关键词竞对", icon="🔍", url_path="keyword-brand"),
    st.Page(keyword_rank_dashboard.render, title="商品排名竞对", icon="🏆", url_path="keyword-rank"),
    st.Page(import_page.render, title="数据导入", icon="📤", url_path="import"),
])
pg.run()
