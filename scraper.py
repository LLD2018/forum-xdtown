"""
爬虫模块 - 爬取TapTap论坛帖子列表（API方式）和详情（HTML方式）
目标: 心动小镇 (App ID: 45213)
"""
import re
import time
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from config import (
    FORUM_LIST_URL, MOMENT_URL, HEADERS, REQUEST_DELAY,
    REQUEST_TIMEOUT, MAX_RETRIES, BASE_URL, APP_ID
)
import database as db

# TapTap 内部 API
FEED_API = "https://www.taptap.cn/webapiv2/feed/v7/by-group"
GROUP_ID = "4761"

# X-UA 令牌（设备指纹，从页面JS中提取）
XUA_PLAIN = (
    "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC"
    "&DS=Android&UID=9285e6fb-d8be-49b4-9dcc-ef16ae2924bd"
    "&OS=Windows&OSV=10&DT=PC"
)


def create_session():
    """创建带cookie持久化的请求会话"""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def fetch_api(session, params, retries=MAX_RETRIES):
    """请求TapTap API，带重试"""
    for attempt in range(retries):
        try:
            resp = session.get(FEED_API, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"  API返回 {resp.status_code}: {resp.text[:200]}")
                if attempt < retries - 1:
                    time.sleep(3)
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 3
                print(f"  API请求失败: {e}，{wait}秒后重试...")
                time.sleep(wait)
            else:
                print(f"  API请求失败，已达最大重试次数: {e}")
    return None


def fetch_page(session, url, retries=MAX_RETRIES):
    """请求HTML页面，带重试"""
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 3
                print(f"  请求失败: {e}，{wait}秒后重试...")
                time.sleep(wait)
            else:
                print(f"  请求失败，已达最大重试次数: {e}")
    return None


def parse_api_post(item):
    """将API返回的单条帖子数据转为数据库格式"""
    moment = item.get("moment", {})
    author_data = moment.get("author", {}).get("user", {})
    topic = moment.get("topic", {})
    stat = moment.get("stat", {})

    # 提取图片
    images = []
    for img in topic.get("footer_images", []):
        url = img.get("original_url") or img.get("medium_url") or img.get("url", "")
        if url:
            images.append(url)

    # 时间戳转换
    created_ts = moment.get("created_time", 0)
    if isinstance(created_ts, (int, float)) and created_ts > 0:
        post_time = datetime.fromtimestamp(created_ts).strftime("%Y/%m/%d %H:%M:%S")
    else:
        post_time = ""

    # 内容：topic.title 就是帖子正文
    title = topic.get("title", "")
    content = title  # API中title即为正文内容

    moment_id = moment.get("id_str", "")
    author_name = author_data.get("name", "")
    author_id = author_data.get("id", "")

    return {
        "moment_id": moment_id,
        "url": f"{MOMENT_URL}/{moment_id}",
        "title": title,
        "author": author_name,
        "author_url": f"/user/{author_id}" if author_id else "",
        "post_time": post_time,
        "content": content,
        "images": images,
    }


def scrape_list_via_api(session, max_posts=None, callback=None):
    """
    通过API爬取帖子列表（游标分页）
    max_posts: 最多爬取帖子数，None表示全部
    callback: callback(page_num, posts_in_batch, new_count)
    返回: 所有新发现的帖子
    """
    all_posts = []
    total_new = 0
    batch_num = 0
    next_page = ""  # 第一页用空字符串

    base_params = {
        "X-UA": XUA_PLAIN,
        "type": "feed",
        "group_id": GROUP_ID,
        "sort": "created",
        "limit": "10",
        "status": "0",
        "with_hot_comment": "true",
    }

    print(f"\n  开始API爬取 (group_id={GROUP_ID}, sort=created)")

    while True:
        batch_num += 1

        if max_posts and total_new >= max_posts:
            print(f"  已达到目标数量 {max_posts}，停止")
            break

        params = dict(base_params)
        if next_page:
            # next_page 是完整URL路径，需要从中提取 'from' 参数值
            from_match = re.search(r'[?&]from=(\d+)', next_page)
            if from_match:
                params["from"] = from_match.group(1)
            else:
                print(f"  无法解析分页标记: {next_page[:80]}...")
                break

        print(f"\n  [批次 {batch_num}] 请求API..."
              f" (from={params.get('from', 'start')})")

        data = fetch_api(session, params)
        if not data:
            print(f"  批次 {batch_num} 请求失败，跳过")
            time.sleep(REQUEST_DELAY * 2)
            continue

        result = data.get("data", {})
        post_list = result.get("list", [])
        next_page = result.get("next_page", "")
        total = result.get("total", 0)

        if not post_list:
            print(f"  无更多帖子，停止 (total={total})")
            break

        batch_new = 0
        for item in post_list:
            post = parse_api_post(item)
            if not post["moment_id"]:
                continue

            if not db.moment_exists(post["moment_id"]):
                db.save_post(post)
                all_posts.append(post)
                batch_new += 1
                total_new += 1

        oldest_time = ""
        if post_list:
            last_moment = post_list[-1].get("moment", {})
            oldest_ts = last_moment.get("created_time", 0)
            if oldest_ts:
                oldest_time = datetime.fromtimestamp(oldest_ts).strftime("%Y-%m-%d %H:%M")

        print(f"  批次 {batch_num}: 获取 {len(post_list)} 条, "
              f"新增 {batch_new} 条, 累计新增 {total_new}, "
              f"最早: {oldest_time}")

        if callback:
            callback(batch_num, len(post_list), batch_new)

        if not next_page:
            print(f"  已到最后一页 (total announced: {total})")
            break

        time.sleep(REQUEST_DELAY)

    print(f"\n  API爬取完成: {batch_num} 批次, 共新增 {total_new} 条帖子")
    return all_posts


def scrape_post_detail(session, post):
    """
    爬取单个帖子详情页 - 获取更完整的内容（如API未给的富文本）
    """
    url = post.get("url") or f"{MOMENT_URL}/{post['moment_id']}"
    post["url"] = url
    html = fetch_page(session, url)
    if not html:
        return post

    soup = BeautifulSoup(html, "html.parser")

    # 标题 - h1[itemprop="name"]
    title_el = soup.select_one('h1[itemprop="name"], [itemprop="name"].moment-head__title')
    if title_el:
        detail_title = title_el.get_text(strip=True)
        if detail_title and detail_title != post.get("title"):
            post["title"] = detail_title

    # 发帖时间
    time_el = soup.select_one('[itemprop="dateCreated"]')
    if time_el:
        t = time_el.get("title", "") or time_el.get_text(strip=True)
        if t:
            post["post_time"] = t

    # 富文本内容
    content_els = soup.select('[itemprop="text"] .tap-rich-content__body, .tap-rich-content__body, .rich-content--topic')
    contents = []
    for el in content_els:
        text = el.get_text(strip=True)
        if text:
            contents.append(text)
    detail_content = "\n".join(contents)

    # 如果详情页内容比API更多，使用详情页的
    api_content = post.get("content", "")
    if detail_content and len(detail_content) > len(api_content or ""):
        post["content"] = detail_content

    # 作者
    if not post.get("author"):
        author_el = soup.select_one('a[href*="/user/"]')
        if author_el:
            post["author"] = author_el.get_text(strip=True)
            post["author_url"] = author_el.get("href", "")

    # 图片 (补充API可能遗漏的)
    img_els = soup.select('.tap-image-list img.tap-image')
    for img in img_els:
        src = img.get("src", "")
        if src and "tapimg.com" in src and src not in post.get("images", []):
            post["images"].append(src)

    return post


def scrape_all_details(session, posts=None, callback=None):
    """
    爬取所有帖子的详情页（补充API未获取的富文本）
    posts: 帖子列表，为None则从DB查询
    """
    if posts is None:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM posts WHERE content IS NULL OR content = ''")
        posts = [dict(row) for row in cursor.fetchall()]
        conn.close()

    if not posts:
        print("  没有需要爬取详情的帖子")
        return []

    total = len(posts)
    updated = 0
    for i, post in enumerate(posts):
        moment_id = post["moment_id"]

        # 检查是否需要更新（API获取的也算有内容）
        if post.get("content") and len(post.get("content", "")) > 10:
            print(f"  [{i+1}/{total}] 帖子 {moment_id} 已有内容，跳过")
            continue

        print(f"  [{i+1}/{total}] 爬取帖子详情: {moment_id}")

        post = scrape_post_detail(session, post)
        db.save_post(post)
        updated += 1

        if callback:
            callback(i + 1, total, post)

        time.sleep(REQUEST_DELAY)

    print(f"  详情爬取完成: 更新 {updated}/{total} 条")
    return posts
