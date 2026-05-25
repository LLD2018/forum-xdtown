#!/bin/bash
# ============================================================
#  论坛舆情分析 - 每日自动化脚本
#  每天凌晨5点执行：爬取 → 评分 → 生成报告 → 推送到GitHub
#  支持代理检测、自动重启、重试机制
# ============================================================

# --- 配置 ---
PROJECT_DIR="/home/ubuntu/project/forum-xdtown"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_$(date +%Y%m%d).log"
MAX_RETRIES=3
RETRY_DELAY=60          # 每次爬取重试间隔（秒）
PROXY_RESTART_WAIT=5    # 代理重启后等待时间（秒）
GITHUB_TOKEN_FILE="$PROJECT_DIR/.github_token"
PROXY_SERVICE="mihomo"
PROXY_HOST="127.0.0.1"
PROXY_PORT="7890"

# --- 初始化 ---
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================================"
echo "  论坛舆情分析 - 每日自动任务"
echo "  开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

cd "$PROJECT_DIR"

# ============================================================
#  代理检测与自动修复
# ============================================================

check_proxy() {
    # 检测代理是否可用，返回 0=可用 1=不可用
    local status_code
    status_code=$(curl -s -o /dev/null -w "%{http_code}" \
        --connect-timeout 5 --max-time 10 \
        --proxy "http://${PROXY_HOST}:${PROXY_PORT}" \
        "https://www.baidu.com" 2>/dev/null)
    if [ "$status_code" = "200" ]; then
        return 0
    else
        return 1
    fi
}

restart_proxy() {
    # 重启代理服务并等待就绪
    echo "  → 重启代理服务 ${PROXY_SERVICE}..."
    sudo systemctl restart "${PROXY_SERVICE}" 2>&1 || {
        echo "  ✗ 代理服务重启失败"
        return 1
    }
    sleep "${PROXY_RESTART_WAIT}"

    if check_proxy; then
        echo "  ✓ 代理已恢复正常"
        return 0
    else
        echo "  ✗ 代理重启后仍然不可用"
        return 1
    fi
}

ensure_proxy() {
    # 确保代理可用，不可用时自动重启，返回 0=成功 1=失败
    echo "[代理检测] 检测代理 ${PROXY_HOST}:${PROXY_PORT}..."

    if check_proxy; then
        echo "  ✓ 代理连接正常"
        return 0
    fi

    echo "  ⚠ 代理不可用，尝试重启..."

    for i in 1 2 3; do
        echo "  [尝试 $i/3] 重启代理服务..."
        if restart_proxy; then
            return 0
        fi
        if [ $i -lt 3 ]; then
            sleep 10
        fi
    done

    echo "  ✗ 代理修复失败（已尝试3次），放弃本次任务"
    return 1
}

# ============================================================
#  核心流程
# ============================================================

# --- 初始代理检测 ---
if ! ensure_proxy; then
    echo ""
    echo "============================================================"
    echo "  代理不可用，任务终止"
    echo "  结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    exit 1
fi

echo ""

# --- 步骤1: 爬取+评分 (带重试) ---
echo "[步骤1] 爬取帖子列表 + 详情 + AI评分 (近5天)"
echo "  最大重试次数: $MAX_RETRIES"
echo ""

SUCCESS=false
for i in $(seq 1 $MAX_RETRIES); do
    echo "--- 第 $i/$MAX_RETRIES 次尝试 ---"
    echo "  开始时间: $(date '+%H:%M:%S')"

    # 每次尝试前检测代理
    if ! ensure_proxy; then
        echo "  代理不可用，跳过本次尝试"
        if [ $i -lt $MAX_RETRIES ]; then
            sleep $RETRY_DELAY
        fi
        continue
    fi

    if python3 main.py auto --last-5-days; then
        echo ""
        echo "  ✓ 爬取+评分成功!"
        SUCCESS=true
        break
    fi

    echo ""
    if [ $i -lt $MAX_RETRIES ]; then
        echo "  ✗ 第 $i 次失败，${RETRY_DELAY}秒后重试..."
        sleep $RETRY_DELAY
        echo ""
    else
        echo "  ✗ 已达最大重试次数 ($MAX_RETRIES)，爬取阶段失败"
    fi
done

if [ "$SUCCESS" = false ]; then
    echo ""
    echo "============================================================"
    echo "  爬取阶段最终失败，退出"
    echo "  结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    exit 1
fi

# --- 步骤2: 生成可视化网页 ---
echo ""
echo "[步骤2] 生成可视化网页"
python3 main.py visualize

# --- 步骤3: 复制到 docs/ (GitHub Pages) ---
echo ""
echo "[步骤3] 复制 HTML 到 docs/ 目录"
cp -f output/visualization.html docs/index.html
echo "  ✓ 已复制 output/visualization.html → docs/index.html"

# --- 步骤4: Git 提交并推送 ---
echo ""
echo "[步骤4] 推送到 GitHub"

# 推送前检测代理
ensure_proxy || {
    echo "  ✗ 代理不可用，无法推送"
    exit 1
}

# 配置 git 用户
if ! git config user.name >/dev/null 2>&1; then
    git config user.name "forum-bot"
fi
if ! git config user.email >/dev/null 2>&1; then
    git config user.email "forum-bot@xdtown.local"
fi

# 使用 token 认证
TOKEN=""
if [ -f "$GITHUB_TOKEN_FILE" ]; then
    TOKEN=$(cat "$GITHUB_TOKEN_FILE" | tr -d '\n')
    git remote set-url origin "https://${TOKEN}@github.com/as167888/forum-xdtown.git"
fi

# 拉取远程最新代码
echo "  拉取远程最新代码..."
git pull origin master --rebase || {
    echo "  ⚠ git pull 失败，继续尝试推送"
}

# 暂存文件
git add data/forum.db docs/index.html output/visualization.html

# 检查是否有变更
if git diff --cached --quiet; then
    echo "  无新增数据，跳过提交和推送"
else
    COMMIT_MSG="chore: 每日自动更新 $(date '+%Y-%m-%d')"
    git commit -m "$COMMIT_MSG"
    echo "  ✓ 提交: $COMMIT_MSG"

    git push origin master
    echo "  ✓ 推送成功"
fi

# 恢复 remote URL
if [ -n "$TOKEN" ]; then
    git remote set-url origin "https://github.com/as167888/forum-xdtown.git"
fi

# --- 完成 ---
echo ""
echo "============================================================"
echo "  每日任务完成!"
echo "  结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  GitHub Pages: https://as167888.github.io/forum-xdtown/"
echo "============================================================"
