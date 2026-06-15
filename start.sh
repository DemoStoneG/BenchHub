#!/usr/bin/env bash
# BenchHub 启动脚本（开发用）
# 用法: bash start.sh [端口号，默认 8000]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-8000}"

# 激活 conda 环境（如果存在）
if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null || true
    conda activate benchhub 2>/dev/null || true
fi

# 如果 conda 不可用，检查本地 venv
if [ -z "$CONDA_DEFAULT_ENV" ] && [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

echo "=========================================="
echo "  BenchHub 启动中..."
echo "  http://localhost:$PORT"
echo "  Ctrl+C 停止"
echo "=========================================="
echo ""

cd "$SCRIPT_DIR"
python manage.py runserver 0.0.0.0:$PORT
