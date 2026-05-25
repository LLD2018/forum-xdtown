"""
============================================================
  TapTap论坛爬虫 & 舆情分析系统
  游戏: 心动小镇 (App ID: 45213)
============================================================

主程序 - 支持交互式菜单和命令行参数化运行
"""
import argparse
import os
import sys
import time
import shutil
import subprocess
import webbrowser
from datetime import datetime, date, timedelta

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
    else:
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
        ("4", "一键全流程", "列表→详情→评分→可视化 全自动执行"),
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


def parse_date_arg(date_str):
    """将 YYYY-MM-DD 字符串转为 date 对象"""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


# ============================================================
# 功能模块（支持参数化调用 + 交互式调用）
# ============================================================

def select_date_range(interactive=True, start_date=None, end_date=None,
                       last_days=None):
    """
    日期范围选择
    interactive=True 时显示菜单让用户选择
    interactive=False 时直接使用传入参数
    返回: (start_date, end_date, cancelled)
    """
    if not interactive:
        if last_days:
            today = date.today()
            return today - timedelta(days=last_days), today, False
        return start_date, end_date, False

    # 交互式菜单
    print()
    print("  日期范围选择:")
    print("  " + "-" * 40)
    print("  [1] 不限制日期 (爬取所有帖子)")
    print("  [2] 爬取最近5天")
    print("  [3] 自定义日期范围 (YYYY-MM-DD)")
    print()

    choice = safe_input("  请选择 [1-3] (默认1): ") or "1"

    if choice == "2":
        today = date.today()
        start = today - timedelta(days=5)
        print(f"\n  日期范围: {start} ~ {today} (近5天)")
        return start, today, False

    elif choice == "3":
        print()
        start_str = safe_input("  起始日期 (YYYY-MM-DD, 如 2025-01-01): ")
        end_str = safe_input("  结束日期 (YYYY-MM-DD, 如 2025-12-31, 留空=今天): ")
        start_date = None
        end_date = None
        try:
            if start_str:
                start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            if end_str:
                end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
            else:
                end_date = date.today()
        except ValueError:
            print("  日期格式错误，请使用 YYYY-MM-DD 格式")
            return None, None, True

        if start_date and end_date and start_date > end_date:
            print("  起始日期不能晚于结束日期")
            return None, None, True

        print(f"\n  日期范围: {start_date or '不限'} ~ {end_date or '不限'}")
        return start_date, end_date, False

    else:
        return None, None, False


def func_scrape_list(interactive=True, max_posts=None, start_date=None,
                      end_date=None, last_days=None):
    """功能1: 爬取帖子列表（通过TapTap API，游标分页）"""
    print_stage("阶段一: 爬取帖子列表 (API方式)")
    print()
    print("  通过TapTap内部API获取帖子列表 (游标分页)")
    print(f"  API: {scraper.FEED_API}")
    print(f"  Group ID: {scraper.GROUP_ID}")

    start_date, end_date, cancelled = select_date_range(
        interactive=interactive, start_date=start_date,
        end_date=end_date, last_days=last_days
    )
    if cancelled:
        return

    if interactive:
        print()
        try:
            limit_str = safe_input("  最多爬取帖子数 (默认1000, 输入0=全部): ")
            max_posts = int(limit_str) if limit_str else 1000
        except ValueError:
            print("  请输入有效数字")
            return
    else:
        if max_posts is None:
            max_posts = 1000

    if max_posts == 0:
        max_posts = None

    print(f"\n  最多爬取: {max_posts or '全部'} 条帖子")
    print(f"  请求间隔: {REQUEST_DELAY} 秒")
    if start_date or end_date:
        print(f"  日期范围: {start_date or '不限'} ~ {end_date or '不限'}")

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
        callback=progress_callback,
        start_date=start_date,
        end_date=end_date
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


def func_scrape_details(interactive=True, limit=None):
    """功能2: 爬取帖子详情"""
    print_stage("阶段二: 爬取帖子详情页")

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM posts WHERE content IS NULL OR content = ''")
    pending = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not pending:
        all_posts = db.get_all_posts()
        pending = [p for p in all_posts if not p.get("content")]
        if not pending:
            print("\n  所有帖子已有详情数据，无需爬取")
            print("  提示: 请先执行 [功能1: 爬取帖子列表] 获取帖子链接")
            return

    print(f"\n  待爬取详情的帖子: {len(pending)} 个")
    print(f"  请求间隔: {REQUEST_DELAY} 秒")

    if interactive:
        try:
            limit_str = safe_input("\n  每次爬取数量 (默认全部, 输入0=全部): ")
            limit = int(limit_str) if limit_str else 0
        except ValueError:
            limit = 0

    if limit and limit > 0:
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


def func_analyze(interactive=True, limit=None):
    """功能3: AI情感评分"""
    print_stage("阶段三: DeepSeek AI 情感评分")
    print()

    unscored = db.get_unscored_posts()
    if not unscored:
        print("  所有帖子已完成评分")
        return

    print(f"  待评分帖子: {len(unscored)} 个")
    print(f"  使用模型: {analyzer.DEEPSEEK_MODEL}")

    if interactive:
        try:
            limit_str = safe_input("\n  每次评分数量 (默认全部, 0=全部): ")
            limit = int(limit_str) if limit_str else 0
        except ValueError:
            limit = 0

    if limit and limit > 0:
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


def func_auto(interactive=True, max_posts=None, start_date=None,
               end_date=None, last_days=None):
    """功能4: 一键全流程"""
    print_stage("一键全流程: 列表(API) → 详情 → 评分 → 可视化")
    print()

    start_date, end_date, cancelled = select_date_range(
        interactive=interactive, start_date=start_date,
        end_date=end_date, last_days=last_days
    )
    if cancelled:
        return

    if interactive:
        print()
        try:
            limit_str = safe_input("  最多爬取帖子数 (默认500, 输入0=全部): ")
            max_posts = int(limit_str) if limit_str else 500
        except ValueError:
            print("  请输入有效数字")
            return
    else:
        if max_posts is None:
            max_posts = 500

    if max_posts == 0:
        max_posts = None

    print()
    session = scraper.create_session()
    client = analyzer.create_client()

    # === 步骤1: 爬取列表 (API) ===
    print_stage("步骤1/3: 爬取帖子列表 (API)")
    posts = scraper.scrape_list_via_api(
        session, max_posts=max_posts,
        start_date=start_date, end_date=end_date
    )
    print(f"  新增帖子: {len(posts)} 个")

    # === 步骤2: 爬取详情 (补充富文本) ===
    print_stage("步骤2/3: 爬取帖子详情 (补充内容)")
    scraper.scrape_all_details(session, posts if posts else None)

    # === 步骤3: AI评分 ===
    print_stage("步骤3/4: AI情感评分")
    unscored = db.get_unscored_posts()
    if unscored:
        analyzer.analyze_all_unscored(client, delay=1)
    else:
        print("  没有待评分的帖子")

    # === 步骤4: 生成可视化 ===
    print_stage("步骤4/4: 生成可视化网页")
    path = visualizer.generate_visualization_html()
    if path:
        print(f"  可视化网页: {path}")

    session.close()

    # 推送到 GitHub
    push_to_github()

    print()
    print_separator("=", 50)
    print("  全流程完成!")
    print_separator("=", 50)


def func_visualize(interactive=True, open_browser=None):
    """功能5: 生成可视化网页"""
    print_stage("生成可视化网页")
    print()

    path = visualizer.generate_visualization_html()

    if path:
        print()
        print(f"  可视化网页: {path}")

        should_open = open_browser
        if interactive and should_open is None:
            try:
                open_cmd = safe_input("  是否在浏览器中打开? (y/n, 默认y): ")
                should_open = open_cmd.lower() != "n"
            except Exception:
                should_open = False

        if should_open:
            try:
                webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
                print("  已在浏览器中打开")
            except Exception:
                print("  请手动打开上述文件")

        # 推送到 GitHub
        push_to_github()


def push_to_github():
    """将可视化网页和数据库推送到 GitHub"""
    print_stage("推送到 GitHub")
    print()

    project_dir = os.path.dirname(os.path.abspath(__file__))
    docs_index = os.path.join(project_dir, "docs", "index.html")
    viz_path = os.path.join(project_dir, "output", "visualization.html")

    # 复制可视化网页到 docs/ 目录
    os.makedirs(os.path.dirname(docs_index), exist_ok=True)
    shutil.copy2(viz_path, docs_index)
    print(f"  已复制: output/visualization.html → docs/index.html")

    # git 操作
    files_to_add = ["data/forum.db", "docs/index.html", "output/visualization.html"]

    for f in files_to_add:
        result = subprocess.run(
            ["git", "add", f], cwd=project_dir,
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            print(f"  git add {f} 失败: {result.stderr.strip()}")

    # 检查是否有变更
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=project_dir
    )
    if diff_result.returncode == 0:
        print("  无新增变更，跳过提交")
        return

    # 提交
    commit_msg = f"chore: 自动更新可视化报告 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    result = subprocess.run(
        ["git", "commit", "-m", commit_msg], cwd=project_dir,
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        print(f"  git commit 失败: {result.stderr.strip()}")
        return
    print(f"  ✓ 提交: {commit_msg}")

    # 推送
    result = subprocess.run(
        ["git", "push"], cwd=project_dir,
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode == 0:
        print("  ✓ 推送成功")
    else:
        print(f"  git push 失败: {result.stderr.strip()}")


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

    if __name__ != "__main__":
        return  # CLI模式不等待回车


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

    if __name__ != "__main__":
        return


# ============================================================
# 命令行参数解析
# ============================================================

def build_parser():
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="TapTap论坛爬虫 & 舆情分析系统 - 心动小镇",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py scrape-list --last-5-days
  python main.py scrape-list --start-date 2025-05-01 --end-date 2025-05-25 --max-posts 500
  python main.py scrape-details --limit 100
  python main.py analyze --limit 50
  python main.py auto --last-5-days
  python main.py auto --start-date 2025-01-01 --end-date 2025-06-30 --max-posts 1000
  python main.py visualize --open-browser
  python main.py stats
  python main.py recompute-daily
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ---- scrape-list ----
    p_list = subparsers.add_parser("scrape-list", help="爬取帖子列表")
    p_list.add_argument("--max-posts", type=int, default=None,
                         help="最多爬取帖子数 (默认1000, 0=全部)")
    p_list.add_argument("--start-date", type=str, default=None,
                         help="起始日期 YYYY-MM-DD")
    p_list.add_argument("--end-date", type=str, default=None,
                         help="结束日期 YYYY-MM-DD")
    p_list.add_argument("--last-5-days", action="store_true",
                         help="爬取最近5天的帖子（覆盖--start-date/--end-date）")

    # ---- scrape-details ----
    p_details = subparsers.add_parser("scrape-details", help="爬取帖子详情")
    p_details.add_argument("--limit", type=int, default=None,
                            help="最多爬取数量 (默认全部)")

    # ---- analyze ----
    p_analyze = subparsers.add_parser("analyze", help="AI情感评分")
    p_analyze.add_argument("--limit", type=int, default=None,
                            help="最多评分数量 (默认全部)")

    # ---- auto ----
    p_auto = subparsers.add_parser("auto", help="一键全流程 (列表→详情→评分→可视化)")
    p_auto.add_argument("--max-posts", type=int, default=None,
                         help="最多爬取帖子数 (默认500, 0=全部)")
    p_auto.add_argument("--start-date", type=str, default=None,
                         help="起始日期 YYYY-MM-DD")
    p_auto.add_argument("--end-date", type=str, default=None,
                         help="结束日期 YYYY-MM-DD")
    p_auto.add_argument("--last-5-days", action="store_true",
                         help="爬取最近5天的帖子")

    # ---- visualize ----
    p_viz = subparsers.add_parser("visualize", help="生成可视化网页")
    p_viz.add_argument("--open-browser", action="store_true",
                        help="生成后自动在浏览器中打开")

    # ---- stats ----
    subparsers.add_parser("stats", help="显示数据库统计信息")

    # ---- recompute-daily ----
    subparsers.add_parser("recompute-daily", help="重新计算每日评分汇总")

    return parser


def run_cli(args):
    """根据解析后的参数运行对应的功能"""
    db.init_db()

    if args.command == "scrape-list":
        start_date = None
        end_date = None
        last_days = None

        if args.last_5_days:
            last_days = 5
        else:
            if args.start_date:
                start_date = parse_date_arg(args.start_date)
            if args.end_date:
                end_date = parse_date_arg(args.end_date)

        func_scrape_list(
            interactive=False, max_posts=args.max_posts,
            start_date=start_date, end_date=end_date,
            last_days=last_days
        )

    elif args.command == "scrape-details":
        func_scrape_details(interactive=False, limit=args.limit)

    elif args.command == "analyze":
        func_analyze(interactive=False, limit=args.limit)

    elif args.command == "auto":
        start_date = None
        end_date = None
        last_days = None

        if args.last_5_days:
            last_days = 5
        else:
            if args.start_date:
                start_date = parse_date_arg(args.start_date)
            if args.end_date:
                end_date = parse_date_arg(args.end_date)

        func_auto(
            interactive=False, max_posts=args.max_posts,
            start_date=start_date, end_date=end_date,
            last_days=last_days
        )

    elif args.command == "visualize":
        func_visualize(interactive=False, open_browser=args.open_browser)

    elif args.command == "stats":
        func_stats()

    elif args.command == "recompute-daily":
        func_recompute_daily()


# ============================================================
# 主程序入口
# ============================================================

def main():
    """主程序入口 - 无参数时启动交互菜单，有参数时执行命令行模式"""
    db.init_db()

    # 检查是否有命令行参数（排除脚本名本身）
    if len(sys.argv) > 1:
        parser = build_parser()
        args = parser.parse_args()

        if args.command is None:
            parser.print_help()
            return

        run_cli(args)
        return

    # 交互式菜单模式
    while True:
        print_header()
        print_menu()

        choice = safe_input("  请选择功能 [0-8]: ")

        if choice == "1":
            func_scrape_list(interactive=True)
        elif choice == "2":
            func_scrape_details(interactive=True)
        elif choice == "3":
            func_analyze(interactive=True)
        elif choice == "4":
            func_auto(interactive=True)
        elif choice == "5":
            func_visualize(interactive=True)
        elif choice == "6":
            func_browse()
        elif choice == "7":
            func_stats()
            press_enter()
        elif choice == "8":
            func_recompute_daily()
            press_enter()
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
