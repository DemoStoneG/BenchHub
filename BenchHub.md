# BenchHub — 个人 AI 论文实验数据管理工具

## 1. 产品定位

一个为研究人员/开发者设计的本地化工具。用户上传论文 PDF，系统自动抽取实验数据，按 Benchmark 分组构建排行榜，对标 [Wizwand SOTA Leaderboard](https://www.wizwand.com/sota/action-recognition-on-epic-kitchens-100-test) 的体验。

- **私有化**：数据存储在本地/私有服务器，不强制公开
- **自动化**：上传 PDF → 表格提取 → LLM 逐表抽取 → 排行榜汇聚，全自动
- **排名**：同一 Benchmark 下多篇论文的模型按指标排名，对标 Wizwand SOTA 体验

---

## 2. 当前实现状态（2026-06-15）

### 2.1 完整功能清单

| 模块 | 功能 | 状态 |
|:---|:---|:---|
| **项目 Session** | 多项目隔离，每个项目独立管理论文与排行榜 | ✅ |
| **PDF 上传** | 上传 PDF → 异步任务自动完成全部流程 | ✅ |
| **表格提取** | Docling TableFormer 识别 PDF 表格结构，含 colspan/rowspan、表头语义、段标题 | ✅ |
| **子行拆分** | PyMuPDF 词坐标 Y 聚类，检测 Word 行合并 → 拆为独立 `<tr>`，虚线分隔 | ✅ |
| **LLM 数据抽取** | 逐表调用 MiniMax M2，抽取 (Benchmark, Model, Dataset, Metric, Value) 元组 | ✅ |
| **表格分类** | LLM 自动判断 is_experimental，非实验表（数据集统计等）自动折叠并标注原因 | ✅ |
| **自动打标签** | 每张表标注 datasets + tasks 标签，显示在表格头部 | ✅ |
| **数据归一化** | Benchmark 名称归一化（别名映射 + 去掉 "on XXX" 后缀）+ Dataset 归一化（EPIC-KITCHENS 全变体合并） | ✅ |
| **表格预览** | PDF 表格渲染为 HTML 展示，可折叠，非实验表自动折叠 | ✅ |
| **排行榜列表** | 按项目分组，每个 Benchmark 一张卡片，显示模型数/数据集数/最高分 | ✅ |
| **排行榜详情** | 单个 Benchmark 下多数据集排名表，客户端 Alpine.js 排序（点击列头 升/降序），CSV/LaTeX 一键导出 | ✅ |
| **Benchmark 说明** | 每个排行榜顶部显示中文任务描述 | ✅ |
| **论文链接定位** | 排行榜中论文链接跳转到对应表格锚点（#tc-<id>） | ✅ |
| **CSV 导出** | 每个数据集排名表一键下载 CSV（UTF-8 BOM，Excel 兼容） | ✅ |
| **LaTeX 导出** | 每个数据集排名表一键复制 LaTeX 表格源码（自动转义特殊字符） | ✅ |
| **Benchmark 自动说明** | 已知任务用预定义描述，新 Benchmark 首次访问 LLM 自动生成中文说明并缓存 | ✅ |
| **项目页面入口** | 项目页顶部"🏆 排行榜"按钮 | ✅ |
| **Django Admin** | 后台可编辑 Session / Paper / ExperimentRecord | ✅ |
| **重新解析** | 项目页点"重新解析"→ 清空旧数据 → 表格提取 → LLM 抽取全自动 | ✅ |

### 2.2 核心数据流

```
上传 PDF
  ↓
Docling TableFormer 解析 → TableChunk（HTML 表格 + caption + 页码）
  ↓
LLM (MiniMax M2) 逐表提取
  ├─ records: [{benchmark, model, dataset, metric, value}, ...]
  ├─ tags: {datasets: [...], tasks: [...]}
  ├─ is_experimental: true/false
  └─ filter_reason: "数据集统计信息" / "非实验对比表格"
  ↓
归一化：benchmark 别名 + dataset 变体合并 + 噪声过滤
  ↓
ExperimentRecord 入库（关联 TableChunk + Paper）
  ↓
排行榜：按 (benchmark, dataset) 分组 → 按指标排名 → CSV/LaTeX 一键导出
```

### 2.3 已清理的废弃模块

| 旧模块 | 原因 |
|:---|:---|
| TableImage（PDF 表格截图） | Docling HTML 渲染完全替代 |
| compare.html + 对比视图 | 排行榜完全替代 |
| Article 页 records 编辑区 | 冗余信息，LLM 抽取质量已足够 |
| latex_service / pdf_service / table_extractor / marker_service / parser_service / md_parser / table_transformer_service / table_extraction_v2 | 旧提取方案，Docling 单一路线已稳定 |

---

## 3. 技术架构

| 组件 | 选型 | 说明 |
|:---|:---|:---|
| **后端框架** | Django 4.2 | 快速开发，内置 Admin |
| **数据库** | SQLite | 个人工具，单文件易备份 |
| **PDF 表格提取** | Docling (TableFormer) + PyMuPDF (子行拆分) | PubTables-1M 训练，96.75% TEDS |
| **LLM** | MiniMax M2（可在 `llm_service.py` 替换） | 逐表 JSON 抽取 + 表格分类 + Benchmark 自动说明 |
| **前端** | Tailwind CSS (CDN) + Alpine.js (CDN) + pdf.js (CDN) | 极简开发，无构建步骤 |
| **排行榜排序** | Alpine.js 客户端排序 | 点击列头即时排序，无页面刷新 |
| **数据导出** | 纯前端 JS 生成 CSV / LaTeX | Clipboard API + Blob download，不依赖后端 |

## 4. 目录结构

```
BenchHub.md            # 本文件
README.md              # 项目简介
benchmark_descriptions.json  # LLM 自动生成的 Benchmark 说明缓存（不提交 Git）
manage.py              # Django 入口
benchhub/              # Django 工程配置 (settings / urls / wsgi)
papers/                # 业务 app
  models.py            # Session / Paper / ExperimentRecord / TableChunk
  views.py             # 项目/论文/排行榜视图
  urls.py              # 路由（24 条，精确可控）
  tasks.py             # 异步解析 pipeline（表格提取 + LLM 抽取）
  admin.py             # Django Admin 注册
  templatetags/        # 自定义模板过滤器 (dict_key / score)
  migrations/          # 数据库迁移（含 0010 tags / 0011 清理 TableImage）
services/              # 核心引擎（仅 2 个文件）
  docling_service.py   # Docling TableFormer 表格提取 + 子行拆分（~370 行）
  llm_service.py       # LLM 逐表抽取 + benchmark/dataset 归一化（~380 行）
templates/             # 模板
  base.html            # 基础布局 + Tailwind/Alpine.js/markdown-it CDN
  papers/
    leaderboard_list.html      # 排行榜卡片列表
    leaderboard_detail.html    # 排行榜排名表（Alpine.js 客户端排序）
    review.html                # 论文表格预览（可折叠 + 过滤标记）
    session_detail.html        # 项目详情（论文列表 + 排行榜入口）
    upload.html                # PDF 上传
    ...                        # 项目增删改表单
media/                 # 上传的 PDF 文件
```

---

## 5. 重难点总结

### 5.1 PDF 表格结构识别

**难点**：学术论文表格结构复杂 — 多行表头、colspan/rowspan、段标题行（UDA/DG）、无横线分隔的子行。早期方案（Table Transformer 坐标映射 → 6 层变换，累积误差 10-20px；纯 PyMuPDF 词坐标聚类 → 阈值一刀切，子列混淆）均失败。

**方案演进**：V1-V4 经历 4 次推倒重来，最终 V5 采用 Docling TableFormer 原生结构化数据（`table_cells`，含 column_header / row_section / col_span / row_span 语义标记）直接遍历生成 HTML，搭配 PyMuPDF 词坐标 Y 聚类做子行拆分。

**验证**：3 篇论文 26 张表，0 误伤，0 重复。

### 5.2 子行拆分

**难点**：TableFormer 将 PDF 中无横线分隔的两个物理行（如 Method 列有 "Source Only" + "TBN-TRN" 两行）识别为一个逻辑行，导致 HTML 渲染时数据挤在同一 `<tr>` 中。

**方案**：在 cell bbox 内用 PyMuPDF `get_text("words")` 按 Y 坐标聚类（gap > 4pt → 新子行），同一行内 ≥70% 多数值 cell 呈现相同簇数时才认定子行。每个子行渲染为独立 `<tr>`，内容相同的 cell 用 `rowspan=n` 跨行去重。

### 5.3 LLM 表格语义分类

**难点**：论文中除了实验对比表，还有数据集统计表、消融实验说明表、参数量对比表等。需要自动识别哪些表可以构建排行榜。

**方案**：在 LLM prompt 中增加 `is_experimental` 布尔字段 + `filter_reason` 中文说明。非实验表提取后自动折叠，显示过滤原因（如 "数据集统计信息"），用户可手动展开。

### 5.4 Benchmark/Dataset 名称归一化

**难点**：LLM 返回的名称不统一 — 同一 Benchmark 被写成 "Action Recognition"、"Action Classification"、"EPIC-KITCHENS-100"；同一数据集 EPIC-KITCHENS 有 20+ 种变体（-100/-Test/-Val/-Verb/-Noun/-Action 等自由组合）。

**方案**：`llm_service.py` 内置别名映射表（`_normalize_benchmark`）和正则归一化规则（`_normalize_dataset`：任意 EPIC-KITCHENS-* → EPIC-KITCHENS，EK/EK100 → EPIC-KITCHENS），加上噪声黑名单（"val"/"test"/"overall" 等裸名称）。跨论文后验证：Session 2 从 24 组 → 11 组合并。

### 5.5 LLM 提取稳定性与增量策略

**难点**：LLM 同一张表两次调用可能返回不同数量的 records（因为 LLM 有随机性），直接全量覆盖会丢失之前已提取的其他表数据。

**方案**：`extract_llm_from_chunks()` 采用逐表增量策略 — 仅当该 TableChunk 尚无 records 时才写入，避免覆盖已有数据。同时保留 `table_chunk_id` FK 关联，排行榜可按表回溯。

### 5.6 同一页多表 caption 误匹配

**难点**：Dong 论文 page 7 有 5 张表（Table 3-7），Docling 未提取到 caption 时，PyMuPDF 在表格上下方搜索 "Table N:"，搜索区域覆盖了上方表的 caption，导致 Table 7 显示 Table 6 的标题。

**方案**：`_search_caption_bidirectional` 改为仅搜索表格**上方** 120pt 区域，取最后一个匹配（Y 坐标最靠近表格顶部的 caption），避免误匹配后方表格的标题。

### 5.7 跨 Session 排行榜隔离

**难点**：不同项目（Session）的论文数据需要独立汇聚，不能混淆。

**方案**：排行榜视图接收 `session_id` 参数，所有 query 加 `paper__session=session` 过滤。排行榜页面 URL 嵌入 Session ID（`/projects/<id>/leaderboards/`），列表和详情页自动限定范围。

### 5.8 JSON 嵌入 HTML 的安全问题

**难点**：Alpine.js 客户端排序需要将 Python dict 序列化为 JS 对象。直接用 `{{ json|safe }}` 嵌入 HTML 属性时，模型名中的 `&`（如 "Pos &Neg"）被浏览器误解析为 HTML 实体，导致 JS 解析失败。

**方案**：改使用 Django 的 `json_script` 模板过滤器，将数据嵌入 `<script type="application/json">` 标签中，`&` 自动转义为 `&`，完全安全。

### 5.9 Benchmark 描述自动生成

**难点**：排行榜详情页需要为每个 Benchmark 展示中文任务说明。已知任务（UDA、DG 等）可预定义，但新论文引入的新 Benchmark（如 PointingQA、Pose Tracking）无法提前覆盖。

**方案**：三级获取机制 — ① 预定义字典（14 个已知 Benchmark，精心编写）→ ② `benchmark_descriptions.json` 缓存文件（LLM 历史生成结果）→ ③ LLM 实时生成（聚合数据集名、指标名、caption 作为上下文，生成 1-2 句中文说明，自动写入缓存）。新 Benchmark 仅首次访问触发 LLM 调用（~2 秒），后续从缓存秒开。无 API Key 时自动降级为原始 caption 兜底。

---

## 6. 部署说明

### 6.1 一键安装

```bash
git clone https://github.com/DemoStoneG/BenchHub.git
cd BenchHub
cp .env.example .env                        # 编辑 .env 填入 MiniMax API Key
bash setup.sh                               # 自动：创建 venv → pip install → migrate
bash start.sh                               # 启动 → http://localhost:8000
```

### 6.2 手动安装

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
```

### 6.3 配置 LLM

API Key 通过**环境变量**注入，不硬编码在代码中：

```bash
export MINIMAX_API_KEY='sk-cp-your-key'
# 或写入 ~/.bashrc 永久生效
```

也可复制 `.env.example` → `.env` 填入 Key。换 OpenAI / Anthropic 需编辑 `services/llm_service.py`。

### 6.4 开发 + 生产双实例

同一台机器可运行两个独立实例，共享 conda 环境但数据隔离：

```bash
# 生产实例（数据库独立）
git clone ~/BenchHub ~/benchhub-app
cd ~/benchhub-app && bash start.sh 9000     # 端口 9000

# 开发环境
cd ~/BenchHub && bash start.sh 8000          # 端口 8000
```

### 6.5 生产环境

`benchhub/settings.py`：

```python
DEBUG = False
ALLOWED_HOSTS = ['your-domain.com']
SECRET_KEY = '<new-random-key>'
```

换 `gunicorn` / `uWSGI` 代替 `runserver`，配合 nginx 反向代理 + supervisor/systemd 进程守护。

### 6.6 安全注意事项

| 文件 | 是否提交 Git | 说明 |
|:---|:---|:---|
| `benchhub/settings.py` | ✅ | API Key 读环境变量，不硬编码 |
| `.env` | ❌ (`.gitignore`) | 包含真实 API Key |
| `.env.example` | ✅ | 模板文件，含占位 Key |
| `benchmark_descriptions.json` | ❌ (`.gitignore`) | LLM 自动生成缓存 |
| `db.sqlite3` | ❌ (`.gitignore`) | 本地数据 |
| `media/` | ❌ (`.gitignore`) | 上传的 PDF |

---

## 7. 版本历史

### 数据提取方案演进

| 版本 | 方案 | 结果 |
|:---|:---|:---|
| V1 | Table Transformer 坐标映射（6 层变换） | ❌ 累积误差 10-20px |
| V2 | 纯 PyMuPDF 词坐标聚类（header-template + Y 聚类） | ⚠️ 阈值一刀切，子列混淆 |
| V3 | Docling 完整管线（计划 50 行胶水代码） | ⚠️ 落地时被绕过 |
| V4 | Docling bbox + PyMuPDF 坐标重建表格 | ⚠️ 丢弃 TableFormer 结构数据 |
| **V5 (当前)** | **Docling table_cells 直接遍历 + 子行拆分** | ✅ **3 论文 26 表，0 误伤** |

### 架构关键清理

- **2026-06-15**：删除 `services/structured_parser.py` (~788 行) — 与 docling_service 功能重叠
- **2026-06-15**：删除 `llm_service.py` 中 STRUCTURED_PROMPT + extract_from_structured_text — structured_parser 配套代码
- **2026-06-15**：删除 compare.html + 5 个对比相关视图 + toggle_table_compare — 排行榜替代
- **2026-06-15**：删除 article 页 records 编辑区（updateRecord/deleteRecord/verifyAll/mergeMetrics）— 冗余信息
- **2026-06-15**：删除 TableImage 模型 + 截图管线 — Docling HTML 替代
- **2026-06-15**：删除 6 个废弃 service 文件（latex/pdf/table_extractor/marker/parser/md_parser/table_transformer/table_extraction_v2）— 旧方案残留
- **2026-06-15**：集成 LLM 自动 pipeline（表格提取 → LLM 抽取 → 归一化 → 入库）— 全自动
- **2026-06-15**：新增排行榜系统（卡片列表 + 多数据集排名表 + Alpine.js 客户端排序 + 中文说明）
- **2026-06-15**：新增 Benchmark/Dataset 归一化 + 噪声过滤 + 表格分类（is_experimental）
