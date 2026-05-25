# 心动小镇 TapTap 论坛舆情分析

TapTap 论坛爬虫与 AI 舆情分析系统，针对游戏 **心动小镇** (App ID: 45213) 自动抓取帖子、DeepSeek AI 情感评分，并生成可视化趋势报告。

## 功能

- **帖子爬取** — 通过 TapTap 内部 API (游标分页) 获取帖子列表，再爬详情页补充完整内容
- **AI 情感评分** — 调用 DeepSeek API 对每条帖子打分 (1-100)、判断情绪 (正面/中性/负面)，附带评分理由
- **可视化报告** — 生成包含评分趋势、发帖量、情绪分布的 Chart.js 交互式网页
- **每日总结** — 自动生成每日话题总结（正面/负面话题分类 + 帖子引用）
- **交互式控制台** — 提供菜单驱动的全流程操作界面

## 项目结构

```
forum_xdtown/
├── main.py          # 主程序入口（交互式菜单）
├── scraper.py       # 爬虫模块（API + HTML）
├── analyzer.py      # DeepSeek AI 情感分析
├── database.py      # SQLite 数据持久化
├── visualizer.py    # 可视化 HTML + 每日总结生成
├── config.py        # 配置文件
├── requirements.txt # Python 依赖
├── .env.example     # 环境变量模板
├── docs/
│   └── index.html   # GitHub Pages 可视化报告
└── output/
    └── visualization.html  # 本地生成的可视化网页
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
```

### 3. 运行

```bash
python main.py
```

菜单选项：
- `[1]` 爬取帖子列表
- `[2]` 爬取帖子详情
- `[3]` AI 情感评分
- `[4]` 一键全流程（列表 → 详情 → 评分）
- `[5]` 生成可视化网页
- `[6]` 浏览数据库
- `[7]` 数据库统计

## 数据说明

- 数据存储在 `data/forum.db` (SQLite)
- `posts` 表：帖子内容、评分、情绪
- `daily_scores` 表：每日评分汇总（含原始 + 过滤双轨）
- `daily_summaries` 表：AI 生成的每日话题总结

评分过滤规则：剔除空内容帖和中性帖 (40-69 分)，保留有明确观点的帖子计算"信号分"。

## 可视化报告

在线报告: `https://<your-username>.github.io/<repo-name>/`

本地生成后自动打开浏览器，也可手动打开 `output/visualization.html`。

## 技术栈

- Python 3.x
- SQLite (数据存储)
- DeepSeek API (AI 评分 + 每日总结)
- Chart.js (前端图表)
- BeautifulSoup4 (HTML 解析)

## License

MIT
