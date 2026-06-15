# BenchHub

个人 AI 论文实验数据管理工具 — 上传 PDF，自动抽取实验数据，校对后一键生成对比表与 LaTeX 代码。

详见规格：[BenchHub.md](./BenchHub.md)

## 特性

- **Docling 表格提取**：Docling (TableFormer) 自动识别 PDF 表格结构，含 colspan/rowspan、表头语义分类、段标题检测
- **子行拆分**：自动检测并拆分 PDF 中无横线分隔的子行，渲染为独立 `<tr>`（虚线分隔 + rowspan 优化）
- **段标题识别**：TableFormer 模型推理自动识别 UDA / DG 等段标题行，渲染为紫色横条
- **LLM 智能抽取**：逐表喂 LLM 抽 `(Benchmark, Model, Dataset, Metric, Value)` 元组，带 5 次指数退避重试
- **项目分组**：在项目（Session）下组织论文；不同项目的论文与对比相互独立
- **人工校验**：上方 HTML 渲染表格预览，下方 record 编辑器，支持增删改 + 全部校验 + 指标合并
- **持久化表格**：表格提取结果自动存入数据库，上传/重试时自动执行，文章页直接加载无需手动触发
- **重试进度条**：重新解析时实时显示进度（提取中 → 调用 LLM → 完成），自动刷新
- **Benchmark 分组对比**：勾选论文后按 Benchmark 分块渲染横向对比表
- **LaTeX 一键导出**：按 Benchmark 分块生成 `\begin{tabular}` 代码，复制即用

## 技术栈

- **后端**：Django 4.2
- **数据库**：SQLite
- **PDF 表格提取**：Docling + TableFormer + PyMuPDF（子行拆分）
- **PDF 表格截图**：pdfplumber + pypdfium2 + Pillow
- **LLM**：MiniMax M2（可在 `benchhub/settings.py` 替换为 OpenAI/Anthropic）
- **前端**：Tailwind CSS (CDN) + Alpine.js (CDN) + pdf.js (CDN) + markdown-it (CDN)

## 环境要求

- Python 3.10+
- 依赖：见下方安装步骤

## 安装与运行

```bash
# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 安装依赖
pip install django pypdf requests
pip install docling                      # Docling 表格提取（主引擎）
pip install pymupdf                      # PyMuPDF（子行拆分 + caption 搜索）
pip install pdfplumber pypdfium2 Pillow  # 表格截图
pip install opencv-python-headless       # 图像处理依赖

# 3. 数据库迁移
python manage.py migrate

# 4. 启动开发服务器
python manage.py runserver
```

访问 http://127.0.0.1:8000/

## 配置 LLM

在 `benchhub/settings.py` 中配置：

```python
MINIMAX_API_KEY = 'your-api-key'
MINIMAX_API_ENDPOINT = 'https://api.minimaxi.com/v1/text/chatcompletion_v2'
```

换 OpenAI / Anthropic 需编辑 `services/llm_service.py` 的 `_call_llm` 方法，改 `payload` 结构和 endpoint。

## 使用流程

1. **创建项目**：首页点 "+ 新建项目"，填写项目名和描述
2. **上传论文**：项目页 `/projects/<id>/` 点 "+ 上传论文"，选 PDF 上传
3. **等待解析**：前端每 2 秒轮询状态，显示"提取文本 → 调用 LLM"进度
4. **校对数据**：`/articles/<id>/` 左侧 pdf.js 预览 PDF，右侧结构化表格 + record 编辑
   - 修改任意单元格自动保存
   - 点击"全部校验"批量标记
   - "合并指标"面板，把 `Accuracy` 和 `Acc` 等近义指标合并
5. **生成对比表**：`/projects/<id>/compare/` 勾选论文 → 按 Benchmark 分块渲染 → 复制 LaTeX

## 运行异步任务

解析任务通过 `subprocess.Popen` 启动独立子进程：

```bash
cd /path/to/BenchHub
python papers/tasks.py <paper_id>           # 完整解析
python papers/tasks.py <paper_id> --no-llm  # 仅做表格提取，不调 LLM
```

## 部署到生产

`benchhub/settings.py` 需修改：

```python
DEBUG = False
ALLOWED_HOSTS = ['your-domain.com']
SECRET_KEY = '<new-random-key>'
```

建议：
- 任务队列换 Celery / Django-Q2
- 静态文件用 nginx / whitenoise
- 进程管理用 supervisor / systemd

## 目录结构

```
benchhub/              # Django 工程配置
papers/                # 业务 app：models / views / urls / tasks / admin / migrations
services/              # 核心服务
  docling_service.py   # Docling 表格提取（主引擎）
  llm_service.py       # LLM 调用 + JSON 解析
  table_extractor.py   # PDF 表格截图
  latex_service.py     # LaTeX 生成
  md_parser.py         # pymupdf4llm 表格切分
  pdf_service.py       # pypdf 文本提取
  parser_service.py    # Markdown 表格规则解析
  marker_service.py    # Marker 封装（保留，不主用）
templates/             # HTML 模板
media/                 # 上传的 PDF + 表格截图
```
