# 销量数据分析平台（京东商智 + 本地 DuckDB + Claude）

每天把京东商智导出的销量报表导入本地数据库，然后用自然语言提问，比如：

- "今天 Redmi K80 的销量是多少？"
- "今天数据有没有异常？"
- "最近 7 天哪个型号卖得最好？"

只在本机使用，不需要服务器，不需要公网访问。

## 目录结构

```
data/
  inbox/          # 每天把京东商智导出的原始文件放这里
  sales.duckdb     # 数据库文件（首次运行自动创建，不进 git）
src/
  db.py            # DuckDB 连接与建表
  import_data.py    # 读取 inbox 里的文件，清洗后写入数据库
  anomaly.py        # 异常检测口径（滚动均值/标准差）
  tools.py          # 提供给 Claude 的工具（run_sql / check_anomalies）
  chat_app.py        # Streamlit 聊天 + 今日看板
```

## 首次安装

1. 安装 Python 3.11+。
2. 安装依赖：

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows 用 .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. 配置 API Key：

   ```bash
   cp .env.example .env
   ```

   打开 `.env`，把 `ANTHROPIC_API_KEY` 换成你自己的 key（在 https://console.anthropic.com 申请）。

4. **★ 对照真实导出文件调整列名映射（重要，只需做一次）**

   打开一份你自己从京东商智实际导出的 Excel/CSV 文件，看一下里面的列名（比如"商品编码""销售量"这些）。
   打开 `src/import_data.py`，找到 `COLUMN_ALIASES` 这个字典，把你文件里的真实列名加进对应字段的列表里（列表越靠前优先级越高）。

   例如京东商智导出的商品编码列实际叫"商品ID"而不是"商品编码"，就在 `COLUMN_ALIASES["sku_id"]` 列表里加上 `"商品ID"`。

   不确定列名对不对也没关系：运行导入脚本时如果缺少必需字段（商品编码、销量），会打印出文件里实际有哪些列名，照着改一次即可。

## 每天的使用流程

1. 登录京东商智，导出当天的商品销量报表（Excel 或 CSV）。
2. 把文件拖进 `data/inbox/` 文件夹。
3. 运行导入脚本：

   ```bash
   python src/import_data.py
   ```

   会自动处理 `data/inbox/` 下所有文件，导入完的文件会被移到 `data/inbox/processed/`（避免重复导入）。
   同一天的数据如果重复导入，会整体替换掉旧数据，不会产生重复行。

4. 打开聊天界面：

   ```bash
   streamlit run src/chat_app.py
   ```

   浏览器会自动打开一个本地网页，左侧是今日销量概览，中间可以直接用中文提问。

Windows 用户也可以直接双击 `run.bat`（首次会自动建虚拟环境、装依赖），Mac 用户双击 `run.command`。

## 关于异常检测

`check_anomalies` 工具的口径：把某个商品当天的销量，和它过去 7 天（可调）的均值/标准差比较，
偏离超过 2 个标准差（可调）就认为是异常波动。数据积累不足 7 天时，大部分商品还算不出标准差，
不会报异常，这是正常现象，不是 bug——数据越积越多，异常检测会越来越准。

## 后续可以做但暂时没做的事

- **自动抓取京东商智数据**：京东商智没有开放给普通商家账号的 API，且登录页通常有滑块/短信验证，
  纯 RPA 全自动很容易失效、维护成本高。如果之后还是想做，可以用 Playwright 写一个半自动脚本
  （自动登录、跳转、点击导出，验证码环节可能仍需要人工点一下），作为对"每天手动导出"这一步的优化，
  不影响后面导入数据库和问答的部分。
- **导入自动触发**：现在是手动运行 `python src/import_data.py`；如果嫌麻烦，可以加一个用
  `watchdog` 监听 `data/inbox/` 目录的小脚本，文件一放进去就自动导入。
- **异常检测预计算**：现在是每次提问时现算，如果以后数据量变大、想要更快，可以加一个每晚跑一次的
  定时任务，把统计结果预先存好。
