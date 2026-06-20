# BenchHub

个人 AI 论文实验数据管理工具 — 上传 PDF，自动抽取实验数据，构建私有 SOTA 排行榜。

**GitHub**: [DemoStoneG/BenchHub](https://github.com/DemoStoneG/BenchHub)

详见 [BenchHub.md](./BenchHub.md)（含技术背景、需求分析、数据流、功能清单、技术难点、部署说明）

---

## 功能

### 表格提取

把论文 PDF 里的实验结果表格还原为网页表格。支持多行表头、跨列跨行（colspan/rowspan）、段标题（表格里的 "UDA" / "DG" 横条）。PDF 中无横线分隔的子行自动检测拆分。

### 实验数据自动抽取

上传后无需任何手动操作，后台用大模型逐表分析，把表格数字变成结构化数据：

| 字段 | 含义 | 例子 |
|:---|:---|:---|
| Benchmark | 任务名 | Action Recognition / UDA / DG |
| Model | 方法名 | Source Only / SeqDG / RNA |
| Dataset | 数据集 | EPIC-KITCHENS / EGTEA |
| Metric | 指标名 | Verb Acc / mAP / nDCG |
| Value | 数值 | 46.7 / 55.5 |

一次 API 调用同时完成数据抽取、表格分类（实验对比 vs 非实验表）、打标签（数据集名 + 任务名）。

### 表格自动分类

大模型自动判断每张表是否包含可排名数据。非实验表（数据集统计、参数列表等）默认折叠，打上 "⚠ 数据集统计信息" 标签。可手动展开查看，但不参与排行榜。

### 名称归一化

同一数据集，大模型可能写出不同名字。规则引擎统一合并：

```
EPIC-KITCHENS-100-Test-Verb  →  EPIC-KITCHENS
EPICKITCHENS-100             →  EPIC-KITCHENS
EK100                        →  EPIC-KITCHENS
CharadesEgo                  →  Charades-Ego
```

Benchmark 同理，"Action Classification" / "Action Recog." 统一为 "Action Recognition"。Session 2 从 24 组归并为 11 组。

### SOTA 排行榜

按项目维度，跨论文自动汇聚模型排名。每 Benchmark 一个卡片，点进去是多数据集排名表。前三名高亮 🥇🥈🥉。点击指标列头即时排序（升/降序切换），页面不刷新，当前排序列紫色加粗。论文链接点击跳转到对应表格位置。

每个排行榜详情页顶部有中文说明，不会面对 "DG" "UDA" 这类缩写一脸懵。

### 项目隔离

可创建多个项目，各自独立管理论文和排行榜：

| 项目 | 论文 | 用途 |
|:---|:---|:---|
| 动作识别 | DG/SeqDG | 领域泛化 + UDA 实验 |
| Ego Foundation Models | EgoVLP + EgoVideo | 第一人称视频理解 |
| Cross View | Semantic Alignment | 跨视角学习 |

---

## 快速开始

```bash
git clone https://github.com/DemoStoneG/BenchHub.git
cd BenchHub
cp .env.example .env             # 编辑 .env 填入 MiniMax API Key
bash setup.sh                    # 自动安装依赖 + 初始化数据库
bash start.sh                    # 启动 → http://localhost:8000
```

## 使用流程

1. **创建项目**：首页 → "+ 新建项目"
2. **上传论文**：项目页 → "+ 上传论文" → 选 PDF → 自动启动全流程
3. **等待解析**：进度条显示状态（提取表格 → LLM 抽取 → 完成），2-10 分钟
4. **查看结果**：完成后自动跳转论文页，可折叠浏览所有提取的表格
5. **排行榜**：项目页 → "🏆 排行榜" → 按 Benchmark 分组 → 点列头排序

**重新解析**：项目页每篇论文有 "重新解析" 按钮，点击后清空旧数据全流程重跑。

### 页面导航

| 页面 | URL | 用途 |
|:---|:---|:---|
| 首页 | `/` | 所有项目列表，可搜索 |
| 项目页 | `/projects/<id>/` | 论文列表 + 上传 + 排行榜入口 |
| 论文详情 | `/articles/<id>/` | 预览提取的表格，可折叠/展开 |
| 排行榜列表 | `/projects/<id>/leaderboards/` | 按 Benchmark 分组的卡片 |
| 排行榜详情 | 点卡片进入 | 多数据集排名表，点击列头排序 |
| 上传页 | `/projects/<id>/upload/` | 拖拽上传 PDF |

### 论文详情页

- 每张表一个卡片，标签区显示 📦 数据集 / 🎯 任务名 / `(N条)` 提取数量
- 点击标题栏可折叠/展开（▶ / － 切换）
- 黄色标题的卡片是**被过滤的非实验表**，不参与排行榜
- 折叠态只占一行，浏览 8 张表不费力

### 排行榜详情页

- 顶部紫色框是 Benchmark 的中文说明（已知任务硬编码，新任务 LLM 自动生成并缓存）
- 每个 📦 对应一个数据集，下面是其排名表
- 点击指标列头 → 排序；再点 → 升/降序切换
- 紫色数值是当前排序指标
- 最右列论文链接，点击跳转到对应表格位置
- 📥 **CSV 下载**：每个数据集表格可一键下载 CSV（UTF-8 BOM，Excel 兼容）
- 📋 **LaTeX 复制**：每个数据集表格可一键复制 LaTeX `\begin{table}...\end{table}` 源码

---

## 配置 LLM

**环境变量（推荐）**：

```bash
export MINIMAX_API_KEY='sk-cp-your-key'
echo "export MINIMAX_API_KEY='sk-cp-your-key'" >> ~/.bashrc
```

或复制 `.env.example` → `.env` 填入 Key。换 OpenAI / Anthropic 编辑 `services/llm_service.py`。

### Benchmark 自动说明

已知 Benchmark（如 UDA、DG）使用预定义中文描述。上传新论文引入新 Benchmark 时，系统自动调用 LLM 生成 1-2 句中文任务说明，并缓存到 `benchmark_descriptions.json`（不提交 Git）。无需手动维护。

---

## 技术栈

| 组件 | 选型 |
|:---|:---|
| 后端框架 | Django 4.2 |
| 数据库 | SQLite |
| PDF 表格提取 | Docling (TableFormer) + PyMuPDF（子行拆分） |
| LLM | MiniMax M2（可替换） |
| 前端 | Tailwind CSS + Alpine.js + pdf.js + markdown-it（全部 CDN） |
| 排行榜排序 | Alpine.js 客户端排序（无刷新） |

---

## 部署

### 单机运行

```bash
bash start.sh 8000
```

### 开发 + 日常双实例

同一台机器两个独立实例，共享环境、数据隔离：

```bash
# 日常使用（端口 9000，数据库独立）
git clone ~/BenchHub ~/benchhub-app
cd ~/benchhub-app && bash start.sh 9000

# 开发调试（端口 8000）
cd ~/BenchHub && bash start.sh 8000
```

### 生产环境

`benchhub/settings.py` 中 `DEBUG=False`，换 `gunicorn` / `uWSGI` + nginx 反向代理 + supervisor/systemd。

---

## 异步任务

解析任务通过 `subprocess.Popen` 启动独立子进程：

```bash
python papers/tasks.py <paper_id>           # 完整解析（表格 + LLM）
python papers/tasks.py <paper_id> --no-llm  # 仅表格提取
```

---

## 目录结构

```
BenchHub/
├── benchhub/              # Django 工程配置
│   └── settings.py        # LLM 配置（读环境变量，不硬编码）
├── papers/                # 业务 app
│   ├── models.py          # Session / Paper / ExperimentRecord / TableChunk
│   ├── views.py           # 项目/论文/排行榜视图
│   └── tasks.py           # 异步 pipeline（表格提取 + LLM 抽取）
├── services/              # 核心引擎（仅 2 个文件）
│   ├── docling_service.py # 表格提取 + 子行拆分（~370 行）
│   └── llm_service.py     # LLM 抽取 + 名称归一化（~380 行）
├── templates/             # HTML 模板
│   └── papers/
│       ├── leaderboard_list.html    # 排行榜卡片列表
│       ├── leaderboard_detail.html  # 排名表（Alpine.js 排序）
│       ├── review.html             # 论文表格预览（可折叠）
│       └── session_detail.html     # 项目详情
├── docs/
│   ├── PPT_OUTLINE.md     # PPT 大纲（21 slides）
│   └── USER_GUIDE.md      # 用户手册（本文件已合并，此文件保留存档）
├── .env.example           # 环境变量模板
├── requirements.txt       # Python 依赖
├── setup.sh               # 一键安装脚本
├── start.sh               # 启动脚本
├── BenchHub.md            # 完整项目文档
└── README.md              # 本文件
```

---

## 常见问题

**Q: 上传 PDF 后要等多久？**
A: 8 页论文约 2-5 分钟，20 页以上约 5-10 分钟。时间主要花在 LLM 逐表分析。

**Q: 为什么有些表格显示 "被过滤"？**
A: LLM 判断该表非实验对比表，自动折叠。可点开查看原始表格。

**Q: 排行榜数据不对怎么办？**
A: 到 Django Admin（`/admin/`）后台编辑 ExperimentRecord，或点"重新解析"重跑。

**Q: 能换 LLM 模型吗？**
A: 编辑 `services/llm_service.py` 的 `_call_llm` 方法，改 payload 结构和 endpoint 即可。
