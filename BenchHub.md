# BenchHub — 个人 AI 论文实验数据智能管理平台

> 上传 PDF → 自动抽取实验数据 → 构建私有 SOTA 排行榜  
> 对标 [PapersWithCode](https://paperswithcode.com) · [Wizwand SOTA Leaderboard](https://www.wizwand.com/sota/action-recognition-on-epic-kitchens-100-test)  
> **让每一位研究者，都拥有自己的 SOTA 排行榜。**

**GitHub**: [DemoStoneG/BenchHub](https://github.com/DemoStoneG/BenchHub)

---

## 1. 技术背景

### 1.1 论文实验数据对比的困境

AI 研究者追踪领域进展时，每周需要对比几十篇论文的实验表格。整个过程是纯手工的：

1. **查数**：打开 PDF → 翻到实验页 → 找到目标表格 → 肉眼对齐行列 → 抄数字
2. **敲数**：手动录入 LaTeX `\begin{tabular}` → 填 Model × Dataset × Metric × Value
3. **对比**：多篇论文之间手动收集、排序、重新画表
4. **更新**：新论文出来 → 以上全部重来一遍

研究者大量时间消耗在"查数 + 敲数"上，而非分析结果本身。

### 1.2 现有方案与不足

| 方案 | 痛点 |
|:---|:---|
| **PapersWithCode** | 依赖作者手动提交，覆盖不全，滞后严重 |
| **Wizwand SOTA Leaderboard** | 仅覆盖少数榜单，数据不公开，无法自定义 |
| **手动维护 Excel / LaTeX** | 耗时、易错、难以跨论文汇聚排名 |
| **通用 PDF 解析工具 (Camelot / Tabula)** | 对学术论文复杂表格（colspan/rowspan、段标题、子行）准确率低 |

**核心缺口**：缺乏一个**全自动**的工具，能从 PDF 直接走到可排序的 SOTA 排行榜。

### 1.3 为什么 PDF 表格提取难

学术论文表格远比普通表格复杂：

- **多行表头**：列头上方还有分组行
- **colspan / rowspan** ：跨列合并单元格
- **段标题行**：表格内嵌 "UDA" / "DG" 等分类横条
- **无横线子行**：PDF 中无分隔线但逻辑上是两行（如 "Source Only" 下隐含 "TBN-TRN"）
- **同页多表**：页码上 5 张表挤在一起，标题与表格的对应关系模糊

### 1.4 AI 论文表格的领域特征

BenchHub 当前以**视频理解 / 第一人称 AI** 领域为核心场景，覆盖以下数据特征：

| 维度 | 典型值 |
|:---|:---|
| **Benchmark** | Action Recognition、UDA、DG、NLQ、Moment Query、Multi-Instance Retrieval、EgoMCQ |
| **Dataset** | EPIC-KITCHENS（20+ 种变体）、EGTEA、Charades-Ego、Ego4D |
| **Metric** | Top-1/5 Acc（Verb / Noun / Action）、mAP、nDCG、R@1/R@5 |
| **Model** | Source Only、SeqDG、RNA、TA3N、EgoVLP、EgoVideo 等 |

---

## 2. 需求分析

### 2.1 用户画像与场景

| 场景 | 用户 | 需求 |
|:---|:---|:---|
| **实验室论文追踪** | 研究生/博士后 | 每周阅读新论文，需要快速提取实验数据，对比各方法表现 |
| **论文写作** | 投稿作者 | 需要生成与 SOTA 的对比表（LaTeX 格式），直接贴入 `.tex` 文件 |
| **Survey / Meta-analysis** | 综述作者 | 聚合某 Benchmark 下所有论文的历史数据 |
| **Reviewer 审查** | 审稿人 | 快速验证投稿声称的 SOTA 数据是否真实 |

### 2.2 核心需求

| 编号 | 需求 | 说明 |
|:---|:---|:---|
| R1 | **自动表格提取** | 上传 PDF 自动识别所有实验表格，不需标记区域或手动框选 |
| R2 | **结构化数据抽取** | 从每张表中提取 (Benchmark, Model, Dataset, Metric, Value) 五元组 |
| R3 | **智能表格分类** | 自动区分实验对比表 vs 数据集统计表/参数表，非实验表不参与排名 |
| R4 | **名称归一化** | 同一 Benchmark/Dataset 的多种写法自动合并 |
| R5 | **跨论文排行榜** | 同一 Benchmark 下不同论文的模型按指标排名 |
| R6 | **客户端排序** | 点击列头升/降序切换，无页面刷新 |
| R7 | **数据导出** | 排名表可导出为 CSV（Excel 兼容）或 LaTeX 源码，直接贴入论文 |
| R8 | **项目隔离** | 不同研究方向的论文分开管理，排行榜互不干扰 |
| R9 | **Benchmark 解释** | 每个 Benchmark 附带中文说明，避免面对缩写一脸懵 |

### 2.3 非功能需求

| 编号 | 需求 | 说明 |
|:---|:---|:---|
| N1 | **本地化部署** | 数据存储在本地，不强制上传到公共服务器 |
| N2 | **零前端构建** | CDN 直引，不需要 Webpack/Vite，clone 即可用 |
| N3 | **数据可靠性** | LLM 抽取失败时 5 次重试；增量写入避免覆盖已有数据 |
| N4 | **可替换性** | LLM 后端可换（MiniMax → OpenAI → Anthropic），API Key 通过环境变量注入 |
| N5 | **轻量依赖** | 单文件 SQLite，`scp` 即可备份 |

---

## 3. 核心数据流

### 3.1 六步表格提取 Pipeline（Docling + TableFormer）

```
① DocumentConverter.convert()
   输入 PDF → IBM Docling 解析 → 输出结构化文档对象（文本段落/图片/表格）

② 过滤 Appendix
   跳过附录章节中的表格，只保留正文实验表格

③ 提取 Caption
   优先 Docling 抽取表格标题，失败时 PyMuPDF fallback（仅搜表格上方 120pt）

④ TableFormer 结构化
   基于 PubTables-1M 训练（TEDS 96.75%），输出每个 cell 的语义标注：
   column_header（列头）、row_section（段标题）、col_span / row_span（合并单元格）

⑤ _table_cells_to_html()
   遍历带语义标注的 table_cells，直接渲染为标准 HTML 表格（不做坐标反推）

⑥ 写入 TableChunk
   封装 HTML + caption + 页码 + 标签，入库供下游 LLM 抽取
```

### 3.2 LLM 抽取 + 排行榜汇聚

```
TableChunk（HTML 表格）
  ↓
LLM 逐表抽取（MiniMax M2，可替换）
  ├─ records: [{benchmark, model, dataset, metric, value}, ...]
  ├─ tags: {datasets: [...], tasks: [...]}
  ├─ is_experimental: true/false
  └─ filter_reason: "数据集统计信息"
  ↓
归一化处理
  ├─ Benchmark 别名映射 + 去 "on XXX" 后缀
  ├─ Dataset 20+ 变体归一（EPIC-KITCHENS-* / EK / EK100 → EPIC-KITCHENS）
  ├─ 小指标排行榜合并进大排行榜
  └─ 噪声过滤（丢弃裸 val / test / overall）
  ↓
ExperimentRecord 入库（关联 TableChunk + Paper）
  ↓
排行榜构建（两层分组）
  A. 会话级：按项目隔离 → 按 (Benchmark, Dataset) 分组 → 每组计模型数/指标列表/最高分 → 卡片列表
  B. 明细级：按 Dataset 分组 → Models 纵向展开 + Metrics 横向展开 → 前端排序 + CSV/LaTeX 导出
```

---

## 4. 功能清单

| 模块 | 说明 |
|:---|:---|
| **PDF 表格提取** | Docling TableFormer 识别表格结构：colspan/rowspan、表头语义、段标题（UDA/DG 横条）。PubTables-1M 训练，TEDS 96.75% |
| **子行拆分** | PyMuPDF 词坐标 Y 聚类检测无横线子行合并，自动拆为独立 `<tr>` + 虚线分隔 + rowspan 去重 |
| **LLM 数据抽取** | 逐表提取 (Benchmark, Model, Dataset, Metric, Value) 五元组。Prompt 包含去样式 HTML + caption，5 次指数退避重试 |
| **表格自动分类** | LLM 判断 `is_experimental`，非数据表（统计/参数/消融）自动折叠并标注原因，不参与排行榜 |
| **自动打标签** | 每张表标注 datasets + tasks 标签，显示在表格头部 |
| **数据归一化** | Benchmark 别名映射 + Dataset 20+ 变体归一（EPIC-KITCHENS-* → EPIC-KITCHENS）+ 噪声过滤。24 组 → 11 组 |
| **SOTA 排行榜** | 按 Benchmark 分组，跨论文汇聚排名。Alpine.js 客户端排序（点列头升/降序），前三名 🥇🥈🥉 高亮 |
| **Benchmark 说明** | 已知任务硬编码中文描述，新 Benchmark 首次访问 LLM 自动生成并缓存到 JSON 文件 |
| **数据导出** | 每个排名表一键下载 CSV（UTF-8 BOM，Excel 兼容）或复制 LaTeX `\begin{table}` 源码 |
| **项目隔离** | Session 维度独立管理论文与排行榜，URL 嵌入 Session ID，多项目互不干扰 |
| **Logo & 首页美化** | 六边形 Hub + 排名柱 Logo，首页统计栏 + 进度环 + 空状态插图 + 渐变色按钮 |

---

## 5. 技术栈与设计决策

### 5.1 选型理由

| 组件 | 选型 | 为什么 |
|:---|:---|:---|
| 后端 | Django 4.2 + SQLite | 快速开发，内置 Admin 调试方便；单文件 `scp` 即可备份 |
| 表格提取 | Docling TableFormer + PyMuPDF | IBM 开源，PubTables-1M 训练，96.75% TEDS；PyMuPDF 仅用于子行拆分补丁 |
| LLM | MiniMax M2（可换） | 逐表 JSON 抽取 + 表格分类 + Benchmark 说明生成 |
| 前端 | Tailwind CSS + Alpine.js + pdf.js + markdown-it | 全 CDN 零构建，clone 即用 |
| 排序 | Alpine.js 客户端排序 | 点击列头即时排序，无页面刷新 |
| 导出 | 纯前端 Blob / Clipboard API | CSV 下载 + LaTeX 复制，不依赖后端 |
| 异步 | `subprocess.Popen` 子进程 | 个人工具无需 Celery/RabbitMQ |

**精简设计**：核心引擎仅 2 个文件 — `services/docling_service.py`（~370 行）+ `services/llm_service.py`（~380 行）。

### 5.2 替代方案对比

| 选型 | 替代方案 | 选择理由 |
|:---|:---|:---|
| Docling TableFormer | Camelot / Tabula / Table Transformer | 前三者对学术复杂表格准确率低；Table Transformer 需要自己搭 6 层坐标变换 |
| SQLite | PostgreSQL / MySQL | 个人工具无需 client-server 数据库，单文件即可 |
| MiniMax M2 | GPT-4o / Claude | MiniMax 性价比高，`llm_service.py` 替换 endpoint 即可切换 |
| CDN 直引 | Webpack / Vite / npm | 个人工具无需构建系统，CDN 一行 `<script>` 搞定 |
| Alpine.js | React / Vue / Svelte | 排行榜排序只需轻量响应式，不需要 SPA 框架 |

---

## 6. 核心技术难点

### 6.1 PDF 表格结构识别 (V1 → V5)

4 次方案失败，最终 V5 采用 **Docling TableFormer 的 `table_cells` 语义标注**直接遍历生成 HTML：

| 版本 | 方案 | 失败原因 |
|:---|:---|:---|
| V1 | Table Transformer 坐标映射 | 6 层变换链，累积误差 10-20px |
| V2 | 纯 PyMuPDF 词坐标聚类 | 阈值一刀切，字体/行距差异大 |
| V3 | Docling 完整管线 | 计划太乐观，落地时被绕过 |
| V4 | Docling bbox + 坐标重建 | 丢弃了 TableFormer 已有的 col_span / row_section |
| **V5** | **TableFormer cells 直接遍历** | ✅ 3 论文 26 表，0 误伤 |

> **核心认知**：表格提取不是"在 PDF 上画框"，而是理解语义结构。TableFormer 已输出 column_header、row_section、col_span、row_span，直接信任即可。

### 6.2 子行拆分

PDF 中无横线分隔的两个物理行被 TableFormer 识别为一个逻辑行 → HTML 挤在同一 `<tr>`。
**方案**：在 cell bbox 内用 PyMuPDF `get_text("words")` 按 Y 坐标聚类（gap > 4pt → 新子行），同行 ≥70% 多数值 cell 呈现相同簇数才认定。独立 `<tr>` + 虚线 + rowspan 去重。

### 6.3 LLM 智能抽取与分类

同一 LLM 调用完成四件事：提取五元组 + 表格分类（`is_experimental`）+ 打标签（datasets/tasks）+ 过滤原因。Prompt 中提供去样式 HTML + caption，输出结构化 JSON。
**鲁棒性**：解析失败时 5 次指数退避重试（1s → 2s → 4s → 8s → 16s），JSON 截断时自动补 `]` 修复。
**增量策略**：仅当该 TableChunk 尚无 records 时写入，避免 LLM 随机性导致覆盖丢失。
**设计原则**：LLM 只做最难的那 5%——理解表格在说什么。主力是 TableFormer（结构）+ 规则（归一化）+ Alpine.js（排序）。

### 6.4 名称归一化

同一 Benchmark 被 LLM 写成 "Action Recognition" / "Action Classification" / "EPIC-KITCHENS-100"；同一数据集 EPIC-KITCHENS 有 20+ 种变体（-100/-Test/-Val/-Verb/-Noun/-Action 自由组合）。
**方案**：别名映射表 + 正则归一化（EPIC-KITCHENS-* / EK / EK100 → EPIC-KITCHENS）+ 噪声黑名单（裸 val/test/overall 丢弃）。24 组归一化为 11 组。

### 6.5 同页多表 Caption 误匹配

PyMuPDF 在表格上下方搜索 "Table N:"，搜索区域覆盖了其他表的 caption。
**方案**：仅搜索表格**上方** 120pt，取 Y 坐标最靠近表格顶部的匹配。

### 6.6 Benchmark 描述自动生成

已知 Benchmark（UDA/DG 等 14 个）硬编码中文描述，新 Benchmark 无法提前覆盖。
**方案**：三级获取 — ① 预定义字典 → ② `benchmark_descriptions.json` 缓存 → ③ LLM 实时生成（聚合数据集名+指标名+caption，生成 1-2 句中文说明，自动写入缓存）。首次 ~2 秒，后续秒开。

### 6.7 前端安全与设计

- **JSON 嵌入安全**：使用 Django `json_script` 过滤器替代 `{{ json|safe }}`，`&` 等特殊字符自动转义
- **CSV/LaTeX 导出**：纯前端 Blob download + Clipboard API，无后端依赖，CSV 带 BOM 确保 Excel UTF-8 兼容
- **首页设计**：Logo SVG + 四卡统计栏 + 项目进度环 + 空状态插图 + indigo→purple 渐变按钮

---

## 7. 目录结构

```
BenchHub/
├── benchhub/              # Django 工程配置
│   └── settings.py        # API Key 读环境变量，不硬编码
├── papers/                # 业务 app
│   ├── models.py          # Session / Paper / ExperimentRecord / TableChunk
│   ├── views.py           # 项目 / 论文 / 排行榜视图 + Benchmark 描述三级获取
│   ├── tasks.py           # 异步 pipeline（表格提取 + LLM 抽取）
│   └── urls.py            # 24 条路由
├── services/              # 核心引擎（仅 2 个文件）
│   ├── docling_service.py # Docling TableFormer 表格提取 + 子行拆分
│   └── llm_service.py     # LLM 逐表抽取 + Benchmark/Dataset 归一化
├── templates/papers/
│   ├── session_list.html          # 首页（项目卡片 + 统计栏 + 空状态）
│   ├── session_detail.html        # 项目详情（论文列表 + 排行榜入口）
│   ├── leaderboard_list.html      # 排行榜卡片列表
│   ├── leaderboard_detail.html    # 排名表（排序 + CSV/LaTeX）
│   ├── review.html                # 论文表格预览（可折叠）
│   └── upload.html                # PDF 上传
├── static/logo.svg        # 项目 Logo
├── docs/BenchHub.pptx     # 项目 PPT（7 页）
├── setup.sh start.sh      # 一键安装 & 启动
└── requirements.txt
```

---

## 8. 快速开始

```bash
git clone https://github.com/DemoStoneG/BenchHub.git
cd BenchHub
cp .env.example .env             # 编辑 .env 填入 MiniMax API Key
bash setup.sh                    # 自动：创建 conda/venv → pip install → migrate
bash start.sh                    # 启动 → http://localhost:8000
```

**使用流程**：创建项目 → 上传 PDF → 等待解析（2-10 分钟）→ 查看排行榜 → 点列头排序 → CSV/LaTeX 导出。

**页面导航**：

| 页面 | URL | 说明 |
|:---|:---|:---|
| 首页 | `/` | 项目列表 + 统计栏，可搜索 |
| 项目页 | `/projects/<id>/` | 论文列表 + 上传 + 排行榜入口 |
| 论文详情 | `/articles/<id>/` | 表格预览，可折叠，非实验表标记 |
| 排行榜列表 | `/projects/<id>/leaderboards/` | 按 Benchmark 分组的卡片 |
| 排行榜详情 | 点卡片进入 | 多数据集排名表，列头排序 + CSV/LaTeX |

---

## 9. 配置与部署

### LLM 配置

API Key 通过环境变量注入，不硬编码：

```bash
export MINIMAX_API_KEY='sk-cp-your-key'
```

换用其他 LLM 编辑 `services/llm_service.py` 的 `_call_llm` 方法即可。

### 开发 + 生产双实例

```bash
git clone ~/BenchHub ~/benchhub-app    # 生产实例（数据库独立）
cd ~/benchhub-app && bash start.sh 9000

cd ~/BenchHub && bash start.sh 8000     # 开发环境
```

### 生产部署

`settings.py` 中设置 `DEBUG=False`，换 gunicorn/uWSGI + nginx + supervisor/systemd。

---

## 10. 安全

| 文件 | Git | 说明 |
|:---|:---|:---|
| `benchhub/settings.py` | ✅ | API Key 读环境变量 |
| `.env` | ❌ | 真实 API Key |
| `.env.example` | ✅ | 模板文件 |
| `benchmark_descriptions.json` | ❌ | LLM 生成缓存 |
| `db.sqlite3` | ❌ | 本地数据 |
| `media/` | ❌ | 上传的 PDF |

---

## 11. 未来规划：从工具，走向平台

| 阶段 | 目标 | 内容 |
|:---|:---|:---|
| **近期** | 完善产品体验 | 增加图表 / 趋势图功能（Plotly / ECharts），横向时间纵向指标，对标 Wizwand；LLM 结果缓存 |
| **中期** | 多场景落地 | 覆盖个人研究者、实验室内部多用户（Django + PostgreSQL + Celery）、Web 公开社区（REST API + React/Vue） |
| **长期** | arXiv 自动爬取 | 论文发表即自动上榜，社区编辑 + 批量入库，构建公开 SOTA 数据库 |

**核心理念**：让研究者从"查数 + 敲数"中解放出来，专注于分析结果。

---

## 12. FAQ

**Q: 解析一篇论文多久？**
A: 8 页约 2-5 分钟，20 页以上约 5-10 分钟。瓶颈在 LLM 逐表分析。

**Q: 为什么有些表格显示"被过滤"？**
A: LLM 判断该表非实验对比表（如数据集统计），自动折叠标注原因。可手动展开查看。

**Q: 排行榜数据不对？**
A: 到 Django Admin (`/admin/`) 编辑 ExperimentRecord，或点"重新解析"重跑。

**Q: 支持 Windows 吗？**
A: WSL2 推荐。纯 Windows 需 conda 环境并确保 Docling 模型下载路径无误。

**Q: LLM 能换吗？**
A: `llm_service.py` 的 `_call_llm` 方法改 endpoint 和 payload 即可，OpenAI / Anthropic / 国产模型均可。
