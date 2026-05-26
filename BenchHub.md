# BenchHub - 个人 AI 论文实验数据管理工具 (MVP 规格)

## 1. 产品定位
一个专门为研究人员/开发者设计的本地化工具。用户通过上传论文，构建属于自己的、私有的 SOTA 对比库。
*   **私有化**：数据存储在本地/私有服务器，不强制公开。
*   **工具化**：核心目标是减少写论文对比表时的手动“查数”和“敲数”时间。

## 2. 基础功能流程
基础版将实现一个闭环的“提取-存储-对比”流程：

1.  **上传与预处理**：上传 PDF，系统调用 `Marker` 将其转换为 Markdown。
2.  **AI 智能提取**：利用 LLM (GPT-4o-mini) 识别 MD 中的表格，提取 `(Model, Dataset, Metric, Value)` 元组。
3.  **人工校验 (Human-in-the-Loop)**：系统展示提取结果，用户对照 PDF 原文手动修正（这是基础功能的核心，确保数据准确）。
4.  **对比视图**：用户自主勾选几篇论文，系统自动生成横向对比表。
5.  **导出**：一键生成 LaTeX 格式的表格代码。

## 3. 技术架构 (简化版)

| 组件         | 选型                         | 理由                                               |
| :----------- | :--------------------------- | :------------------------------------------------- |
| **后端框架** | **Django 4.2**               | 快速开发，内置 Admin 方便用户直接在后台改数。      |
| **数据库**   | **SQLite**                   | 个人工具无需复杂配置，单文件易备份，查询性能足够。 |
| **PDF 解析** | **Marker-pdf**               | 目前开源界对学术论文双栏排版处理最好的工具。       |
| **异步处理** | **Django-Q2**                | 比 Celery 轻量，直接在 Django 进程中管理解析任务。 |
| **前端**     | **Tailwind CSS + Alpine.js** | 极简开发，无需构建复杂的 React/Vue 环境。          |

---

## 4. 核心功能规格说明

### 4.1 论文上传与解析 (Upload & Parse)
*   **输入**：PDF 文件上传。
*   **处理**：
    *   调用 `marker` 命令行将 PDF 转为 `output.md`。
    *   将 `output.md` 喂给 LLM，提示词（Prompt）约束其仅输出 JSON 格式的表格数据。
*   **状态反馈**：前端通过轮询显示：`解析中 (Step 1/2)...`

### 4.2 校验编辑器 (The Editor)
这是用户停留最久的地方：
*   **界面布局**：
    *   **左侧**：PDF 预览窗口（定位到实验章节）。
    *   **右侧**：可编辑的表格。
*   **功能**：用户可以增删行（Model）和列（Metric），点击保存后正式入库。

### 4.3 个人对比仪表盘 (Personal Dashboard)
*   **论文列表**：展示已解析的所有论文。
*   **自由勾选**：用户在列表勾选想对比的论文（如 Llama3, Qwen2, Gemma2）。
*   **自动对齐**：系统根据 `Dataset` 字段，把相同数据集的数据排列在一起。
*   **LaTeX 导出**：下方实时生成 `\begin{tabular}...` 代码块。

---

## 5. 核心数据库模型 (models.py)

```python
from django.db import models

class Paper(models.Model):
    title = models.CharField(max_length=500)
    arxiv_id = models.CharField(max_length=50, blank=True)
    local_pdf = models.FileField(upload_to='papers/')
    raw_markdown = models.TextField(blank=True) # 存储解析后的MD
    created_at = models.DateTimeField(auto_now_add=True)

class ExperimentRecord(models.Model):
    """一条具体的实验数据"""
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='results')
    dataset = models.CharField(max_length=100) # 归一化后的名字，如 "MMLU"
    model_name = models.CharField(max_length=100) # 论文里的模型名
    metric = models.CharField(max_length=50)     # 指标，如 "Acc"
    value = models.FloatField()
    is_verified = models.BooleanField(default=False) # 用户是否校对过
```

---

## 6. 基础版实现难点与对策

### 6.1 解决“幻觉”：强制校验
*   **对策**：LLM 提取后，不直接进入对比库，而是状态设为 `unverified`。强制引导用户进入校验页确认一次。

### 6.2 解决“指标不一”：手动合并
*   **对策**：在对比视图中，如果用户发现系统把 `Accuracy` 和 `Acc` 认成了两个指标，提供一个简单的 UI 按钮：“合并选中列”。

### 6.3 Marker 的环境配置
*   **对策**：Marker 需要较多显存或 CPU。作为个人工具，建议在 `settings.py` 中配置一个开关：使用本地 Marker 或是调用某个解析 API（如 Docling 的远程实例）。

---

## 7. 第一阶段开发计划 (MVP 路线图)

*   **Step 1 (后端)**：搭建 Django 工程，实现 `Paper` 模型和文件上传。
*   **Step 2 (解析)**：集成 `marker` 脚本，编写 Python 函数实现 `PDF -> MD -> JSON` 的 pipeline。
*   **Step 3 (前端)**：做一个最简单的表格列表页，展示解析出的 JSON。
*   **Step 4 (功能)**：实现简单的对比逻辑——根据 `dataset` 字段聚合数据。
*   **Step 5 (导出)**：编写一个简单的字符串模板，将数据转化为 LaTeX Table。

这个方案移除了所有社区交互、点赞、权限等复杂逻辑，专注于**“把 PDF 里的数字快速、准确地变成我自己的对比表”**。