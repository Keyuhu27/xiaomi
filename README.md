# 销量数据分析平台（京东商智 + 本地 DuckDB + Claude）

每天把京东商智相关数据更新进 Excel 模板后，导入本地数据库，然后用自然语言提问，比如：

- "今天 Redmi Note 17 Pro 的销量是多少？"
- "今天数据有没有异常？"
- "最近 7 天 Turbo 系列哪个渠道转化最好？"

可以在自己电脑本地跑，也可以部署到 Railway 这类平台上（公司电脑装不了本地环境
时用这个），部署方式见下面"部署到 Railway"一节。

网页是多页面的，左侧导航栏可以切换：

- 💬 **聊天问答**：自然语言问数据库
- 📦 **销量看板**：sku_daily 的 KPI + 趋势图 + 畅销排行
- 🚀 **新品转化看板**：funnel_daily（Turbo 系列等）的流量/转化趋势 + 渠道排名
- 🔍 **关键词竞对** / 🏆 **商品排名竞对**：两张竞对监控表的筛选表格
- 📤 **数据导入**：上传京东商智相关的 Excel 文件

## 数据库里有什么（重要，务必先看）

这个数据库**不是一张"销量表"**，而是对应京东商智 4 类完全不同的报表，分别建了 4 张表
（已经用真实导出文件验证过表结构、字段含义、去重逻辑）：

| 表 | 内容 | 粒度 | 说明 |
|---|---|---|---|
| **sku_daily** | 全量商品每日库存/出库快照 | 日期 × SKU × 区域(RDC) | **回答"今天/某天某型号卖了多少"的核心表**。`sales_qty` = 昨日出库件数 |
| **funnel_daily** | 重点新品（Turbo 系列等）全链路流量转化 | 日期 × 产品系列 × 渠道 | 有 PV/UV/加购/下单/成交全链路数据，`sales_qty`=成交子单量，`sales_amount`=成交金额 |
| **keyword_brand_weekly** | 行业关键词/品牌词条竞对监控 | 周 × 品牌 × 关键词 | 覆盖全行业，数值多为脱敏区间（如"10万~25万"），`_est` 字段是区间中点估算值，不是精确数 |
| **keyword_sku_rank_weekly** | 关键词/型号下商品排名竞对监控 | 周 × 型号 × SKU | 含自家和竞品，数值同样多为脱敏区间估算 |

字段的详细中文含义见 `src/db.py` 里每张表的建表语句注释，以及 `src/tools.py` 里给 Claude 的
工具描述。

### ⚠️ sku_daily 里两个容易踩的坑

1. **rdc='全国' 是京东商智已经算好的全国汇总行**，同一个 SKU 同一天还会有若干
   `rdc=具体城市名`（广州/上海/西安…）的区域拆分行，**两者相加会重复计数**。
   查"某型号今天总共卖了多少"，只用 `WHERE rdc = '全国'` 即可，不要对全表 SUM。
   聊天界面和 `check_anomalies` 工具已经处理好了这一点，自己写 SQL 时要注意。

2. **`sales_qty` 是"昨日"出库件数**：snapshot_date 是导出快照当天，`sales_date` =
   `snapshot_date - 1天`，即这一行数据实际反映的是 `sales_date` 那天的销量。查询时用
   `sales_date` 定位"哪天卖了多少"，`snapshot_date` 只是记录这份数据是哪天导出的。

### 已修复：P10U 和 O10U 曾在 2026-07-27~08-18 期间数据重复

最初导入的 Turbo 系列文件里，`series_code='O10U'` 在 2026-07-27~2026-08-18
这段时间和 `P10U` 的数据完全一样（源 Excel 模板里这段时间的"数据源O10U" sheet
被误粘贴/误引用成了和"数据源P10U"一样的内容）。已经用重新导出的"流量来源_二级
渠道_分天"报表（该报表按型号单独导出，sheet 名不带"数据源XXX"）替换了这段时间
O10U 的数据，现在 P10U/O10U 在这段时间的数值不再相同。

如果以后遇到类似情况——某个系列一段时间的数据错了，只有那段时间的修正文件（不是
"数据源XXX"这种完整历史 sheet 名）——用这样的命令导入，用 `--series-code` 指定
这份文件属于哪个系列：

```bash
python src/import_data.py 修正文件.xlsx --series-code O10U
```

`funnel_daily` 是按 `(series_code, date)` 整体替换的（见下面"每天的使用流程"里的
去重方式表），所以这样导入只会替换文件里实际包含的那些日期，不会影响该系列其它
日期的历史数据。

## 目录结构

```
data/
  inbox/          # 每天把更新好的 Excel 文件放这里
  sales.duckdb     # 数据库文件（首次运行自动创建，不进 git）
src/
  app.py           # 应用入口：密码门 + 页面导航（streamlit run src/app.py）
  app_pages/        # 每个导航页面一个文件，函数名统一叫 render()
    chat_page.py         # 💬 聊天问答
    sku_dashboard.py      # 📦 销量看板
    funnel_dashboard.py    # 🚀 新品转化看板
    keyword_brand_dashboard.py  # 🔍 关键词竞对
    keyword_rank_dashboard.py   # 🏆 商品排名竞对
    import_page.py        # 📤 数据导入
  db.py            # DuckDB 连接与建表（4 张表）
  parsing.py        # 小工具：是/否转布尔、脱敏区间转估算数值、安全数字/日期转换
  import_data.py     # 打开 Excel，逐个 sheet 识别报表类型，导入对应的表
  anomaly.py         # 异常检测口径（基于 sku_daily 的滚动均值/标准差）
  tools.py           # 提供给 Claude 的工具（run_sql / check_anomalies）
Procfile              # Railway/类 Heroku 平台的启动命令
railway.json          # Railway 部署配置（构建方式、启动命令）
.python-version       # 指定 Python 3.11，Railway 构建时会读取
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

## 每天的使用流程

1. 跟你原来的习惯一样，把当天从京东商智下载的新数据更新进 Excel 模板（对应模板里的
   "数据源xxx" sheet）。
2. 导入数据，两种方式任选一种（部署到 Railway 后只能用方式 A，因为没有本地文件系统）：

   - **方式 A：网页里直接上传**（推荐，本地/部署都能用）——打开网页，切到左侧导航栏的
     "📤 数据导入"页面，把 Excel 文件拖进去，点"开始导入"。
   - **方式 B：命令行**（只适合本地）——把文件拖进 `data/inbox/` 文件夹，运行：

     ```bash
     python src/import_data.py
     ```

     导入完的文件会被移到 `data/inbox/processed/`。

   不管哪种方式，脚本都会打开文件、逐个 sheet 自动识别是上面 4 类报表的哪一种（认不出的
   汇总/透视表 sheet 会跳过），分别导入对应的表。重复导入同一天/同一系列/同一份文件的
   数据会被整体替换，不会产生重复行——具体按哪个字段去重见下表：

   | 表 | 去重方式 |
   |---|---|
   | sku_daily | 按 `sales_date`（同一天的快照整体替换） |
   | funnel_daily | 按 `(series_code, date)`（同一产品系列同一天的数据整体替换，不影响其它日期） |
   | keyword_brand_weekly / keyword_sku_rank_weekly | 按来源文件名整体替换 |

   funnel_daily 的 `series_code` 默认从 sheet 名推断（"数据源O10U" -> `O10U`）；如果是
   单独重新导出的修正文件、sheet 名不是这个格式，网页版在"📤 数据导入"页面的"高级选项"
   里填，命令行版用 `--series-code` 参数，见上面"已修复"那节的例子。

3. 打开网页（本地）：

   ```bash
   streamlit run src/app.py
   ```

   浏览器会自动打开，左侧导航栏可以切换聊天问答/各个看板/数据导入。部署到 Railway 后
   就是打开 Railway 给的那个网址，导航栏是一样的。

Windows 用户本地跑也可以直接双击 `run.bat`（首次会自动建虚拟环境、装依赖），Mac 用户双击 `run.command`。

## 部署到 Railway

公司电脑装不了本地 Python 环境、或者想随时随地（不只是自己电脑）打开聊天界面时用这个。
数据库还是同一个 DuckDB，只是换成跑在 Railway 上；每天的数据靠上面"方式 A：网页里直接
上传"更新，不需要 SSH 到服务器。

1. **确认代码已经推到 GitHub**（这个仓库就是，用哪个分支部署都行，比如当前分支或者合并到
   `main`）。
2. 登录 [railway.app](https://railway.app)，**New Project → Deploy from GitHub repo**，
   选这个仓库。Railway 会自动识别出是 Python 项目（靠 `requirements.txt`），并且这个仓库
   根目录已经放了 `railway.json`（指定了启动命令）和 `.python-version`（指定 Python
   3.11），不需要手动配置构建/启动命令。
3. 部署出来的服务里，进 **Variables**（环境变量）标签页，添加：
   - `ANTHROPIC_API_KEY`：你的 Claude API key。
   - `APP_PASSWORD`：给这个网页设一个访问密码（**强烈建议设置**——不设的话，任何拿到
     Railway 给的公网 URL 的人都能进来问你的数据、消耗你的 API 额度）。
   - `DATA_DIR`：设成 `/data`（配合下一步的持久化 volume，不然每次重新部署数据库都会被
     清空）。
4. 给这个服务加一个 **Volume**（持久化存储），挂载路径填 `/data`（要和上面 `DATA_DIR`
   一致）。Railway 的 Volume 功能在服务详情页的 "Settings" → "Volumes" 里。
5. 等部署完成，打开 Railway 给的域名（在服务详情页的 "Settings" → "Networking" 里，如果
   没有默认域名要手动点一下 "Generate Domain"）。第一次打开先输入你设的 `APP_PASSWORD`，
   然后照日常流程在"数据导入"里传第一份数据。

以后每天更新数据，就是打开这个 Railway 网址、上传当天更新好的 Excel、然后照常提问。

## 关于异常检测

`check_anomalies` 工具基于 `sku_daily` 表（`rdc='全国'` 的行）：把某个 SKU 当天的销量，
和它过去 7 天（可调）的均值/标准差比较，偏离超过 2 个标准差（可调）就认为是异常波动。
数据积累不足 7 天时，大部分 SKU 还算不出标准差，不会报异常，这是正常现象，不是 bug——
数据越积越多，异常检测会越来越准。

## 如果京东商智导出的字段名变了怎么办

`src/import_data.py` 里每个 `load_xxx` 函数开头都有一个 `names` 列表，写着这类报表要用到
的真实中文列名。如果京东商智改了导出格式、或者你新增了别的报表类型，照着现有的写法加一个
新的 `detect_report_type` 分支和 `load_xxx` 函数即可，不需要改其它地方。

## 后续可以做但暂时没做的事

- **自动抓取京东商智数据**：京东商智没有开放给普通商家账号的 API，且登录页通常有滑块/短信验证，
  纯 RPA 全自动很容易失效、维护成本高。如果之后还是想做，可以用 Playwright 写一个半自动脚本
  （自动登录、跳转、点击导出，验证码环节可能仍需要人工点一下），作为对"每天手动导出"这一步的优化，
  不影响后面导入数据库和问答的部分。
- **导入自动触发**：现在是手动运行 `python src/import_data.py`；如果嫌麻烦，可以加一个用
  `watchdog` 监听 `data/inbox/` 目录的小脚本，文件一放进去就自动导入。
- **异常检测预计算**：现在是每次提问时现算，如果以后数据量变大、想要更快，可以加一个每晚跑一次的
  定时任务，把统计结果预先存好。
- **keyword_brand_weekly / keyword_sku_rank_weekly 的估算值**：目前用区间中点做估算
  （`_est` 字段），如果后续觉得不够准，可以换成更细的分布假设，或者干脆只用 `_raw` 原始区间
  做排序/分类，不做数值估算。
