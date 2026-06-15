# BenchHub PPT 大纲

> 截图方法：打开对应页面 → F12 开发者工具 → `Ctrl+Shift+S` 截取可视区域。
> 推荐分辨率：1920×1080，浏览器缩放 100%。

---

## Slide 1: 封面

**标题**：BenchHub — 个人 AI 论文实验数据智能管理平台

**副标题**：上传 PDF → 自动抽取实验数据 → 构建私有 SOTA 排行榜

**底部**：GitHub / 日期 / 作者

> 📸 截图位置：无（纯文字封面）

---

## Slide 2: 项目背景与痛点

**标题**：论文对比表的痛点

| 痛点 | 现状 |
|:---|:---|
| 查数 | 打开 PDF → 翻到实验页 → 找到目标表格 → 肉眼对齐行列 → 抄数字 |
| 敲数 | 手动录入 LaTeX `\begin{tabular}` → 填 Model × Dataset × Metric × Value |
| 对比 | 多篇论文间手动收集、排序、画表 |
| 更新 | 新论文出来 → 全部重来一遍 |

**核心问题**：被 "查数 + 敲数" 环节消耗大量时间，而非"分析结果"。

**解决方案**：全自动的 PDF → 实验数据 → 排行榜 pipeline。

> 📸 无需截图

---

## Slide 3: 产品定位

**标题**：BenchHub 是什么

**三句话**：
1. **PDF 上传即用**：拖拽上传论文 PDF，自动识别表格结构
2. **LLM 智能抽取**：逐表调用大模型，提取 (Benchmark, Model, Dataset, Metric, Value) 五元组
3. **SOTA 排行榜**：多篇论文按 Benchmark 分组汇聚，点击列头即排序

**对标**：Wizwand SOTA Leaderboard（action-recognition-on-epic-kitchens-100-test）

> 📸 **[screenshots/landing.png]** — BenchHub 首页（项目列表）

---

## Slide 4: 技术架构

**标题**：系统架构图

```
┌──────────────────────────────────────────────────────────┐
│                      前端                                  │
│  Tailwind CSS (CDN) + Alpine.js (CDN) + pdf.js (CDN)     │
│  无构建步骤 · 极简部署                                      │
├──────────────────────────────────────────────────────────┤
│                     Django 4.2                             │
│  ┌──────────┬──────────┬──────────┬─────────────────┐    │
│  │ Session  │  Paper   │  Upload  │  Leaderboard    │    │
│  │ 项目隔离  │  论文管理 │  上传 API │  卡片+排名表     │    │
│  └──────────┴──────────┴──────────┴─────────────────┘    │
├──────────────────────────────────────────────────────────┤
│                    核心引擎                                │
│  ┌─────────────────┐  ┌─────────────────────────────┐   │
│  │ docling_service  │  │      llm_service             │   │
│  │ • TableFormer    │  │  • 逐表 JSON 提取             │   │
│  │ • 子行拆分       │  │  • is_experimental 分类       │   │
│  │ • caption 搜索   │  │  • Benchmark/Dataset 归一化   │   │
│  │ • HTML 生成      │  │  • 5 次指数退避重试           │   │
│  └─────────────────┘  └─────────────────────────────┘   │
├──────────────────────────────────────────────────────────┤
│                    数据层                                  │
│  SQLite · 单文件 · 易备份 · Media/ 存放 PDF                │
└──────────────────────────────────────────────────────────┘
```

| 组件 | 选型 | 原因 |
|:---|:---|:---|
| 后端 | Django 4.2 | 快速开发，内置 Admin |
| 数据库 | SQLite | 单文件，个人工具 |
| 表格提取 | Docling TableFormer | PubTables-1M 训练，96.75% TEDS |
| 子行拆分 | PyMuPDF 词坐标 Y 聚类 | 解决无横线子行合并问题 |
| LLM | MiniMax M2 | 可替换为 OpenAI/Anthropic |
| 前端 | Tailwind + Alpine.js | 零构建，CDN 直引 |
| 排行榜排序 | Alpine.js 客户端排序 | 点击即排，无页面刷新 |

---

## Slide 5: 关键技术 1 — PDF 表格结构识别

**标题**：从 PDF 像素到结构化表格

**4 次失败 → V5 方案**：

| 版本 | 方案 | 问题 |
|:---|:---|:---|
| V1 | Table Transformer 坐标映射 | 6 层变换，累积误差 10-20px |
| V2 | 纯 PyMuPDF 词坐标聚类 | 阈值一刀切，子列混淆 |
| V3 | Docling 完整管线 | 落地时被绕过 |
| V4 | Docling bbox + 坐标重建 | 丢弃了 TableFormer 结构数据 |
| **V5** | **Docling table_cells 直接遍历** | ✅ |

**V5 核心思路**：TableFormer 已识别了 `column_header`、`row_section`、`col_span`、`row_span` 等语义标记，直接遍历 `table.data.table_cells` 生成 HTML，不做坐标反推。

> 📸 **[screenshots/table_html.png]** — Article 页一张带表头+段标题的 HTML 表格

---

## Slide 6: 关键技术 2 — 子行拆分

**标题**：解决 "一行当两行用" 的问题

**问题**：TableFormer 将 PDF 中无横线分隔的两个物理行识别为一个逻辑行：
```
┌──────────┬───────────────┐
│ Method   │ Verb Acc (%)  │
├──────────┼───────────────┤
│ Source   │    46.7       │  ← 两个物理行被挤到一个 <tr>
│ Only     │  TBN-TRN      │
└──────────┴───────────────┘
```

**方案**：
1. 检测触发：cell 内含 ≥2 个独立数值
2. Y 聚类：PyMuPDF word 坐标按 Y 坐标聚类（gap > 4pt → 新子行）
3. 一致性检查：同行 ≥70% 多数值 cell 呈现相同簇数才认定子行
4. 独立 `<tr>` + `border-t border-dashed` 虚线分隔
5. rowspan 优化：内容相同的 cell 跨行不重复

> 📸 **[screenshots/subrow.png]** — 子行拆分后的效果（虚线分隔 + rowspan）

---

## Slide 7: 关键技术 3 — LLM 数据抽取与归一化

**标题**：从 HTML 表格到结构化数据

**LLM Prompt 设计**：
- 输入：`Caption: ...` + 去样式的 HTML `<table>` (class/style 属性已 strip)
- 输出：`{"records": [...], "tags": {...}, "is_experimental": bool, "filter_reason": "..."}`
- 段标题识别：`<th>UDA</th>` → 该段内所有 record benchmark = "UDA"

**归一化管道**：

| 步骤 | 处理 |
|:---|:---|
| Benchmark | "Action Classification" → "Action Recognition"（别名表） |
| Benchmark | "Action Recognition on EPIC-KITCHENS" → "Action Recognition"（去 on 后缀） |
| Dataset | "EPIC-KITCHENS-100-Test-Verb" → "EPIC-KITCHENS"（正则归一化） |
| Dataset | "CharadesEgo" → "Charades-Ego"（驼峰补横线） |
| 噪声过滤 | "val" / "test" / "overall" → 丢弃 |

**Session 2 效果**：24 组 → 11 组（归一化合并后）

> 📸 无需截图（纯方案说明）

---

## Slide 8: 关键技术 4 — 非实验表自动过滤

**标题**：哪些表不应该进排行榜？

**LLM 自动判断** `is_experimental` + `filter_reason`：

| 表类型 | is_experimental | filter_reason |
|:---|:---|:---|
| 实验对比表（Method × Metric） | true | — |
| 数据集统计表（Dur/Clips/Texts） | false | "数据集统计信息" |
| 消融实验说明（无数值） | false | "非实验对比表格" |
| 段标题行（仅一个全宽 `<th>`） | false | — |

**前端展示**：非实验表默认折叠，琥珀色标记 + 过滤原因 badge，用户可展开查看。

> 📸 **[screenshots/filter_table.png]** — Article 页，折叠态的非实验表（⚠ 数据集统计信息）

---

## Slide 9: 关键技术 5 — 跨论文排行榜

**标题**：从单篇论文到 SOTA 排名

**数据汇聚流程**：
```
Paper A 记录 ──┐
Paper B 记录 ──┼── 按 (Benchmark, Dataset) 分组 ──→ 模型排名表
Paper C 记录 ──┘
```

**页面结构**：
```
📊 Ego Foundation Models 排行榜  ← 按项目隔离
┌─────────────────────────────────────┐
│ 🎯 Multi-Instance Retrieval         │
│    6 模型 · 2 指标 · 2 篇论文        │
│    🥇 JPoSE (nDCG=55.5)            │  ← 点击进入
├─────────────────────────────────────┤
│ 🎯 NLQ                              │
│    4 数据集 · 5 模型                 │
└─────────────────────────────────────┘
```

**详情页**：客户端 Alpine.js 排序，点击列头 升/降序，🔥 紫色高亮当前排序列，无刷新。

> 📸 **[screenshots/leaderboard_list.png]** — 排行榜卡片列表页
> 📸 **[screenshots/leaderboard_detail.png]** — 排行榜详情页（指标可排序）

---

## Slide 10: 关键技术 6 — Session 隔离与 Anchor 定位

**标题**：项目维度的数据隔离 + 精确定位

**Session 隔离**：不同项目的论文与排行榜完全独立。URL 嵌入 Session ID：
- `/projects/1/leaderboards/` — 项目 1（动作识别）
- `/projects/2/leaderboards/detail/?benchmark=UDA` — 项目 1 的 UDA 排行榜

**Anchor 定位**：排行榜中论文链接 → 跳转到文章页对应表格：
- URL: `/articles/8/#tc-53` → 页面自动滚动到 Table ID=53 卡片

> 📸 无需截图

---

## Slide 11: 使用说明 — 完整流程

**标题**：从 PDF 到排行榜的完整流程

```
Step 1             Step 2              Step 3              Step 4
创建项目           上传 PDF            等待解析             查看排行榜
┌──────────┐      ┌──────────┐        ┌──────────┐        ┌──────────┐
│ + 新建项目│  →   │ 拖拽 PDF │   →    │ 自动提取  │   →    │ 🏆 排行榜│
│ 填写名称  │      │ 上传论文  │        │ + LLM 抽取│        │ 排序对比  │
│ 填写描述  │      │          │        │ 2-10 分钟  │        │          │
└──────────┘      └──────────┘        └──────────┘        └──────────┘
```

**各环节**：
1. **创建项目**：首页 → "+ 新建项目" → 填写名称（如 "动作识别"）
2. **上传 PDF**：项目页 → "+ 上传论文" → 选文件 → 自动启动后台异步任务
3. **等待解析**：前端轮询状态（提取文本 → 调用 LLM → 完成），2-10 分钟取决于论文大小
4. **查看结果**：点击 "🏆 排行榜" → 按 Benchmark 分组 → 点击列头排序

**重新解析**：项目页每篇论文有 "重新解析" 按钮 → 清空旧数据 → 全流程重跑。

> 📸 **[screenshots/upload.png]** — 上传页面
> 📸 **[screenshots/project_detail.png]** — 项目页（论文列表 + 状态 + 排行榜入口）
> 📸 **[screenshots/parsing_status.png]** — 解析中的状态展示

---

## Slide 12: 使用说明 — 页面导航

**标题**：页面结构总览

```
首页 /                   项目列表（可搜索）
  └─ /projects/<id>/     项目详情（论文列表 + 上传 + 排行榜入口）
       ├─ /upload/       上传 PDF
       ├─ /leaderboards/ 排行榜卡片列表
       │    └─ /detail/  单个 Benchmark 排名表（Alpine.js 排序）
       └─ /articles/<id>/ 论文表格预览（可折叠 + 过滤标记）
```

**角色**：

| 页面 | 用途 |
|:---|:---|
| 首页 | 查看所有项目，搜索 |
| 项目页 | 管理论文，上传，进入排行榜 |
| 排行榜列表 | 查看项目内所有 Benchmark 卡片 |
| 排行榜详情 | 具体某个 Benchmark 下的排名表 |
| 论文详情 | 预览提取的表格，检查过滤状态 |
| Admin | 后台编辑 Session / Paper / ExperimentRecord |

> 📸 **[screenshots/article_detail.png]** — 论文详情页（表格预览 + 标签 + 折叠）

---

## Slide 13: 部署说明

**标题**：本地 / 服务器部署

### 环境要求

```bash
Python 3.10+
2 GB 内存（Docling 模型加载）
SQLite（无额外数据库依赖）
```

### 一键安装（推荐）

```bash
git clone https://github.com/DemoStoneG/BenchHub.git
cd BenchHub
cp .env.example .env          # 编辑 .env 填入 MiniMax API Key
bash setup.sh                 # 自动：创建 venv → pip install → migrate
bash start.sh                 # 启动服务器 → http://localhost:8000
```

### 手动安装

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
export MINIMAX_API_KEY='sk-cp-your-key'   # 或者写入 ~/.bashrc
python manage.py runserver 0.0.0.0:8000
```

### 配置 API Key

推荐使用环境变量（不硬编码）：`export MINIMAX_API_KEY='...'` 或复制 `.env.example` → `.env` 填入 Key。换 OpenAI / Anthropic 编辑 `services/llm_service.py` 的 `_call_llm` 方法。

### 开发 + 生产双实例

```bash
git clone ~/BenchHub ~/benchhub-app    # 生产实例（数据库独立）
cd ~/benchhub-app && bash start.sh 9000 # 端口 9000
cd ~/BenchHub && bash start.sh 8000     # 开发环境 8000
```

### 生产部署

```python
# benchhub/settings.py
DEBUG = False
ALLOWED_HOSTS = ['your-domain.com']
SECRET_KEY = '<new-random-key>'
```

换 `gunicorn` / `uWSGI` 代替 `runserver`，配合 nginx 反向代理 + supervisor/systemd 进程守护。

> 📸 无需截图

---

## Slide 14: 项目状态 — 已完成

**标题**：当前完成度一览

| 模块 | 功能 | 数据 | 状态 |
|:---|:---|:---|:---|
| PDF 表格提取 | Docling TableFormer V5 + 子行拆分 | 4 论文 32 张表，0 误伤 | ✅ |
| LLM 数据抽取 | MiniMax M2 逐表抽取 5 元组 | 600+ 条记录 | ✅ |
| 表格分类 | is_experimental 自动判断 | 非实验表折叠 | ✅ |
| 名称归一化 | Benchmark/Dataset 变体合并 | 24→11 组 | ✅ |
| 项目隔离 | Session 维度独立管理 | 3 个项目 | ✅ |
| 排行榜列表 | 卡片 × Benchmark 分组 | 15 个排行榜组 | ✅ |
| 排行榜详情 | 多数据集排名表 + 客户端排序 | Alpine.js | ✅ |
| 论文详情 | 表格 HTML 预览 + 折叠 | 88% 页面缩减 | ✅ |
| 代码清理 | 死代码 + 旧方案删除 | -2700+ 行 | ✅ |

---

## Slide 15: 思考 1 — 为什么 V1-V4 都失败了

**标题**：从 4 次失败中得到的教训

### V1-V4 失败的根本原因

| 版本 | 路向 | 为什么失败 | 教训 |
|:---|:---|:---|:---|
| V1 | Table Transformer 坐标映射 | 6 层变换链，每层累积误差 | **坐标反推是死路**，模型输出的空间信息和结构信息要一起用 |
| V2 | 纯 PyMuPDF 词坐标聚类 | 阈值一刀切，不同论文的字体/行距差异巨大 | **纯 rule-based 不可行**，必须结合语义理解 |
| V3 | Docling 完整管线 | 计划 50 行胶水代码，实际落地时被跳过 | **计划太乐观**，低估了 Docling API 的学习成本 |
| V4 | Docling bbox + 坐标重建 | 丢弃了 TableFormer 已经做好的 col_span/row_section 等语义标记 | **不要扔掉模型已有的推理结果** |

### 核心认知

> 表格提取的本质不是"在 PDF 上画框"，而是**理解表格的语义结构**。
> TableFormer 已经做了 90% 的工作 — column_header、row_section、col_span、row_span — 这些是黄金。
> V5 的突破在于：放弃"自己重建"，改为"直接信任模型的语义输出，只在必要时做局部修正（子行拆分）"。

### 如果重来一次

- 第一天就用 Docling 的 `table.data.table_cells` 遍历，不做任何坐标变换
- 子行拆分作为独立模块，不影响主流程
- 相信模型的 col_span / row_span / row_section，不做反推

---

## Slide 16: 思考 2 — LLM 在 pipeline 中的角色

**标题**：LLM 该做 LLM 擅长的事

### 设计原则

| LLM 能做好 | LLM 不该做 |
|:---|:---|
| 从表格中抽取 (model, dataset, metric, value) 元组 ✅ | 识别表格边框和结构（那是 TableFormer 的事） |
| 判断表格类型（实验对比 vs 数据集统计） ✅ | 生成 HTML（那是规则代码的事） |
| 推断 Benchmark 名称（从 caption） ✅ | 处理坐标计算（那是 PyMuPDF 的事） |
| 区分段标题（UDA vs DG） ✅ | |

### LLM 的局限性 —— 实际踩坑

1. **输出不稳定**：同一张表两次调用，records 数量从 24 到 84 到 0 不等 → 采用"逐表增量"策略，有数据就不覆盖
2. **JSON 格式偶尔出错**：做过鲁棒解析（补 `]`、截断修复、逐对象提取），LLM 返回的 JSON 90% 合法，10% 需要 remedial
3. **自由文本归一化**：dataset 名写 "EK100" / "EK" / "EPIC-KITCHENS-100" / "EPICKITCHENS" 等 20+ 变体 → 后处理归一化是必需的，不能指望 LLM 统一
4. **成本**：8 张表 × 5 次重试 = 最多 40 次 API 调用，每次 ~30s → 总耗时 2-10 分钟

### 结论

> LLM 是 pipeline 的"智能插件"，不是主力。主力是 TableFormer（结构）+ 规则（归一化）+ Alpine.js（排序）。LLM 只做最难的那 5%：理解表格在说什么。

---

## Slide 17: 思考 3 — 什么做对了，什么还差得远

**标题**：项目反思

### ✅ 做得对的决定

| 决策 | 原因 |
|:---|:---|
| 用 Docling 而不是自己搭 | 省了 6 个月的 Table Transformer 调参 |
| 前端零构建（CDN 直引） | 个人工具不需要 Webpack/Vite |
| SQLite 而非 PostgreSQL | 单文件，`scp` 就能备份 |
| Django Admin 保留 | 后台直接改数据，调试时非常有用 |
| 先做功能再清理 | 功能跑通后才删除 dead code，避免误删 |
| 逐表增量 LLM | 不会因为一次失败覆盖之前的数据 |

### ❌ 还需要改进的

| 问题 | 现状 | 影响 |
|:---|:---|:---|
| LLM 抽取偶尔遗漏 | 有些表 0 records，需要重新解析 | 用户需要点 "重新解析" 2-3 次 |
| 硬编码基准名映射 | `BENCHMARK_DESCRIPTIONS` 字典硬编码 | 新 Benchmark 出现时没有描述 |
| 无 Excel/CSV 导出 | 排行榜数据不能下载 | 用户只能看不能带走 |
| 前端无响应式设计 | 最小宽度依赖 overflow-x | 手机端体验差 |
| Docling 依赖重 | `pip install docling` 下载 ~2GB 模型文件 | 安装慢，不适合轻量部署 |

---

## Slide 18: 未来计划 — 短期（1-2 周）

**标题**：立刻可以做的改进

| 优先级 | 功能 | 说明 | 工作量 |
|:---|:---|:---|:---|
| P0 | LaTeX 导出 | 排行榜数据一键生成 `\begin{tabular}` | 小（恢复旧 latex_service 逻辑） |
| P0 | Excel/CSV 导出 | 排行榜表格下载 | 小 |
| P1 | Benchmark 描述扩展 | 从 TableChunk caption 自动提取说明 | 中 |
| P1 | LLM 结果缓存 | 相同 HTML 不重复调 LLM | 中 |
| P2 | PDF 侧栏预览 | pdf.js 在文章页左侧展示原文 | 中（旧代码有基础） |

---

## Slide 19: 未来计划 — 中期（1-3 月）

**标题**：让排行榜真正有用

### 核心目标：对标 Wizwand

```
当前 BenchHub                             目标 Wizwand 体验
┌────────────────────┐                   ┌─────────────────────────┐
│ 排行榜卡片列表      │                   │ 📈 趋势折线图             │
│ 点击进入排名表      │        →          │ 📊 排名表（分页）          │
│ 客户端排序          │                   │ 📄 侧边栏（SOTA 论文卡片） │
│                    │                   │ 🔗 相关 Benchmark 链接     │
└────────────────────┘                   └─────────────────────────┘
```

| 功能 | 说明 |
|:---|:---|
| **趋势图** | Plotly/ECharts 嵌入，横轴时间、纵轴指标，可切换多指标线 |
| **SOTA 高亮** | 顶部大号数字 + 对应模型/论文 |
| **方法超链接** | 模型名 → 论文页 / arXiv / GitHub |
| **分页** | 模型 >20 时分页展示 |
| **论文卡片** | 侧边栏展示当前 SOTA 论文信息 |
| **Abstract 面板** | 论文页附 LLM 自动提取的摘要 |

---

## Slide 20: 未来计划 — 长期（3-12 月）

**标题**：从个人工具到社区平台

### 技术进化

| 阶段 | 架构 | 场景 |
|:---|:---|:---|
| 现在 | Django + SQLite，单机 | 个人研究者 |
| Phase 1 | Django + PostgreSQL + Celery | 实验室内部多用户 |
| Phase 2 | Django REST API + React/Vue 前端 | Web 公开服务 |
| Phase 3 | arXiv API 自动爬取 + 批量入库 + 社区编辑 | 论文一发表就自动上榜 |

### 关键挑战

| 挑战 | 思路 |
|:---|:---|
| 多 LLM 后端 | 抽象 LLMBackend 基类，OpenAI/Anthropic/MiniMax 可插拔 |
| 表格提取失败率 | 论文格式差异大，增加 fallback 策略（camelot → docling → 手动标注） |
| 社区贡献 | 用户可标注 "这条数据是错的"，类似 Wikipedia 的编辑模型 |
| 数据版权 | PDF 原文不公开，只公开提取的元数据（model / metric / value） |
| 成本控制 | 批量调用时用更便宜的模型（如 GPT-4o-mini），缓存命中不再调用 |

### 长尾场景

- **学术会议投稿**：上传论文 → 自动生成对比表 LaTeX 代码，直接贴到 `.tex` 文件
- **Reviewer 审查**：上传投稿 PDF → 自动提取声称的 SOTA 数据 → 与真实排行榜对比 → 发现 "cherry-picking"
- **Meta-analysis**：聚合所有论文在某一 Benchmark 上的历史趋势，自动生成 survey figure

---

## Slide 21: 总结

**标题**：BenchHub = PDF → 实验数据 → 排行榜，全自动

| 维度 | 成果 |
|:---|:---|
| **自动化** | 上传 PDF 后无需任何手动操作，表格提取 + LLM 抽取 + 归一化 + 排行榜全自动 |
| **准确率** | Docling TableFormer V5 方案，3 论文 26 张表 0 误伤 |
| **代码质量** | services 目录从 9 个文件精简到 2 个（docling_service + llm_service），-2700+ 行 |
| **对标** | 排行榜页面对标 Wizwand SOTA Leaderboard，客户端排序、模型高亮、中文说明 |
| **数据积累** | 4 篇论文 → 600+ 条实验数据 → 3 个项目 15 个排行榜组，跨论文汇聚 |

**核心理念**：让研究者从 "查数 + 敲数" 中解放出来，专注于分析结果。

**核心教训**：相信模型的语义输出，用 LLM 做最后 5% 的智能判断，不要 invent what already works。

---

## 截图清单

| 文件名 | 内容 | 页面 URL |
|:---|:---|:---|
| `screenshots/landing.png` | 首页项目列表 | `http://127.0.0.1:8000/` |
| `screenshots/project_detail.png` | 项目详情页 | `http://127.0.0.1:8000/projects/2/` |
| `screenshots/upload.png` | 上传 PDF | `http://127.0.0.1:8000/projects/2/upload/` |
| `screenshots/article_detail.png` | 论文表格预览 | `http://127.0.0.1:8000/articles/8/` |
| `screenshots/table_html.png` | 带表头+段标题的 HTML 表格 | 同上，展开 Table 1 |
| `screenshots/filter_table.png` | 非实验表折叠状态 | 同上，非实验表折叠态 |
| `screenshots/subrow.png` | 子行拆分效果 | Paper 7 Table 1（有虚线分隔的行） |
| `screenshots/leaderboard_list.png` | 排行榜卡片列表 | `http://127.0.0.1:8000/projects/2/leaderboards/` |
| `screenshots/leaderboard_detail.png` | 排行榜排序表 | `http://127.0.0.1:8000/projects/2/leaderboards/detail/?benchmark=Multi-Instance%20Retrieval` |
| `screenshots/parsing_status.png` | 解析中的状态 | 上传 / 重解析后的等待状态 |
