"""
数据库模块 - SQLite 数据库操作
提供帖子和每日评分的 CRUD 操作
"""
import sqlite3
import os
import json
from datetime import datetime
from config import DB_DIR, DB_PATH


def get_connection():
    """获取数据库连接"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            moment_id TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            author TEXT,
            author_url TEXT,
            post_time TEXT,
            content TEXT,
            images TEXT,
            score INTEGER,
            sentiment TEXT,
            score_reason TEXT,
            scored_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            avg_score REAL,
            post_count INTEGER,
            positive_count INTEGER,
            negative_count INTEGER,
            neutral_count INTEGER,
            filtered_avg_score REAL,
            filtered_post_count INTEGER,
            filtered_positive_count INTEGER,
            filtered_negative_count INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 创建索引加速查询
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_moment_id ON posts(moment_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_post_time ON posts(post_time)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_score ON posts(score)
    """)
    # 迁移：为已有 daily_scores 表添加过滤评分的列
    for col_def in [
        ("filtered_avg_score", "REAL"),
        ("filtered_post_count", "INTEGER"),
        ("filtered_positive_count", "INTEGER"),
        ("filtered_negative_count", "INTEGER"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE daily_scores ADD COLUMN {col_def[0]} {col_def[1]}")
        except sqlite3.OperationalError:
            pass  # 列已存在
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            post_count TEXT,
            positive TEXT,
            negative TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def moment_exists(moment_id):
    """检查某个帖子是否已经存在于数据库中"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM posts WHERE moment_id = ?", (moment_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def save_post(post_data):
    """
    保存帖子数据到数据库
    post_data: dict with keys: moment_id, url, title, author, author_url,
               post_time, content, images
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 清理作者名 - 去除多余的标签文本
    author = post_data.get("author", "")
    if author:
        author = author.strip()
        # 去除常见的时间后缀污染 (如 "1 分钟前好友滴滴")
        import re
        author = re.sub(r'\d+\s*(分钟|小时|天|周|月|年)前.*$', '', author).strip()
        author = re.sub(r'好友滴滴.*$', '', author).strip()
        author = re.sub(r'佛系摸鱼.*$', '', author).strip()

    cursor.execute("""
        INSERT OR REPLACE INTO posts
        (moment_id, url, title, author, author_url, post_time, content, images)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        post_data.get("moment_id"),
        post_data.get("url"),
        post_data.get("title"),
        author,
        post_data.get("author_url"),
        post_data.get("post_time"),
        post_data.get("content"),
        json.dumps(post_data.get("images", []), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()


def update_post_score(moment_id, score, sentiment, reason=""):
    """更新帖子的评分信息"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE posts SET score = ?, sentiment = ?, score_reason = ?, scored_at = ?
        WHERE moment_id = ?
    """, (score, sentiment, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), moment_id))
    conn.commit()
    conn.close()


def get_unscored_posts(limit=None):
    """获取尚未评分的帖子"""
    conn = get_connection()
    cursor = conn.cursor()
    if limit:
        cursor.execute(
            "SELECT * FROM posts WHERE score IS NULL ORDER BY id LIMIT ?",
            (limit,)
        )
    else:
        cursor.execute(
            "SELECT * FROM posts WHERE score IS NULL ORDER BY id"
        )
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_all_posts(order_by="post_time DESC", limit=None):
    """获取所有帖子"""
    conn = get_connection()
    cursor = conn.cursor()
    query = f"SELECT * FROM posts ORDER BY {order_by}"
    if limit:
        query += f" LIMIT {limit}"
    cursor.execute(query)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_posts_count():
    """获取帖子总数"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM posts")
    result = cursor.fetchone()
    conn.close()
    return result["count"]


def get_scored_count():
    """获取已评分的帖子数"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM posts WHERE score IS NOT NULL")
    result = cursor.fetchone()
    conn.close()
    return result["count"]


def get_posts_by_date_range(start_date, end_date):
    """获取指定日期范围内的帖子"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM posts
        WHERE post_time >= ? AND post_time <= ?
        ORDER BY post_time DESC
    """, (start_date, end_date))
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def upsert_daily_score(date, avg_score, post_count, positive_count,
                        negative_count, neutral_count,
                        filtered_avg_score=None, filtered_post_count=None,
                        filtered_positive_count=None, filtered_negative_count=None):
    """插入或更新每日评分汇总（含过滤后评分）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO daily_scores
        (date, avg_score, post_count, positive_count, negative_count,
         neutral_count, filtered_avg_score, filtered_post_count,
         filtered_positive_count, filtered_negative_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        date, avg_score, post_count, positive_count, negative_count,
        neutral_count, filtered_avg_score, filtered_post_count,
        filtered_positive_count, filtered_negative_count,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


def get_all_daily_scores():
    """获取所有每日评分数据"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_scores ORDER BY date")
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_database_stats():
    """获取数据库统计信息"""
    conn = get_connection()
    cursor = conn.cursor()
    stats = {}

    cursor.execute("SELECT COUNT(*) as count FROM posts")
    stats["total_posts"] = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) as count FROM posts WHERE score IS NOT NULL")
    stats["scored_posts"] = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) as count FROM posts WHERE score IS NULL")
    stats["unscored_posts"] = cursor.fetchone()["count"]

    if stats["scored_posts"] > 0:
        cursor.execute("SELECT AVG(score) as avg FROM posts WHERE score IS NOT NULL")
        stats["avg_score"] = round(cursor.fetchone()["avg"], 2)
    else:
        stats["avg_score"] = 0

    cursor.execute("SELECT COUNT(*) as count FROM daily_scores")
    stats["daily_records"] = cursor.fetchone()["count"]

    # 情绪分布
    cursor.execute("""
        SELECT sentiment, COUNT(*) as count FROM posts
        WHERE sentiment IS NOT NULL
        GROUP BY sentiment
    """)
    sentiment_counts = {row["sentiment"]: row["count"] for row in cursor.fetchall()}
    stats["positive_count"] = sentiment_counts.get("positive", 0)
    stats["negative_count"] = sentiment_counts.get("negative", 0)
    stats["neutral_count"] = sentiment_counts.get("neutral", 0)

    # 日期范围
    cursor.execute("SELECT MIN(post_time) as min_date, MAX(post_time) as max_date FROM posts WHERE post_time IS NOT NULL")
    date_range = cursor.fetchone()
    stats["date_range"] = f"{date_range['min_date']} ~ {date_range['max_date']}" if date_range["min_date"] else "无数据"

    conn.close()
    return stats


def search_posts(keyword, field="title"):
    """按关键词搜索帖子"""
    conn = get_connection()
    cursor = conn.cursor()
    if field == "title":
        cursor.execute(
            "SELECT * FROM posts WHERE title LIKE ? ORDER BY post_time DESC",
            (f"%{keyword}%",)
        )
    elif field == "content":
        cursor.execute(
            "SELECT * FROM posts WHERE content LIKE ? ORDER BY post_time DESC",
            (f"%{keyword}%",)
        )
    elif field == "author":
        cursor.execute(
            "SELECT * FROM posts WHERE author LIKE ? ORDER BY post_time DESC",
            (f"%{keyword}%",)
        )
    else:
        cursor.execute(
            "SELECT * FROM posts WHERE title LIKE ? OR content LIKE ? ORDER BY post_time DESC",
            (f"%{keyword}%", f"%{keyword}%")
        )
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_daily_opinion_posts(date_str):
    """
    获取某一天有明确观点的帖子（正面+负面），含标题和评分理由
    date_str: "YYYY-MM-DD" 或 "YYYY/MM/DD"
    返回: {"positive": [...], "negative": [...]}
    """
    conn = get_connection()
    cursor = conn.cursor()
    # DB 中 post_time 格式为 YYYY/MM/DD HH:MM:SS
    date_slash = date_str.replace("-", "/")
    result = {"positive": [], "negative": []}
    for sentiment in ("positive", "negative"):
        cursor.execute("""
            SELECT title, content, score, score_reason FROM posts
            WHERE post_time LIKE ? AND sentiment = ?
            ORDER BY score DESC
        """, (f"{date_slash}%", sentiment))
        rows = cursor.fetchall()
        result[sentiment] = [
            {
                "title": (r["title"] or ""),
                "content": (r["content"] or ""),
                "score": r["score"],
                "reason": (r["score_reason"] or ""),
            }
            for r in rows
        ]
    conn.close()
    return result


def upsert_daily_summary(date, post_count, positive, negative):
    """插入或更新每日发帖总结"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO daily_summaries (date, post_count, positive, negative, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (date, post_count, positive, negative,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_all_daily_summaries():
    """获取所有每日总结"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT date, post_count, positive, negative FROM daily_summaries ORDER BY date DESC")
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_dates_without_summary(dates):
    """返回哪些日期还没有总结"""
    if not dates:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join(["?" for _ in dates])
    cursor.execute(f"""
        SELECT date FROM daily_summaries WHERE date IN ({placeholders})
    """, dates)
    existing = {row[0] for row in cursor.fetchall()}
    conn.close()
    return [d for d in dates if d not in existing]


def delete_all_posts():
    """删除所有帖子（谨慎使用）"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM posts")
    cursor.execute("DELETE FROM daily_scores")
    conn.commit()
    conn.close()
