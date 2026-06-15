# BenchHub

个人 AI 论文实验数据管理工具 — 上传 PDF，自动抽取实验数据，构建私有 SOTA 排行榜。

**GitHub**: [DemoStoneG/BenchHub](https://github.com/DemoStoneG/BenchHub)

详见 [BenchHub.md](./BenchHub.md) | PPT 大纲: [docs/PPT_OUTLINE.md](./docs/PPT_OUTLINE.md)

---

## 功能

- **Docling 表格提取**：Docling (TableFormer) 自动识别 PDF 表格结构，含 colspan/rowspan、表头语义分类、段标题检测、子行拆分
- **LLM 智能抽取**：逐表调用 LLM（MiniMax M2，可替换）抽取 `(Benchmark, Model, Dataset, Metric, Value)` 五元组 + 自动表格分类 + 打标签
- **全自动 Pipeline**：上传 PDF → 表格提取 → LLM 逐表抽取 → Benchmark/Dataset 归一化 → 入库，无需任何手动操作
- **SOTA 排行榜**：按 Benchmark 分组，跨论文自动汇聚模型排名，对标 Wizwand SOTA Leaderboard
- **项目隔离**：Session 维度独立管理论文与排行榜，互不干扰
- **客户端排序**：排行榜页 Alpine.js 渲染，点击列头即时排序，无页面刷新
- **非实验表过滤**：LLM 自动识别非数据表（数据集统计等）并折叠标注原因
- **数据归一化**：Benchmark 别名映射 + Dataset 全变体合并（EPIC-KITCHENS-* 等 20+ 变体归一）

## 技术栈

| 组件 | 选型 |
|:---|:---|
| 后端框架 | Django 4.2 |
| 数据库 | SQLite |
| PDF 表格提取 | Docling (TableFormer) + PyMuPDF（子行拆分） |
| LLM | MiniMax M2（`llm_service.py` 可替换为 OpenAI/Anthropic） |
| 前端 | Tailwind CSS + Alpine.js + pdf.js + markdown-it（全部 CDN，零构建） |
| 部署 | `setup.sh` 一键安装 / `start.sh` 手动启动 |

## 环境要求

- Python 3.10+
- 2 GB 内存（Docling 模型加载）
- 可选：NVIDIA GPU（加速表格提取）

## 快速开始

### 新机器一键安装

```bash
git clone https://github.com/DemoStoneG/BenchHub.git
cd BenchHub
cp .env.example .env         # 编辑 .env 填入 MiniMax API Key
bash setup.sh                # 自动安装依赖 + 初始化数据库
bash start.sh                # 启动服务器
```

浏览器打开 `http://localhost:8000`。

### 手动安装

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### 配置 LLM

**方式 1 — 环境变量（推荐）**：

```bash
export MINIMAX_API_KEY='sk-cp-your-key'
export MINIMAX_API_ENDPOINT='https://api.minimaxi.com/v1/text/chatcompletion_v2'
```

或在 `~/.bashrc` 中永久写入：

```bash
echo "export MINIMAX_API_KEY='sk-cp-your-key'" >> ~/.bashrc
source ~/.bashrc
```

**方式 2 — `.env` 文件**：

```bash
cp .env.example .env
# 编辑 .env，填入真实 Key
# 此文件被 .gitignore 保护，不会提交到 GitHub
```

换 OpenAI / Anthropic 需编辑 `services/llm_service.py` 的 `_call_llm` 方法。

## 使用流程

1. **创建项目**：首页 → "+ 新建项目"
2. **上传论文**：项目页 → "+ 上传论文" → 选 PDF → **自动启动全流程**
3. **等待解析**：状态栏显示进度（提取表格 → LLM 抽取 → 完成）
4. **查看排行榜**：项目页 → "🏆 排行榜" → 按 Benchmark 分组 → 点击列头排序
5. **预览表格**：`/articles/<id>/` 查看提取的 HTML 表格

## 部署

### 开发 + 生产双实例（同机隔离）

```bash
# 开发环境（写代码用）
cd ~/BenchHub && bash start.sh 8000

# 生产环境（日常用，数据库独立）
# 先克隆一份
git clone ~/BenchHub ~/benchhub-app
cd ~/benchhub-app && bash start.sh 9000
```

两个实例共享 conda 环境，数据库完全隔离。

### 生产部署

`benchhub/settings.py`：

```python
DEBUG = False
ALLOWED_HOSTS = ['your-domain.com']
SECRET_KEY = '<new-random-key>'
```

建议配合 nginx 反向代理 + supervisor/systemd 进程守护。

> ⚠ 生产环境禁止使用 `runserver`，换 `gunicorn` 或 `uWSGI`。

## 目录结构

```
BenchHub/
├── benchhub/              # Django 工程配置
│   └── settings.py        # 含 LLM 配置（读环境变量）
├── papers/                # 业务 app
│   ├── models.py          # Session / Paper / ExperimentRecord / TableChunk
│   ├── views.py           # 项目/论文/排行榜视图
│   ├── urls.py            # 路由（18 条）
│   ├── tasks.py           # 异步 pipeline（表格提取 + LLM 抽取）
│   ├── admin.py           # Django Admin 注册
│   └── templatetags/      # 自定义过滤器
├── services/              # 核心引擎（仅 2 个文件）
│   ├── docling_service.py # Docling 表格提取 + 子行拆分（~370 行）
│   └── llm_service.py     # LLM 抽取 + 名称归一化（~380 行）
├── templates/             # HTML 模板
│   ├── base.html          # 基础布局 + CDN 依赖
│   └── papers/
│       ├── leaderboard_list.html    # 排行榜卡片列表
│       ├── leaderboard_detail.html  # 排名表（Alpine.js 客户端排序）
│       ├── review.html             # 论文表格预览（可折叠）
│       ├── session_detail.html     # 项目详情
│       └── ...
├── docs/
│   └── PPT_OUTLINE.md     # PPT 大纲（21 slides）
├── media/                 # 上传的 PDF（不提交 Git）
├── .env.example           # 环境变量模板
├── requirements.txt       # Python 依赖
├── setup.sh               # 一键安装脚本
├── start.sh               # 启动脚本
├── BenchHub.md            # 完整项目文档
└── README.md              # 本文件
```

## 异步任务

`subprocess.Popen` 启动独立子进程：

```bash
python papers/tasks.py <paper_id>           # 完整解析（表格提取 + LLM）
python papers/tasks.py <paper_id> --no-llm  # 仅表格提取
```
