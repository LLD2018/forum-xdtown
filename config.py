"""
TapTap论坛爬虫配置文件 - 心动小镇
"""
import os
from pathlib import Path

# 加载 .env 文件（如果存在）—— 优先级低于系统环境变量
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _key = _key.strip()
                _val = _val.strip()
                if _key not in os.environ:
                    os.environ[_key] = _val

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

# TapTap 论坛配置
APP_ID = "45213"
BASE_URL = "https://www.taptap.cn"
FORUM_LIST_URL = f"{BASE_URL}/app/{APP_ID}/topic?sort=created"
MOMENT_URL = f"{BASE_URL}/moment"

# 数据库配置
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "forum.db")

# 可视化输出
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
VISUALIZATION_PATH = os.path.join(OUTPUT_DIR, "visualization.html")

# 爬虫配置
REQUEST_DELAY = 2  # 请求间隔（秒）
MAX_PAGES = 1000  # 最大爬取页数
START_PAGE = 1  # 起始页码
REQUEST_TIMEOUT = 30  # 请求超时（秒）
MAX_RETRIES = 3  # 最大重试次数

# HTTP 请求头
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.taptap.cn/",
}
