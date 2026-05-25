"""
分析器模块 - 通过DeepSeek API对帖子进行情感评分
游戏: 心动小镇
"""
import time
import json
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
import database as db


def create_client():
    """创建DeepSeek API客户端"""
    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )


SYSTEM_PROMPT = """你是一个专业的游戏社区内容分析助手。你的任务是分析TapTap论坛用户对游戏【心动小镇】的帖子内容，判断用户对该游戏的评价态度。

请按以下规则评分（1-100分）：
- 90-100: 非常正面，对游戏高度赞扬、推荐、表达喜爱
- 70-89: 正面，总体满意，有一些建设性意见
- 50-69: 中性偏正，有肯定也有吐槽，整体平和
- 30-49: 负面，有明显不满、失望、批评
- 1-29: 非常负面，强烈谴责、劝退、表达愤怒

请以JSON格式返回，格式严格如下：
{"score": 75, "sentiment": "positive", "reason": "用户对游戏玩法表示认可，但提到了一些优化建议"}

sentiment 只能是 "positive"、"negative" 或 "neutral"
reason 控制在50字以内"""


def analyze_post(client, post):
    """
    对单个帖子进行情感分析
    返回: (score, sentiment, reason)
    """
    content = post.get("content") or ""
    title = post.get("title") or ""

    if not content and not title:
        return 50, "neutral", "无内容"

    user_message = f"帖子标题：{title}\n\n帖子内容：{content[:2000]}"

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            stream=False,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )

        result_text = response.choices[0].message.content.strip()

        # 尝试提取JSON
        # 处理可能的markdown代码块
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()

        result = json.loads(result_text)
        score = int(result.get("score", 50))
        sentiment = result.get("sentiment", "neutral")
        reason = result.get("reason", "")

        # 限制分数范围
        score = max(1, min(100, score))

        # 验证sentiment
        if sentiment not in ("positive", "negative", "neutral"):
            sentiment = "neutral"

        return score, sentiment, reason

    except json.JSONDecodeError:
        # 尝试从文本中解析分数
        import re
        score_match = re.search(r'"score"?\s*:\s*(\d+)', result_text)
        score = int(score_match.group(1)) if score_match else 50
        score = max(1, min(100, score))

        if "positive" in result_text.lower():
            sentiment = "positive"
        elif "negative" in result_text.lower():
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return score, sentiment, result_text[:200]

    except Exception as e:
        print(f"  DeepSeek API调用失败: {e}")
        return 50, "neutral", f"API错误: {str(e)[:100]}"


def analyze_all_unscored(client=None, delay=1, callback=None, limit=None):
    """
    对所有未评分的帖子进行情感分析
    callback: 可选回调 callback(index, total, post, score, sentiment)
    """
    if client is None:
        client = create_client()

    posts = db.get_unscored_posts(limit=limit)
    total = len(posts)

    if total == 0:
        print("  没有待评分的帖子")
        return

    print(f"  共有 {total} 个帖子待评分")

    for i, post in enumerate(posts):
        moment_id = post["moment_id"]
        title = post.get("title", "")[:40]
        print(f"  [{i+1}/{total}] 分析帖子 {moment_id}: {title}...")

        score, sentiment, reason = analyze_post(client, post)

        db.update_post_score(moment_id, score, sentiment, reason)
        print(f"    评分: {score} 分, 情绪: {sentiment}")

        if callback:
            callback(i + 1, total, post, score, sentiment)

        time.sleep(delay)

    print(f"  评分完成，共处理 {total} 个帖子")


def analyze_single_post(post_or_moment_id):
    """分析单个帖子"""
    client = create_client()

    if isinstance(post_or_moment_id, str):
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM posts WHERE moment_id = ?", (post_or_moment_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            post = dict(row)
        else:
            print(f"  帖子 {post_or_moment_id} 不存在")
            return None
    else:
        post = post_or_moment_id

    score, sentiment, reason = analyze_post(client, post)
    db.update_post_score(post["moment_id"], score, sentiment, reason)
    return score, sentiment, reason
