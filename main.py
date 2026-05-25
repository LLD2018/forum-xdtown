"""
============================================================
  TapTap论坛爬虫 & 舆情分析系统
  游戏: 心动小镇 (App ID: 45213)
============================================================

主程序 - 交互式控制台菜单
提供爬取、评分、可视化、数据浏览等功能的统一入口
"""
import os
import sys
import time
import webbrowser
from datetime import datetime

# 修复Windows控制台编码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db
import scraper
import analyzer
import visualizer
from config import VISUALIZATION_PATH, START_PAGE, MAX_PAGES, REQUEST_DELAY


# ============================================================
# 控制台UI工具函数
# ============================================================

def cwidth(s):
    """计算字符串的显示宽度（中文字符占2位）"""
    width = 0
    for ch in s:
        if '一' <= ch <= '鿿' or '　' <= ch <= '〿' or '＀' <= ch <= '￯':
            width += 2
        else:
            width += 1
    return width


def cpad(text, target_width, align="left", fill=" "):
    """按显示宽度填充字符串"""
    cur = cwidth(text)
    if cur >= target_width:
        return text
    diff = target_width - cur
    if align == "left":
        return text + fill * diff
    elif align == "right":
        return fill * diff + text
    else:  # center
        left = diff // 2
        right = diff - left
        return fill * left + text + fill * right


def print_separator(char="=", width=60):
    """打印分隔线"""
    print(char * width)


def print_header():
    """打印程序标题"""
    os.system("cls" if os.name == "nt" else "clear")
    print()
    print_separator("=", 60)
    print(cpad("  TapTap论坛爬虫 & 舆情分析系统", 58, "center"))
    print(cpad("  游戏: 心动小镇 | App ID: 45213", 56, "center"))
    print_separator("=", 60)
    print()


def print_menu():
    """打印主菜单"""
    menu_items = [
        ("1", "爬取帖子列表", "从论坛列表页获取所有帖子链接"),
        ("2", "爬取帖子详情", "爬取每个帖子的标题/作者/时间/内容"),
        ("3", "AI情感评分", "通过DeepSeek API对帖子进行评分(1-100)"),
        ("4", "一键全流程", "列表→详情→评分 全自动执行"),
        ("5", "生成可视化网页", "生成每日舆情评分趋势图表"),
        ("6", "浏览数据库", "查看/搜索数据库中的帖子和统计"),
        ("7", "数据库统计", "显示数据库整体统计信息"),
        ("8", "重新计算每日汇总", "重新聚合每日评分数据"),
        ("0", "退出程序", ""),
    ]

    print("  主菜单:")
    print("  " + "-" * 56)
    for key, name, desc in menu_items:
        line = f"  [{key}] {name}"
        if desc:
            line = cpad(line, 32) + f"- {desc}"
        print(line)
    print("  " + "-" * 56)
    print()


def print_stage(stage_name):
    """打印阶段标识"""
    print()
    print_separator("-", 50)
    print(f"  >>> {stage_name}")
    print_separator("-", 50)


def print_result(label, value, indent=2):
    """对齐打印结果"""
    prefix = " " * indent
    print(f"{prefix}{cpad(label, 18)}: {value}")


def safe_input(prompt):
    """安全的输入函数，处理EOF"""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "0"


def press_enter():
    """等待用户按回车"""
    safe_input("\n  按回车键返回主菜单...")


# ============================================================
# 功能模块
# ============================================================

def func_scrape_list():
    """功能1: 爬取帖子列表（通过TapTap API，游标分页）"""
    print_stage("阶段一: 爬取帖子列表 (API方式)")
    print()
    print("  通过TapTap内部API获取帖子列表 (游标分页)")
    print(f"  API: {scraper.FEED_API}")
    print(f"  Group ID: {scraper.GROUP_ID}")
    print()

    # 输入帖子数量限制
    try:
        limit_str = safe_input(f"  最多爬取帖子数 (默认1000, 输入0=全部, 最多约10000): ")
        if limit_str:
            max_posts = int(limit_str)
        else:
            max_posts = 1000
    except ValueError:
        print("  请输入有效数字")
        return

    if max_posts == 0:
        max_posts = None
        print(f"\n  将爬取全部帖子（约10000条，耗时较长）")
    else:
        print(f"\n  最多爬取: {max_posts} 条帖子")
    print(f"  请求间隔: {REQUEST_DELAY} 秒")

    total_found = [0]
    total_new = [0]
    batch_count = [0]

    def progress_callback(batch, found, new):
        batch_count[0] += 1
        total_found[0] += found
        total_new[0] += new

    session = scraper.create_session()
    start_time = time.time()

    posts = scraper.scrape_list_via_api(
        session, max_posts=max_posts,
        callback=progress_callback
    )

    elapsed = time.time() - start_time

    print()
    print_separator("-", 50)
    print(f"  列表爬取完成!")
    print(f"  耗时: {elapsed:.1f} 秒")
    print(f"  批次数: {batch_count[0]}")
    print(f"  获取帖子: {total_found[0]}")
    print(f"  新增帖子: {total_new[0]} (已在数据库中的跳过)")
    print_separator("-", 50)

    session.close()


def func_scrape_details():
    """功能2: 爬取帖子详情"""
    print_stage("阶段二: 爬取帖子详情页")

    # 获取数据库中尚未爬取详情的帖子
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM posts WHERE content IS NULL OR content = ''")
    pending = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not pending:
        # 尝试从列表页获取的帖子
        all_posts = db.get_all_posts()
        pending = [p for p in all_posts if not p.get("content")]
        if not pending:
            print("\n  所有帖子已有详情数据，无需爬取")
            print("  提示: 请先执行 [功能1: 爬取帖子列表] 获取帖子链接")
            return

    print(f"\n  待爬取详情的帖子: {len(pending)} 个")
    print(f"  请求间隔: {REQUEST_DELAY} 秒")

    try:
        limit_str = safe_input(f"\n  每次爬取数量 (默认全部, 输入0=全部): ")
        limit = int(limit_str) if limit_str else 0
    except ValueError:
        limit = 0

    if limit > 0:
        pending = pending[:limit]
        print(f"  限制爬取: {limit} 个")
    else:
        print(f"  将爬取全部 {len(pending)} 个帖子")

    session = scraper.create_session()
    start_time = time.time()
    success_count = [0]

    def progress_callback(index, total, post):
        if post.get("title"):
            success_count[0] += 1

    scraper.scrape_all_details(session, pending, callback=progress_callback)

    elapsed = time.time() - start_time

    print()
    print_separator("-", 50)
    print(f"  详情爬取完成!")
    print(f"  耗时: {elapsed:.1f} 秒")
    print(f"  成功: {success_count[0]}/{len(pending)}")
    print_separator("-", 50)

    session.close()


def func_analyze():
    """功能3: AI情感评分"""
    print_stage("阶段三: DeepSeek AI 情感评分")
    print()

    unscored = db.get_unscored_posts()
    if not unscored:
        print("  所有帖子已完成评分")
        return

    print(f"  待评分帖子: {len(unscored)} 个")
    print(f"  使用模型: {analyzer.DEEPSEEK_MODEL}")

    try:
        limit_str = safe_input(f"\n  每次评分数量 (默认全部, 0=全部): ")
        limit = int(limit_str) if limit_str else 0
    except ValueError:
        limit = 0

    if limit > 0:
        unscored = unscored[:limit]
        print(f"  限制评分: {limit} 个")
    else:
        print(f"  将评分全部 {len(unscored)} 个帖子")

    print()

    client = analyzer.create_client()
    start_time = time.time()

    def progress_callback(index, total, post, score, sentiment):
        title = post.get("title", "")[:30]
        print(f"    -> {score}分 [{sentiment}] {title}")

    analyzer.analyze_all_unscored(
        client, delay=1, callback=progress_callback, limit=limit
    )

    elapsed = time.time() - start_time
    print()
    print_separator("-", 50)
    print(f"  评分完成! 耗时: {elapsed:.1f} 秒")
    print_separator("-", 50)


def func_auto():
    """功能4: 一键全流程"""
    print_stage("一键全流程: 列表(API) → 详情 → 评分")
    print()

    try:
        limit_str = safe_input(f"  最多爬取帖子数 (默认500, 输入0=全部): ")
        max_posts = int(limit_str) if limit_str else 500
    except ValueError:
        print("  请输入有效数字")
        return

    if max_posts == 0:
        max_posts = None

    print()
    session = scraper.create_session()
    client = analyzer.create_client()

    # === 步骤1: 爬取列表 (API) ===
    print_stage("步骤1/3: 爬取帖子列表 (API)")
    posts = scraper.scrape_list_via_api(session, max_posts=max_posts)
    print(f"  新增帖子: {len(posts)} 个")

    # === 步骤2: 爬取详情 (补充富文本) ===
    print_stage("步骤2/3: 爬取帖子详情 (补充内容)")
    scraper.scrape_all_details(session, posts if posts else None)

    # === 步骤3: AI评分 ===
    print_stage("步骤3/3: AI情感评分")
    unscored = db.get_unscored_posts()
    if unscored:
        analyzer.analyze_all_unscored(client, delay=1)
    else:
        print("  没有待评分的帖子")

    session.close()

    print()
    print_separator("=", 50)
    print("  全流程完成!")
    print_separator("=", 50)


def func_visualize():
    """功能5: 生成可视化网页"""
    print_stage("生成可视化网页")
    print()

    path = visualizer.generate_visualization_html()

    if path:
        print()
        print(f"  可视化网页: {path}")
        try:
            open_cmd = safe_input("  是否在浏览器中打开? (y/n, 默认y): ")
            if open_cmd.lower() != "n":
                webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
                print("  已在浏览器中打开")
        except Exception:
            print("  请手动打开上述文件")


def func_browse():
    """功能6: 浏览数据库"""
    while True:
        print_stage("浏览数据库")
        print()
        print("  [1] 查看最新帖子 (前20条)")
        print("  [2] 搜索帖子")
        print("  [3] 按评分范围查看")
        print("  [4] 查看每日评分汇总")
        print("  [5] 查看单个帖子详情")
        print("  [0] 返回主菜单")
        print()

        choice = safe_input("  请选择: ")

        if choice == "1":
            posts = db.get_all_posts(limit=20)
            print()
            if not posts:
                print("  数据库为空")
                press_enter()
                continue
            print(f"  {'ID':<20} {'标题':<30} {'评分':<6} {'时间':<20}")
            print("  " + "-" * 76)
            for p in posts:
                mid = p["moment_id"][:18]
                title = (p.get("title") or "无标题")[:28]
                score = str(p.get("score") or "-")
                ptime = (p.get("post_time") or "")[:19]
                # 中文宽度对齐
                print(f"  {mid:<20} {title:<30} {score:<6} {ptime:<20}")
            print()
            print(f"  共显示 {len(posts)} 条记录")
            press_enter()

        elif choice == "2":
            keyword = safe_input("  搜索关键词: ")
            if not keyword:
                continue
            field = safe_input("  搜索字段 (title/content/author/all, 默认all): ") or "all"
            posts = db.search_posts(keyword, field)
            print()
            print(f"  找到 {len(posts)} 条结果:")
            for p in posts[:30]:
                print(f"  [{p.get('score') or '-':>3}分] {p.get('title','无标题')[:50]}")
                print(f"         作者: {p.get('author','未知')} | 时间: {p.get('post_time','')[:19]}")
                print()
            if len(posts) > 30:
                print(f"  ... 还有 {len(posts) - 30} 条结果")
            press_enter()

        elif choice == "3":
            try:
                min_s = int(safe_input("  最低分 (1-100): ") or "1")
                max_s = int(safe_input("  最高分 (1-100): ") or "100")
            except ValueError:
                continue
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM posts WHERE score BETWEEN ? AND ? ORDER BY score DESC LIMIT 30",
                (min_s, max_s)
            )
            posts = [dict(row) for row in cursor.fetchall()]
            conn.close()
            print()
            print(f"  评分 {min_s}-{max_s} 的帖子 ({len(posts)} 条):")
            for p in posts:
                title = (p.get("title") or "无标题")[:50]
                print(f"  [{p.get('score'):>3}分] [{p.get('sentiment',''):>8}] {title}")
            press_enter()

        elif choice == "4":
            daily = visualizer.get_daily_scores()
            print()
            if not daily:
                print("  暂无每日汇总数据，请先完成帖子评分")
                press_enter()
                continue
            print(f"  {'日期':<14} {'均分':<8} {'帖子数':<8} {'正面':<6} {'中性':<6} {'负面':<6}")
            print("  " + "-" * 56)
            for d in daily:
                print(f"  {d['date']:<14} {d['avg_score']:<8} {d['post_count']:<8} "
                      f"{d['positive_count']:<6} {d['neutral_count']:<6} {d['negative_count']:<6}")
            print()
            press_enter()

        elif choice == "5":
            mid = safe_input("  帖子 moment_id: ")
            if not mid:
                continue
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM posts WHERE moment_id = ?", (mid,))
            row = cursor.fetchone()
            conn.close()
            if row:
                p = dict(row)
                print()
                print(f"  moment_id: {p['moment_id']}")
                print(f"  URL:      {p['url']}")
                print(f"  标题:     {p.get('title','')}")
                print(f"  作者:     {p.get('author','')}")
                print(f"  时间:     {p.get('post_time','')}")
                print(f"  评分:     {p.get('score','未评分')}")
                print(f"  情绪:     {p.get('sentiment','')}")
                print(f"  理由:     {p.get('score_reason','')}")
                print(f"  内容:")
                content = p.get("content") or ""
                for i in range(0, len(content), 70):
                    print(f"    {content[i:i+70]}")
            else:
                print(f"  未找到帖子: {mid}")
            press_enter()

        elif choice == "0":
            break


def func_stats():
    """功能7: 数据库统计"""
    print_stage("数据库统计信息")
    print()

    stats = db.get_database_stats()

    print_result("总帖子数", stats["total_posts"])
    print_result("已评分", stats["scored_posts"])
    print_result("未评分", stats["unscored_posts"])
    print_result("整体均分", stats["avg_score"])
    print()
    print_result("正面帖数", stats["positive_count"])
    print_result("负面帖数", stats["negative_count"])
    print_result("中性帖数", stats["neutral_count"])
    print()
    print_result("每日汇总记录", stats["daily_records"])
    print_result("数据日期范围", stats["date_range"])

    press_enter()


def func_recompute_daily():
    """功能8: 重新计算每日汇总"""
    print_stage("重新计算每日评分汇总")
    print()

    daily_data = visualizer.aggregate_daily_scores()
    if daily_data:
        print(f"\n  共生成 {len(daily_data)} 天的汇总数据")
        print()
        print(f"  {'日期':<14} {'均分':<8} {'帖子数':<8}")
        print("  " + "-" * 32)
        for d in daily_data:
            print(f"  {d['date']:<14} {d['avg_score']:<8} {d['post_count']:<8}")
    else:
        print("  没有数据可汇总")

    press_enter()


# ============================================================
# 主程序入口
# ============================================================

def main():
    """主程序入口"""
    # 初始化数据库
    db.init_db()

    while True:
        print_header()
        print_menu()

        choice = safe_input("  请选择功能 [0-8]: ")

        if choice == "1":
            func_scrape_list()
        elif choice == "2":
            func_scrape_details()
        elif choice == "3":
            func_analyze()
        elif choice == "4":
            func_auto()
        elif choice == "5":
            func_visualize()
        elif choice == "6":
            func_browse()
        elif choice == "7":
            func_stats()
        elif choice == "8":
            func_recompute_daily()
        elif choice == "0":
            print()
            print("  感谢使用! 再见.")
            print()
            break
        else:
            print(f"\n  无效选择: {choice}")
            time.sleep(1)

        if choice != "0":
            press_enter()


if __name__ == "__main__":
    main()
