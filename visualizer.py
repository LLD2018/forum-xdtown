"""
可视化模块 - 生成每日评分汇总和可视化网页
游戏: 心动小镇
"""
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict
from config import OUTPUT_DIR, VISUALIZATION_PATH, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
import database as db


def _parse_post_date(post):
    """解析帖子日期"""
    post_time = post.get("post_time", "")
    if not post_time:
        return None
    for fmt in ["%Y/%m/%d", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(post_time[:10], fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _is_empty_content(post):
    """判断帖子内容是否为空"""
    content = post.get("content")
    return content is None or (isinstance(content, str) and content.strip() == "")


def _is_neutral(post):
    """判断帖子是否为中性（无明确观点）"""
    score = post.get("score")
    return score is not None and 40 <= score <= 69


def _daily_stats(scores, post_count):
    """计算每日统计（平均分 + 情绪分布）"""
    avg = round(sum(scores) / post_count, 2) if post_count else 0
    pos = sum(1 for s in scores if s >= 70)
    neg = sum(1 for s in scores if s < 40)
    neu = post_count - pos - neg
    return avg, pos, neg, neu


def aggregate_daily_scores():
    """
    以天为单位汇总帖子评分（原始 + 过滤双轨）
    - 原始: 所有已评分帖子
    - 过滤: 剔除空内容和中性内容，仅保留有明确观点的帖子
    """
    posts = db.get_all_posts(order_by="post_time ASC")
    if not posts:
        print("  数据库中没有帖子数据")
        return []

    daily_raw = defaultdict(list)
    daily_filtered = defaultdict(list)

    for post in posts:
        date_str = _parse_post_date(post)
        if not date_str:
            continue

        score = post.get("score")
        if score is None:
            continue

        daily_raw[date_str].append(score)

        if not _is_empty_content(post) and not _is_neutral(post):
            daily_filtered[date_str].append(score)

    results = []
    for date_str in sorted(daily_raw.keys()):
        raw_scores = daily_raw[date_str]
        raw_count = len(raw_scores)
        raw_avg, raw_pos, raw_neg, raw_neu = _daily_stats(raw_scores, raw_count)

        filt_scores = daily_filtered.get(date_str, [])
        filt_count = len(filt_scores)
        filt_avg, filt_pos, filt_neg, _ = _daily_stats(filt_scores, filt_count)

        results.append({
            "date": date_str,
            "avg_score": raw_avg,
            "post_count": raw_count,
            "positive_count": raw_pos,
            "negative_count": raw_neg,
            "neutral_count": raw_neu,
            "filtered_avg_score": filt_avg if filt_count else None,
            "filtered_post_count": filt_count,
            "filtered_positive_count": filt_pos,
            "filtered_negative_count": filt_neg,
        })

        db.upsert_daily_score(
            date_str, raw_avg, raw_count, raw_pos, raw_neg, raw_neu,
            filtered_avg_score=(filt_avg if filt_count else None),
            filtered_post_count=filt_count,
            filtered_positive_count=filt_pos,
            filtered_negative_count=filt_neg,
        )

    return results


def get_daily_scores():
    """获取每日评分数据（优先从缓存表读取）"""
    cached = db.get_all_daily_scores()
    if cached:
        return cached
    return aggregate_daily_scores()


# ---- 每日发帖内容总结（DeepSeek 批量生成 + DB 缓存） ----

SUMMARY_SYSTEM_PROMPT = """你是游戏社区深度分析师，为【心动小镇】TapTap论坛每日帖子撰写详细的内容总结。

输出严格JSON：
{"summaries": [{"date": "YYYY-MM-DD", "overview": "当日整体氛围概述（30-50字）", "positive_topics": [{"topic": "话题标题", "detail": "详细说明"}], "negative_topics": [{"topic": "话题标题", "detail": "详细说明"}]}]}

每项要求：
- overview: 概括当日整体氛围和主要特征（30-50字），点明最突出的情绪倾向
- topic: 10-15字的话题标题
- detail: 针对该话题的详细说明（50-100字），必须做到：
  ① 描述该话题在当日帖子中的具体表现和讨论热度
  ② 适当引用帖子中的原文/关键表述（用「」括起来）
  ③ 说明玩家对这件事的态度和情绪
- positive_topics: 2-4个，按讨论热度排序
- negative_topics: 2-4个，按讨论热度排序
- 如果某类帖子极少或无，返回空数组[]

关注维度：
- 正面：家园/装修设计好评、社交/好友互动体验、游戏氛围/画风/音乐、活动/更新内容满意、服装/外观/搭配分享、钓鱼/采集/种植玩法、小镇建设/共建、好友互助/送礼
- 负面：BUG/卡顿/闪退/优化问题、活动/更新内容不满、氪金/付费/抽卡吐槽、内容不足/长草期/无聊、社交体验差/网络问题、操作/UI不便、账号/数据问题"""


def _build_detail_prompt(dates_to_summarize):
    """构建详细总结 prompt，包含帖子原文内容"""
    daily_data = {}
    for date_str in dates_to_summarize:
        opinion = db.get_daily_opinion_posts(date_str)
        pos_posts = opinion.get("positive", [])
        neg_posts = opinion.get("negative", [])
        if pos_posts or neg_posts:
            daily_data[date_str] = {"positive": pos_posts, "negative": neg_posts}

    if not daily_data:
        return None, {}

    lines = []
    for date_str, data in daily_data.items():
        lines.append(f"=== {date_str} ===")
        pos = data["positive"]
        neg = data["negative"]
        lines.append(f"正面帖 {len(pos)} 条，负面帖 {len(neg)} 条")

        if pos:
            lines.append("-- 正面帖 --")
            for p in pos[:15]:
                title = (p.get("title") or "")[:80]
                content = (p.get("content") or "")[:500]
                reason = (p.get("reason") or "")
                lines.append(f"  [标题]{title}[/标题] [内容]{content}[/内容] [评分:{p.get('score','?')}分 {reason}]")

        if neg:
            lines.append("-- 负面帖 --")
            for p in neg[:15]:
                title = (p.get("title") or "")[:80]
                content = (p.get("content") or "")[:500]
                reason = (p.get("reason") or "")
                lines.append(f"  [标题]{title}[/标题] [内容]{content}[/内容] [评分:{p.get('score','?')}分 {reason}]")

        lines.append("")

    return "\n".join(lines), daily_data


def _call_deepseek_summary(user_prompt):
    """调用 DeepSeek 生成总结"""
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}},
    )
    text = response.choices[0].message.content.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text).get("summaries", [])


def generate_daily_summaries(dates):
    """
    获取每日发帖总结（DB缓存优先，增量生成缺失日期，跳过最后一天）
    返回: [{"date": "...", "overview": "...", "positive_topics": [...], "negative_topics": [...]}, ...]
    """
    if not dates:
        return []

    # 排除最后一天（数据可能爬取不全）
    dates_except_last = [d for d in dates if d != dates[-1]]
    missing = db.get_dates_without_summary(dates_except_last)

    new_summaries = []
    if missing:
        print(f"  增量生成 {len(missing)} 天总结: {missing[0]} ~ {missing[-1]}")
        user_prompt, _ = _build_detail_prompt(missing)
        if user_prompt:
            try:
                summaries = _call_deepseek_summary(user_prompt)
                for s in summaries:
                    pos_json = json.dumps(s.get("positive_topics", []), ensure_ascii=False)
                    neg_json = json.dumps(s.get("negative_topics", []), ensure_ascii=False)
                    overview = s.get("overview", "")
                    db.upsert_daily_summary(
                        s["date"], overview, pos_json, neg_json
                    )
                new_summaries = summaries
                print(f"  已生成并保存 {len(new_summaries)} 天总结")
            except Exception as e:
                print(f"  总结生成失败，回退到缓存: {e}")

    # 从DB读取所有缓存
    cached = db.get_all_daily_summaries()
    # 合并去重
    seen = set()
    merged = []
    for s in new_summaries:
        if s["date"] not in seen:
            merged.append(s)
            seen.add(s["date"])
    for s in cached:
        if s["date"] not in seen:
            # DB 中 positive/negative 是 JSON 字符串，解析为列表
            pos = s.get("positive", "[]")
            neg = s.get("negative", "[]")
            if isinstance(pos, str):
                try:
                    pos = json.loads(pos)
                except (json.JSONDecodeError, TypeError):
                    pos = [pos] if pos else []
            if isinstance(neg, str):
                try:
                    neg = json.loads(neg)
                except (json.JSONDecodeError, TypeError):
                    neg = [neg] if neg else []
            merged.append({
                "date": s["date"],
                "overview": s.get("post_count", ""),
                "positive_topics": pos if isinstance(pos, list) else [],
                "negative_topics": neg if isinstance(neg, list) else [],
            })
            seen.add(s["date"])

    return sorted(merged, key=lambda x: x["date"], reverse=True)


def _render_daily_cards(summaries, filtered_counts, dates, daily_data):
    """生成每日总结折叠卡片 HTML（详细版，含帖子引用）"""
    if not summaries:
        return '<div class="no-summary">暂无每日总结数据</div>'

    count_map = dict(zip(dates, filtered_counts))
    score_map = {d["date"]: d.get("filtered_avg_score") for d in daily_data}

    def _render_topic_group(topics, label, label_class, topic_class):
        if not topics:
            return f'<div class="{label_class}">{label}</div><div class="summary-text">当日无明显话题</div>'
        parts = []
        for t in topics:
            if isinstance(t, str):
                parts.append(f'<div class="{topic_class}"><span class="topic-dot"></span>{t}</div>')
            elif isinstance(t, dict):
                topic_name = t.get("topic", "")
                detail = t.get("detail", "")
                parts.append(
                    f'<div class="{topic_class}">'
                    f'<span class="topic-dot"></span>'
                    f'<span class="topic-name">{topic_name}</span>'
                    f'<div class="topic-detail">{detail}</div>'
                    f'</div>'
                )
        return f'<div class="{label_class}">{label}</div>' + "\n".join(parts)

    parts = []
    for s in summaries:
        date_str = s.get("date", "")
        fc = count_map.get(date_str, 0)
        fs = score_map.get(date_str)
        score_str = f"信号分 {fs}" if fs else ""
        overview = s.get("overview", "")
        pos_topics = s.get("positive_topics", [])
        neg_topics = s.get("negative_topics", [])

        parts.append(f"""    <div class="daily-card">
        <div class="card-header" onclick="this.parentElement.classList.toggle('open')">
            <span class="card-date">{date_str}</span>
            <span class="card-stats">
                <span>观点帖 {fc} 条</span>
                <span class="card-score-tag">{score_str}</span>
                <span class="card-overview-preview">{overview}</span>
            </span>
            <span class="card-arrow">▼</span>
        </div>
        <div class="card-body">
            <div class="overview-line">{overview}</div>
            {_render_topic_group(pos_topics, "正面话题", "pos-label", "pos-topic")}
            {_render_topic_group(neg_topics, "负面话题", "neg-label", "neg-topic")}
        </div>
    </div>""")

    return "\n".join(parts)


# ---- 可视化 HTML 生成 ----

def generate_visualization_html():
    """生成可视化网页"""
    daily_data = aggregate_daily_scores()
    if not daily_data:
        print("  没有可可视化的数据")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 准备Chart.js数据
    dates = [d["date"] for d in daily_data]
    counts = [d["post_count"] for d in daily_data]
    positive = [d["positive_count"] for d in daily_data]
    negative = [d["negative_count"] for d in daily_data]
    neutral = [d["neutral_count"] for d in daily_data]
    filtered_scores = [d.get("filtered_avg_score") for d in daily_data]
    filtered_counts = [d.get("filtered_post_count", 0) for d in daily_data]

    # 生成每日总结（增量 + DB缓存）
    print("  正在获取每日发帖总结...")
    summaries = generate_daily_summaries(dates)

    valid_filtered = [s for s in filtered_scores if s is not None]

    # 计算整体统计
    total_posts = sum(counts)
    total_filtered = sum(filtered_counts)
    overall_filtered_avg = round(
        sum(s * c for s, c in zip(filtered_scores, filtered_counts) if s is not None) / total_filtered, 2
    ) if total_filtered > 0 else 0

    # 自适应Y轴范围
    def adaptive_range(data, is_score=False, snap=1):
        dmin, dmax = min(data), max(data)
        span = dmax - dmin
        padding = max(span * 0.3, 2 if is_score else span * 0.1)
        if span == 0:
            padding = 5 if is_score else max(1, dmax * 0.1)
        y_min = max(0, int((dmin - padding) / snap) * snap)
        y_max = int((dmax + padding + snap - 1) / snap) * snap
        if is_score:
            y_min = max(0, y_min)
            y_max = min(100, y_max)
        return y_min, y_max

    score_min, score_max = adaptive_range(valid_filtered, is_score=True) if valid_filtered else (0, 100)
    count_max = adaptive_range(counts)[1]
    sentiment_max = adaptive_range([p + n + neu for p, n, neu in zip(positive, negative, neutral)])[1]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>心动小镇 - TapTap论坛舆情分析</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js">
</script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    color: #e0e0e0;
    min-height: 100vh;
}}
.header {{
    text-align: center;
    padding: 30px 20px 10px;
    background: rgba(255,255,255,0.03);
    border-bottom: 1px solid rgba(255,255,255,0.08);
}}
.header h1 {{
    font-size: 28px;
    background: linear-gradient(90deg, #a78bfa, #60a5fa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 8px;
}}
.header .subtitle {{ color: #94a3b8; font-size: 14px; }}
.stats-row {{
    display: flex; justify-content: center; gap: 24px;
    flex-wrap: wrap; padding: 20px;
}}
.stat-card {{
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px; padding: 18px 28px; text-align: center;
    min-width: 120px;
}}
.stat-card .value {{
    font-size: 32px; font-weight: 700;
    background: linear-gradient(90deg, #c084fc, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.stat-card .label {{ color: #94a3b8; font-size: 13px; margin-top: 4px; }}
.charts-wrapper {{
    max-width: 1200px; margin: 0 auto; padding: 0 20px;
}}
.chart-container {{
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px; padding: 24px; margin-bottom: 24px;
}}
.chart-container h3 {{
    font-size: 16px; color: #cbd5e1; margin-bottom: 16px;
    padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.06);
}}
.chart-canvas-wrap {{ position: relative; height: 380px; }}
.footer {{
    text-align: center; padding: 20px; color: #64748b;
    font-size: 12px;
}}
/* 折叠卡片 */
.daily-summary-section {{
    max-width: 1200px; margin: 0 auto; padding: 0 20px 40px;
}}
.daily-summary-section h3 {{
    font-size: 18px; color: #cbd5e1; margin-bottom: 20px;
    text-align: center;
}}
.daily-card {{
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px; margin-bottom: 12px; overflow: hidden;
    transition: background 0.2s;
}}
.daily-card:hover {{ background: rgba(255,255,255,0.06); }}
.card-header {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; cursor: pointer; user-select: none;
    gap: 16px;
}}
.card-date {{
    font-size: 15px; font-weight: 600; color: #e2e8f0;
    min-width: 100px;
}}
.card-stats {{
    display: flex; gap: 16px; font-size: 13px; color: #94a3b8;
    flex: 1; align-items: center;
}}
.card-overview-preview {{
    color: #94a3b8; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; max-width: 360px;
}}
.card-score-tag {{
    color: #60a5fa; font-weight: 600; white-space: nowrap;
    font-size: 12px;
}}
.card-arrow {{
    font-size: 12px; color: #64748b; transition: transform 0.3s;
    min-width: 20px; text-align: center;
}}
.daily-card.open .card-arrow {{ transform: rotate(180deg); }}
.card-body {{
    display: none; padding: 0 20px 20px; border-top: 1px solid rgba(255,255,255,0.06);
    font-size: 14px; line-height: 1.8;
}}
.daily-card.open .card-body {{ display: block; }}
.overview-line {{
    color: #cbd5e1; margin: 8px 0 4px;
    padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.04);
}}
.card-body .pos-label {{
    color: #34d399; font-weight: 600; margin-top: 10px;
}}
.card-body .neg-label {{
    color: #f87171; font-weight: 600; margin-top: 10px;
}}
.card-body .summary-text {{
    color: #cbd5e1; margin-left: 8px;
}}
/* 话题详细样式 */
.pos-topic, .neg-topic {{
    margin: 8px 0 12px 12px; padding-left: 16px;
    border-left: 2px solid rgba(255,255,255,0.06);
}}
.topic-dot {{
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    margin-right: 8px; vertical-align: middle;
}}
.pos-topic .topic-dot {{ background: #34d399; }}
.neg-topic .topic-dot {{ background: #f87171; }}
.topic-name {{
    font-weight: 600; color: #e2e8f0; font-size: 14px;
    vertical-align: middle;
}}
.topic-detail {{
    margin-top: 4px; color: #94a3b8; font-size: 13px;
    line-height: 1.7; padding-left: 16px;
}}
.no-summary {{
    text-align: center; color: #64748b; padding: 40px;
    font-size: 14px;
}}
</style>
</head>
<body>

<div class="header">
    <h1>心动小镇</h1>
    <p class="subtitle">TapTap论坛玩家舆情时间序列分析</p>
    <p class="subtitle">数据范围: {dates[0]} ~ {dates[-1]} | 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
</div>

<div class="stats-row">
    <div class="stat-card">
        <div class="value">{total_posts}</div>
        <div class="label">帖子总数</div>
    </div>
    <div class="stat-card">
        <div class="value">{overall_filtered_avg}</div>
        <div class="label">观点信号均分</div>
    </div>
    <div class="stat-card">
        <div class="value">{total_filtered}</div>
        <div class="label">有效观点帖</div>
    </div>
    <div class="stat-card">
        <div class="value">{len(dates)}</div>
        <div class="label">统计天数</div>
    </div>
    <div class="stat-card">
        <div class="value">{len(summaries)}</div>
        <div class="label">已总结天数</div>
    </div>
</div>

<div class="charts-wrapper">
    <div class="chart-container">
        <h3>每日观点信号评分趋势（剔除空内容+中性帖）</h3>
        <div class="chart-canvas-wrap">
            <canvas id="scoreChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h3>每日发帖数量</h3>
        <div class="chart-canvas-wrap">
            <canvas id="countChart"></canvas>
        </div>
    </div>

    <div class="chart-container">
        <h3>每日情绪分布 (正面/中性/负面)</h3>
        <div class="chart-canvas-wrap">
            <canvas id="sentimentChart"></canvas>
        </div>
    </div>
</div>

<div class="daily-summary-section">
    <h3>每日发帖内容总结（点击展开）</h3>
    {_render_daily_cards(summaries, filtered_counts, dates, daily_data)}
</div>

<div class="footer">
    Powered by DeepSeek AI · 数据来源: TapTap论坛 · 自动生成
</div>

<script>
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = 'rgba(255,255,255,0.08)';
Chart.defaults.font.family = '-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif';

const dates = {json.dumps(dates, ensure_ascii=False)};
const filteredScores = {json.dumps(filtered_scores)};
const counts = {json.dumps(counts)};
const positive = {json.dumps(positive)};
const negative = {json.dumps(negative)};
const neutral = {json.dumps(neutral)};

// 观点信号评分趋势图
new Chart(document.getElementById('scoreChart'), {{
    type: 'line',
    data: {{
        labels: dates,
        datasets: [{{
            label: '观点信号评分',
            data: filteredScores,
            borderColor: '#60a5fa',
            backgroundColor: 'rgba(96,165,250,0.15)',
            fill: true,
            tension: 0.3,
            pointRadius: 4,
            pointBackgroundColor: '#60a5fa',
            borderWidth: 2,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ labels: {{ usePointStyle: true }} }},
            tooltip: {{
                callbacks: {{
                    label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y !== null ? ctx.parsed.y + ' 分' : '无数据')
                }}
            }}
        }},
        scales: {{
            y: {{
                min: {score_min}, max: {score_max},
                ticks: {{ callback: v => v + '分' }},
                grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }},
            x: {{
                grid: {{ display: false }},
                ticks: {{ maxTicksLimit: 20 }}
            }}
        }},
        interaction: {{ intersect: false, mode: 'index' }}
    }}
}});

// 发帖数量图
new Chart(document.getElementById('countChart'), {{
    type: 'bar',
    data: {{
        labels: dates,
        datasets: [{{
            label: '发帖数',
            data: counts,
            backgroundColor: 'rgba(96,165,250,0.5)',
            borderColor: '#60a5fa',
            borderWidth: 1,
            borderRadius: 4,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ labels: {{ usePointStyle: true }} }},
        }},
        scales: {{
            y: {{
                min: 0, max: {count_max},
                grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }},
            x: {{
                grid: {{ display: false }},
                ticks: {{ maxTicksLimit: 20 }}
            }}
        }},
        interaction: {{ intersect: false, mode: 'index' }}
    }}
}});

// 情绪分布图
new Chart(document.getElementById('sentimentChart'), {{
    type: 'bar',
    data: {{
        labels: dates,
        datasets: [
            {{
                label: '正面',
                data: positive,
                backgroundColor: 'rgba(52,211,153,0.6)',
                borderColor: '#34d399',
                borderWidth: 1,
            }},
            {{
                label: '中性',
                data: neutral,
                backgroundColor: 'rgba(251,191,36,0.6)',
                borderColor: '#fbbf24',
                borderWidth: 1,
            }},
            {{
                label: '负面',
                data: negative,
                backgroundColor: 'rgba(248,113,113,0.6)',
                borderColor: '#f87171',
                borderWidth: 1,
            }}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ labels: {{ usePointStyle: true }} }},
        }},
        scales: {{
            x: {{
                stacked: true,
                grid: {{ display: false }},
                ticks: {{ maxTicksLimit: 20 }}
            }},
            y: {{
                stacked: true,
                min: 0, max: {sentiment_max},
                grid: {{ color: 'rgba(255,255,255,0.04)' }}
            }}
        }},
        interaction: {{ intersect: false, mode: 'index' }}
    }}
}});
</script>
</body>
</html>"""

    with open(VISUALIZATION_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  可视化网页已生成: {VISUALIZATION_PATH}")
    return VISUALIZATION_PATH
