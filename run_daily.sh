#!/bin/bash
# ============================================================
#  论坛舆情分析 - 每日自动化脚本
#  每天凌晨5点执行：爬取 → 评分 → 生成报告 → 推送到GitHub
# ============================================================
set -e

# --- 配置 ---
PROJECT_DIR="/home/ubuntu/project/forum-xdtown"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_$(date +%Y%m%d).log"
MAX_RETRIES=3
RETRY_DELAY=60  # 重试间隔（秒）
GITHUB_TOKEN_FILE="$PROJECT_DIR/.github_token"

# --- 初始化 ---
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================================"
echo "  论坛舆情分析 - 每日自动任务"
echo "  开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

cd "$PROJECT_DIR"

# --- 步骤1: 爬取+评分 (带重试) ---
echo "[步骤1] 爬取帖子列表 + 详情 + AI评分 (近5天)"
echo "  最大重试次数: $MAX_RETRIES"
echo ""

SUCCESS=false
for i in $(seq 1 $MAX_RETRIES); do
    echo "--- 第 $i/$MAX_RETRIES 次尝试 ---"
    echo "  开始时间: $(date '+%H:%M:%S')"

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

# 配置 git 用户（如果未设置）
if ! git config user.name >/dev/null 2>&1; then
    git config user.name "forum-bot"
fi
if ! git config user.email >/dev/null 2>&1; then
    git config user.email "forum-bot@xdtown.local"
fi

# 如果有 token 文件，使用 token 认证
TOKEN=""
if [ -f "$GITHUB_TOKEN_FILE" ]; then
    TOKEN=$(cat "$GITHUB_TOKEN_FILE" | tr -d '\n')
    REPO_URL="https://${TOKEN}@github.com/as167888/forum-xdtown.git"
    # 临时修改 remote URL 为带 token 的版本
    git remote set-url origin "$REPO_URL"
fi

# 先拉取远程最新代码，避免冲突
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

# 恢复 remote URL（如果有 token 的话）
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
