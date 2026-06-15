# PDF 表格提取方案 V3 — 完整计划

## 问题回顾

### V1（Table Transformer 坐标映射）失败的根因

```
PDF文字 → pypdfium2渲染 → Processor resize → 模型输出 → denormalize → scale → PDF坐标
                          1280px              模型内坐标    中间尺寸     图片尺寸   页面坐标
```

6 层坐标变换累积误差 10-20px，cell 文字配不准。检测模型过分割（4 张表被拆成 12 个碎片），caption 匹配混乱。

### V2（纯词聚类）的问题

词坐标聚类在理论上可行，但实操中三个致命缺陷：
- X 间隙阈值无法一刀切（列间 20pt vs 字间 5pt vs 子列间 8pt）
- 多级表头导致列模板不准（Modalities→RGB/Flow/Audio→Verb/Noun/Action 共三层）
- caption 延续行污染表格 body 区域

### 本质问题

**我们在用坐标拼凑表格结构，而不是让模型"看懂"表格。**
PDF 里的每个词坐标都是完美的（PyMuPDF），但把词组装成有意义的行列结构，
本质上是一个"视觉理解"任务，不是坐标聚类任务。

## 候选方案对比

### 方案 A：SmolDocling（256M VLM）⭐ 推荐

| 维度 | 详情 |
|:---|:---|
| **原理** | 端到端视觉语言模型，输入页面图片，输出结构化 DocTags |
| **参数量** | 256M（SigLIP 93M + SmolLM 135M）|
| **显存** | ~0.5 GB，6GB GPU 绰绰有余 |
| **速度** | ~0.35 秒/页（consumer GPU）|
| **表格输出** | OTSL 格式 → 可转 HTML/Markdown，含 row/col span |
| **caption** | 原生支持 caption-figure/table 关联 |
| **开源** | Apache 2.0，HuggingFace 直接下载 |
| **训练数据** | 含图表、表格、公式、代码等专门数据集 |
| **开发方** | IBM Research + Hugging Face（2025.03）|

**优势**：
- 端到端，零坐标映射，不需要检测→结构识别→文字对齐的三段管线
- 像人一样"看"表格，自动理解行列结构、合并单元格、表头层级
- 256M 参数但专门为文档理解训练，精度不输大得多的通用 VLM
- caption 与 table 天然一一对应（输出在同一段 DocTags 内）

**劣势**：
- preview 版本（2025.03），可能有未覆盖的边缘 case
- 输出质量依赖 prompt 设计

### 方案 B：Docling 完整管线（TableFormer）

| 维度 | 详情 |
|:---|:---|
| **原理** | DocLayNet 布局检测 → TableFormer 表格结构识别 → 文字对齐 |
| **优势** | 生产级、久经考验、TableFormer 在 PubTabNet 上 96.75% TEDS |
| **劣势** | 多段模型管线，设置复杂；TableFormer 仍需坐标映射 |

### 方案 C：两阶段——SmolDocling 为主 + Docling 兜底

若 SmolDocling 某页输出异常（表格结构不完整、caption 缺失），退到 Docling 的 TableFormer 管线重试。

## 最终策略：直接用成熟工具，不造轮子

前两轮失败的核心原因：**在写算法，而不是用工具。**
坐标变换、词聚类、间隙检测——这些都是自己写的、未经充分测试的算法。

这一次，全部用现成开源工具。

## 方案：Docling（IBM）

选择 Docling 而非 SmolDocling preview：
- Docling 是 **生产级**（1.0+），久经用户验证
- 底层 TableFormer 在 CVPR 2022 发表，PubTabNet TEDS 96.75%
- 一条命令 `docling mypaper.pdf` 输出 Markdown/JSON/HTML
- 支持多栏布局、全宽/半宽表格、数学公式
- `pip install docling` 即可

```python
from docling.document_converter import DocumentConverter
converter = DocumentConverter()
result = converter.convert("paper.pdf")
# result.document.tables → 每张表的结构化数据
# doc.export_to_html() / doc.export_to_markdown()
```

## 我们只需写 ~50 行胶水代码

BenchHub 需要的只是：
1. PDF → Docling → 提取 tables → 返回 HTML
2. 一个 Django view 包一层 API

表格结构理解、行列识别、caption 匹配、HTML 渲染——Docling 全做了。

## 实施步骤

### Step 1：安装 Docling

```bash
pip install docling
# 模型自动下载（DocLayNet + TableFormer）到 ~/.cache/docling
```

### Step 2：写一个薄封装（~50 行）

`services/docling_service.py`：
- 调 `DocumentConverter.convert(pdf_path)`
- 从 `result.document.tables` 遍历表格
- 每个 table 取 caption + HTML → 返回 JSON

### Step 3：Django view 对接

`extract_tables_api` 调 docling_service → 返回 JSON。

### Step 4：验证

3 篇数据库论文跑一遍，对比 PDF 原文。

## 时间估算

- Step 1：安装 + 模型下载 ~10 分钟
- Step 2-3：50 行胶水代码 ~15 分钟
- Step 4：测试验证 ~10 分钟
- **总计：~35 分钟**
