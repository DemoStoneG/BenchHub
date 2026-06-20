# BenchHub — 个人 AI 论文实验数据智能管理平台

上传 PDF → 自动抽取实验数据 → 构建私有 SOTA 排行榜。对标 [Wizwand](https://www.wizwand.com/sota/action-recognition-on-epic-kitchens-100-test)。

**GitHub**: [DemoStoneG/BenchHub](https://github.com/DemoStoneG/BenchHub)

---

## 1. 核心数据流

```
上传 PDF
  ↓
Docling TableFormer 解析 PDF 表格 → TableChunk（HTML 表格 + caption + 页码）
  ↓
LLM（MiniMax M2，可替换）逐表提取
  ├─ records: [{benchmark, model, dataset, metric, value}, ...]
  ├─ tags: {datasets: [...], tasks: [...]}
  ├─ is_experimental: true/false  （非实验表自动折叠不参与排行）
  └─ filter_reason: "数据集统计信息"
  ↓
归一化：Benchmark 别名 + Dataset 变体合并 + 噪声过滤
  ↓
ExperimentRecord 入库（关联 TableChunk + Paper）
  ↓
排行榜：按 (Benchmark, Dataset) 分组 → 按指标排名 → CSV / LaTeX 一键导出
```

---

## 2. 功能清单

| 模块 | 说明 |
|:---|:---|
| **PDF 表格提取** | Docling TableFormer 识别表格结构：colspan/rowspan、表头语义、段标题（UDA/DG 横条）。PubTables-1M 训练，TEDS 96.75% |
| **子行拆分** | PyMuPDF 词坐标 Y 聚类检测无横线子行合并，自动拆为独立 `<tr>` + 虚线分隔 + rowspan 去重 |
| **LLM 数据抽取** | 逐表提取 (Benchmark, Model, Dataset, Metric, Value) 五元组。Prompt 包含去样式 HTML + caption，5 次指数退避重试 |
| **表格自动分类** | LLM 判断 `is_experimental`，非数据表（统计/参数/消融）自动折叠并标注原因，不参与排行榜 |
| **自动打标签** | 每张表标注 datasets + tasks 标签，显示在表格头部 |
| **数据归一化** | Benchmark 别名映射 + Dataset 20+ 变体归一（EPIC-KITCHENS-* → EPIC-KITCHENS）+ 噪声过滤。24 组 → 11 组 |
| **SOTA 排行榜** | 按 Benchmark 分组，跨论文汇聚排名。Alpine.js 客户端排序（点列头升/降序），前三名 🥇🥈🥉 高亮 |
| **Benchmark 说明** | 已 知任务硬编码中文描述，新 Benchmark 首次访问 LLM 自动生成并缓存到 JSON 文件 |
| **数据导出** | 每个排名表一键下载 CSV（UTF-8 BOM，Excel 兼容）或复制 LaTeX `\begin{table}` 源码 |
| **项目隔离** | Session 维度独立管理论文与排行榜，URL 嵌入 Session ID，多项目互不干扰 |
| **Logo & 首页美 化** | 六边形 Hub + 排名柱 Logo，首页统计栏 + 进度环 + 空状态插图 + 渐变色按钮 |

---

## 3. 技术栈

| 组件 | 选型 | 说明 |
|:---|:---|:---|
| 后端 | Django 4.2 + SQLite | 内置 Admin，单文件易备份 |
| 表格提取 | Docling TableFormer + PyMuPDF | IBM 开源，96.75% TEDS |
| LLM | MiniMax M2（可换 OpenAI/Anthropic） | 逐表 JSON 抽取 + 分类 + Benchmark 说明生成 |
| 前端 | Tailwind CSS + Alpine.js + pdf.js + markdown-it | 全 CDN，零构建 |
| 排序 | Alpine.js 客户端排序 | 点击列头即时排序，无刷新 |
| 导出 | 纯前端 Blob / Clipboard API | CSV 下载 + LaTeX 复制 |

**精简设计**：核心引擎仅 2 个文件 — `services/docling_service.py`（~370 行）+ `services/llm_service.py`（~380 行）。

---

## 4. 目录结构

```
BenchHub/
├── benchhub/              # Django 工程配置
│   └── settings.py        # API Key 读环境变量，不硬编码
├── papers/                # 业务 app
│   ├── models.py          # Session / Paper / ExperimentRecord / TableChunk
│   ├── views.py           # 项目 / 论文 / 排行榜视图 + Benchmark 描述三级获取
│   ├── tasks.py           # 异步 pipeline（表格提取 + LLM 抽取）
│   └── urls.py            # 24 条路由，精确可控
├── services/              # 核心引擎（仅 2 个文件）
│   ├── docling_service.py # Docling TableFormer 表格提取 + 子行拆分
│   └── llm_service.py     # LLM 逐表抽取 + Benchmark/Dataset 归一化
├── templates/papers/
│   ├── session_list.html          # 首页（项目卡片 + 统计栏 + 空状态）
│   ├── session_detail.html        # 项目详情（论文列表 + 排行榜入口）
│   ├── leaderboard_list.html      # 排行榜卡片列表
│   ├── leaderboard_detail.html    # 排名表（排序 + CSV/LaTeX 按 钮）
│   ├── review.html                # 论文表格预览（可折叠）
│   └── upload.html                # PDF 上传
├── static/logo.svg        # 项目 Logo
├── docs/BenchHub.pptx     # 项目 PPT（7 页）
├── setup.sh start.sh      # 一键安装 & 启动
└── requirements.txt
```

---

## 5. 核心技术难点

### 5.1 PDF 表格结构识别 (V1→V5)

4 次方案失败，最终 V5 采用 **Docling TableFormer 的 `table_cells` 语义标注**直接遍历生成 HTML：

| 版本 | 方案 | 失败原因 |
|:---|:---|:---|
| V1 | Table Transformer 坐标映射 | 6 层变换链，累积误差 10-20px |
| V2 | 纯 PyMuPDF 词坐标聚类 | 阈值一刀切，字体/行距差异大 |
| V3 | Docling 完整管线 | 计划太乐观，落地时被绕过 |
| V4 | Docling bbox + 坐标重建 | 丢弃了 TableFormer 已有的 col_span/row_section |
| **V5** | **TableFormer cells 直接遍历** | ✅ 3 论文 26 表，0 误伤 |

**核心认知**：表格提取不是"在 PDF 上画框"，而是理解语义结构。TableFormer 已输出 column_header、row_section、col_span、row_span，直接信任即可。

### 5.2 子行拆分

PDF 中无横线分隔的两个物理行被 TableFormer 识别为一个逻辑行 → HTML 挤在同一 `<tr>`。  
**方案**：在 cell bbox 内用 PyMuPDF `get_text("words")` 按 Y 坐标聚类（gap > 4pt → 新子行），同行 ≥70% 多数值 cell 呈现相同簇数才认定。独立 `<tr>` + 虚线 + rowspan 去重。

### 5.3 LLM 智能抽取与分类

同一 LLM 调用完成四件事：提取五元组 + 表格分类（`is_experimental`）+ 打标签（datasets/tasks）+ 过滤原因。Prompt 中提供去样式 HTML + caption，输出结构化 JSON。  
**鲁棒性**：解析失败时 5 次指数退避重试（1s → 2s → 4s → 8s → 16s），JSON 截断时自动补 `]` 修复。  
**增量策略**：仅当该 TableChunk 尚无 records 时写入，避免 LLM 随机性导致覆盖丢失。

### 5.4 名称归一化

同一 Benchmark 被 LLM 写成 "Action Recognition" / "Action Classification" / "EPIC-KITCHENS-100"；同一数据集 EPIC-KITCHENS 有 20+ 种变体（-100/-Test/-Val/-Verb/-Noun/-Action 自由组合）。  
**方案**：别名映射表 + 正则归一化（EPIC-KITCHENS-* / EK / EK100 → EPIC-KITCHENS）+ 噪声黑名单（裸 val/test/overall 丢弃）。24 组归一化为 11 组。

### 5.5 同页多表 Caption 误匹配

PyMuPDF 在表格上下方搜索 "Table N:"，搜索区域覆盖了其他表的 caption。  
**方案**：仅搜索表格**上方** 120pt，取 Y 坐标最靠近表格顶部的匹配。

### 5.6 Benchmark 描述自动生成

已 知 Benchmark（UDA/DG 等 14 个）硬编码中文描述，新 Benchmark 无法提前覆盖。  
**方案**：三级获取 — ① 预定义字典 → ② `benchmark_descriptions.json` 缓存 → ③ LLM 实时生成（聚合数据集名+指标名+caption，生成 1-2 句中⽂说明，自动写入缓存）。首次 ~2 秒，后续秒开。

### 5.7 前端安全与设计

- **JSON 嵌入安全**：使用 Django `json_script` 过滤器替代 `{{ json|safe }}`，`&` 等特殊字符自动转义，避免 HTML 实体解析错误
- **CSV/LaTeX 导出**：纯前端 Blob download + Clipboard API，无后端依赖。CSV 带 BOM 确保 Excel UTF-8 兼容
- **首页设计**：Logo SVG + 四卡统计栏 + 项目进度环 + 空状态插图 + indigo→purple 渐变按钮

---

## 6. 快速开始

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
| 排行榜详情 | 点卡片进入 | 多数据集排名表，列头排序 + CSV/LaTeX 导出 |

---

## 7. 配置与部署

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

## 8. 安全

| 文件 | Git | 说明 |
|:---|:---|:---|
| `benchhub/settings.py` | ✅ | API Key 读环境变量 |
| `.env` | ❌ | 真实 API Key |
| `.env.example` | ✅ | 模板文件 |
| `benchmark_descriptions.json` | ❌ | LLM 生成缓存 |
| `db.sqlite3` | ❌ | 本地数据 |
| `media/` | ❌ | 上传的 PDF |

---

## 9. FAQ

**Q: 解析一篇论文多久？**  
A: 8 页约 2-5 分钟，20 页以上约 5-10 分钟。瓶颈在 LLM 逐表分析。

**Q: 为什么有些表格显示"被过滤"？**  
A: LLM 判断该表非实验对比表（如数据集统计），自动折叠标注原因。可手动展开查看。

**Q: 排行榜数据不对？**  
A: 到 Django Admin (`/admin/`) 编辑 ExperimentRecord，或点"重新解析"重跑。

**Q: 支持 Windows 吗？**  
A: WSL2 推荐。纯 Windows 需 conda 环境并确保 Docling 模型下载路径无误。
