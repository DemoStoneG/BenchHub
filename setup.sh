#!/usr/bin/env bash
# BenchHub 一键安装脚本
# 用法: bash setup.sh [目标目录，默认 ~/benchhub-app]

set -e

APP_DIR="${1:-$HOME/benchhub-app}"

echo "========================================"
echo "  BenchHub 安装脚本"
echo "  目标目录: $APP_DIR"
echo "========================================"
echo ""

# 1. 检查 Python
echo ">>> 检查 Python 版本..."
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "错误: 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi
PY_VER=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
echo "    找到 $PYTHON ($PY_VER)"

# 2. 克隆或更新项目
if [ -d "$APP_DIR" ]; then
    echo ""
    echo ">>> 目标目录已存在，执行 git pull..."
    cd "$APP_DIR"
    git pull
else
    echo ""
    echo ">>> 克隆项目..."
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    REPO_URL="$(cd "$SCRIPT_DIR" && git remote get-url origin 2>/dev/null || echo '')"
    if [ -z "$REPO_URL" ]; then
        REPO_URL="$SCRIPT_DIR"
    fi
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. 检查虚拟环境
if [ ! -d "venv" ]; then
    echo ""
    echo ">>> 创建虚拟环境..."
    $PYTHON -m venv venv
fi
source venv/bin/activate

# 4. 安装依赖
echo ""
echo ">>> 安装 Python 依赖..."
pip install --upgrade pip -q
pip install -r requirements.txt

# 5. 数据库迁移
echo ""
echo ">>> 初始化数据库..."
python manage.py migrate --noinput

# 6. 配置提示
echo ""
echo "========================================"
echo "  安装完成！"
echo ""
echo "  下一步:"
echo ""
echo "  1. 配置 LLM API Key:"
echo "     编辑 $APP_DIR/benchhub/settings.py"
echo "     修改 MINIMAX_API_KEY = '你的key'"
echo ""
echo "  2. 启动:"
echo "     cd $APP_DIR"
echo "     source venv/bin/activate"
echo "     python manage.py runserver 0.0.0.0:8000"
echo ""
echo "  3. 打开浏览器: http://localhost:8000"
echo "========================================"
