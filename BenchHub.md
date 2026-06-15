# BenchHub — 个人 AI 论文实验数据管理工具

## 1. 产品定位

一个为研究人员/开发者设计的本地化工具。用户上传论文 PDF，系统自动抽取实验数据，构建私有的 SOTA 对比库，减少写论文对比表时手动"查数"和"敲数"的时间。

- **私有化**：数据存储在本地/私有服务器，不强制公开
- **工具化**：核心目标是把 PDF 里的实验数字快速、准确地变成可编辑、可对比、可导出的结构化数据

---

## 2. 当前实现状态（2026-06-15）

所有 MVP Step 1-5 已实现，并在此之上做了显著增强：

### 2.1 已完成的 MVP 功能

| Step | 功能 | 状态 |
|:---|:---|:---|
| **Step 1** | Django 工程搭建、Paper/Session 模型、文件上传 | 已完成 |
| **Step 2** | PDF 表格提取 pipeline（Docling/TableFormer → HTML → TableChunk） | 已完成 |
| **Step 3** | 前端表格展示与人工校验编辑器 | 已完成 |
| **Step 4** | 多论文对比视图（按 Benchmark 分组对齐） | 已完成 |
| **Step 5** | LaTeX 导出（按 Benchmark 分块生成 tabular） | 已完成 |

### 2.2 额外增强（超出 MVP）

- **项目（Session）管理**：支持创建/编辑/删除多个项目，每个项目内论文与对比独立隔离
- **AI 表格提取**（2026-06 重写）：从 PDF 论文中自动提取完整表格结构，渲染为 HTML，**结果持久化到数据库，上传/重试时自动执行**
- **子行拆分**（2026-06-15 新增）：当 TableFormer 将 PDF 中多个物理子行合并为一个逻辑行时，自动检测并拆分为独立 `<tr>`，带虚线分隔和 rowspan
- **重试进度条**（2026-06-15 新增）：点击"重新解析"后实时显示状态轮询进度（5% → 30% → 75% → 100%），完成后自动刷新

### 2.3 AI 表格提取子系统

#### 架构（最终版，2026-06-15）

```
PDF → Docling (TableFormer: Detection + Structure)
    → table.data.table_cells (结构化 cell 列表)
    → 遍历 cells，按 row_offset_idx 排序
    → column_header? → <th>（蓝底表头）
    → row_section? → 全宽 <th colspan=n>（紫底段标题，如 "UDA" / "DG"）
    → row_header? → <td class="text-left font-medium">（方法名列加粗）
    → col_span / row_span → colspan / rowspan HTML 属性
    → PyMuPDF 词坐标 Y 聚类 → 子行拆分（独立 <tr> + 虚线分隔 + rowspan 去重）
    → Tailwind CSS 美化 + 斑马纹
    → API JSON → 前端 Django 模板渲染
```

#### 关键技术决策

| 决策 | 选型 | 原因 |
|:---|:---|:---|
| 表格结构识别 | Docling TableFormer（内置） | PubTables-1M 训练，生产级，96.75% TEDS |
| 表头语义分类 | `column_header` / `row_header` / `row_section` | TableFormer 模型推理结果，非规则 |
| 段标题检测 | `row_section` bool | 模型直接标识（如 "UDA" / "DG"） |
| colspan/rowspan | `col_span` / `row_span` 字段 | TableFormer 原生输出 |
| 子行拆分 | PyMuPDF 词坐标 Y 聚类 + 行级一致性检查 | 解决 TableFormer 将多物理子行合并为一逻辑行的问题 |
| 全局框架 | Docling | caption 提取 + Appendix 过滤 + bbox 定位 |

#### 子行拆分机制

TableFormer 有时将 PDF 中多个物理子行（如 Method 列有 "Source Only" 和 "TA3N" 两行）合并为一个逻辑行。解决方案：

1. **触发条件**：cell 内含 ≥2 个独立数值（排除 "▲ +X.Y" 增量注释）
2. **Y 聚类**：在 cell bbox 内用 PyMuPDF `get_text("words")` 按 Y 坐标聚类（gap > 4pt → 新子行）
3. **一致性检查**：同一行内 ≥70% 的多数值 cell 呈现相同簇数时才认定子行存在
4. **渲染**：每个子行为独立 `<tr>`，第二个子行起加 `border-t border-dashed border-gray-300`
5. **rowspan 优化**：内容在所有子行中相同的 cell 用 `rowspan=n` 跨行，不重复渲染
6. **去重**：自然 Y 聚类或强制复制后，若所有子行文本相同 → 只保留一份

#### 验证结果（2026-06-15）

3 篇论文 26 张表：

| 论文 | 表数 | col_header | row_section | 子行拆分 | 误伤 |
|:---|:---|:---|:---|:---|:---|
| EgoVideo | 10 | ✅ | N/A | 0（无子行表） | 0 |
| DG/SeqDG | 8 | ✅ | ✅ UDA/DG | 3 表 / 18 行 | 0 |
| EgoVLP | 8 | ✅ | N/A | 0（无子行表） | 0（之前 123 误拆全部修正） |

#### 已知局限

1. **子行拆分粒度**：仅检测同 cell 内多数值 → Y 聚类。若 PDF 中仅文本 cell 有子行但无数值 cell 对应（极罕见），不会触发拆分。
2. **row_section 依赖模型**：若 TableFormer 未识别某段标题行，不会渲染为紫色横条。
3. **header cell 文本对齐**：TableFormer 的 cell.text 来自内部 OCR/文字对齐管线，极少数情况可能有 artifacts（如 ✓ 被识别为 `!`）。

#### 代码位置

`services/docling_service.py` (369 行) — 8 个函数

---

## 3. 技术架构（实际落地）

| 组件 | 选型 | 说明 |
|:---|:---|:---|
| **后端框架** | Django 4.2 | 快速开发，内置 Admin 方便直接在后台改数 |
| **数据库** | SQLite | 个人工具，单文件易备份，查询性能足够 |
| **PDF 表格提取** | Docling (TableFormer) + PyMuPDF (子行拆分) | 生产级表格结构识别 |
| **LLM** | MiniMax M2（可在 `benchhub/settings.py` 替换为 OpenAI/Anthropic） | 实验数据元组抽取 |
| **前端** | Tailwind CSS (CDN) + Alpine.js (CDN) + pdf.js (CDN) + markdown-it (CDN) | 极简开发，无构建步骤 |

---

## 4. 核心数据模型 (models.py)

```python
class Session(models.Model):
    """研究项目 / 对比会话。每个 session 内的论文与对比相互独立。"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Paper(models.Model):
    session = models.ForeignKey(Session, on_delete=CASCADE, related_name='papers')
    title = models.CharField(max_length=500)
    arxiv_id = models.CharField(max_length=50, blank=True)
    local_pdf = models.FileField(upload_to='papers/')
    raw_markdown = models.TextField(blank=True)
    status: PENDING | EXTRACTING | CALLING_LLM | COMPLETED | FAILED
    progress_message / error_message
    created_at

class ExperimentRecord(models.Model):
    """一条具体的实验数据"""
    paper (FK) → table_chunk (FK, nullable) → table_image (FK, nullable)
    benchmark, dataset, model_name, metric, value
    is_verified

class TableChunk(models.Model):
    """Docling 提取的单张表格 HTML（主路径）"""
    paper (FK) / table_n / sub_table_index / page
    caption / markdown_text          # markdown_text 存储 HTML 快照
    cells_json / header_json / bbox_json  # bbox_json 含 html + rows + cols
    extraction_method: docling | camelot_stream | camelot_lattice | pymupdf_find_tables | pymupdf4llm
    parent_table_n (nullable)

class TableImage(models.Model):
    """PDF 表格截图（旧的横线聚类路线）"""
    paper (FK) / page_number / image / caption
    order / selected_for_compare
    created_at
```

**关键关系**：`ExperimentRecord.table_chunk` 将每条实验数据关联回来源表格，方便校对时按表分组展示。

---

## 5. 使用流程

1. **创建项目**：首页点 "+ 新建项目"，填写项目名和描述
2. **上传论文**：项目页 `/projects/<id>/` 点 "+ 上传论文"，选 PDF 上传 → **自动在后台启动表格提取**
3. **等待解析**：页面显示状态进度条（待解析 → 提取中 → 调用 LLM → 已完成/失败）
4. **校对数据**：`/articles/<id>/` 上半部分展示提取的 HTML 表格，下半部分为 record 编辑器
   - 修改任意单元格自动保存
   - 点击"全部校验"批量标记
   - "合并指标"面板，把 `Accuracy` 和 `Acc` 等近义指标合并
5. **重新解析**：项目页每篇论文有"重新解析"按钮，点击后显示实时进度条，完成后自动刷新
6. **生成对比表**：`/projects/<id>/compare/` 勾选论文 → 按 Benchmark 分块渲染 → 复制 LaTeX

---

## 6. 目录结构

```
benchhub/              # Django 工程配置
papers/                # 业务 app：models / views / urls / tasks / admin / migrations
services/              # 核心服务
  docling_service.py   # Docling/TableFormer 表格提取 + 子行拆分（主引擎，369 行）
  llm_service.py       # LLM 调用 + JSON 解析（单表抽取）
  table_extractor.py   # PDF 表格截图
  latex_service.py     # LaTeX 生成
  md_parser.py         # pymupdf4llm 表格切分（camelot 旧路径 fallback）
  pdf_service.py       # pypdf 文本提取
  parser_service.py    # Markdown 表格规则解析
  marker_service.py    # Marker 封装（保留，不主用）
templates/             # HTML 模板
media/                 # 上传的 PDF + 表格截图
```

---

## 7. 版本历史

### 表格提取方案演进

| 版本 | 方案 | 结果 |
|:---|:---|:---|
| V1 | Table Transformer 坐标映射（6 层变换） | ❌ 累积误差 10-20px |
| V2 | 纯 PyMuPDF 词坐标聚类（header-template + Y 聚类） | ⚠️ 阈值一刀切，子列混淆 |
| V3 | Docling 完整管线（计划 50 行胶水代码） | ⚠️ 落地时被绕过 |
| V4 | Docling bbox + PyMuPDF 坐标重建表格（`_rebuild_table` ~95 行） | ⚠️ 丢弃 TableFormer 结构数据 |
| **V5 (当前)** | **Docling `table.data.table_cells` 直接遍历 + 子行拆分** | ✅ **3 论文 26 表，0 误伤，0 重复** |

### 关键清理

- **2026-06-15**：删除 `services/structured_parser.py`（~788 行，camelot×2 + PyMuPDF + pymupdf4llm 四级提取器 + colspan/rowspan 反推 + 段标题识别 + 子表合并 + LLM 文本序列化）。此系统与 docling_service 功能重叠，且底层模型相同（TableFormer）。删除后净减少约 850 行代码。
- **2026-06-15**：删除 `llm_service.py` 中的 `STRUCTURED_PROMPT`（24 行）和 `extract_from_structured_text()`（22 行），仅 structured_parser 管线使用。
- **2026-06-15**：前端删除"🤖 AI 表格提取"按钮及相关 Alpine.js 组件。表格提取在上传/重试时自动执行，结果持久化在 TableChunk 中，文章页直接从数据库加载。
