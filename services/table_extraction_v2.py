"""PDF 表格提取 V2：caption 锚定 + 纯词坐标聚类。

抛弃 Table Transformer 结构模型的坐标映射，只用检测模型定位表格区域，
或者直接用 caption 位置 + 页面布局来划定表格边界，然后用 PyMuPDF 词坐标聚类分行列。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import fitz
import torch
from PIL import Image
from transformers import AutoImageProcessor, TableTransformerForObjectDetection

logger = logging.getLogger(__name__)

# ============== 数据结构 ==============


@dataclass
class Cell:
    row_idx: int
    col_idx: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""
    is_header: bool = False
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)


@dataclass
class ExtractedTable:
    page: int
    caption: str = ""
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    rows: List[List[Cell]] = field(default_factory=list)
    raw_html: str = ""
    raw_markdown: str = ""


# ============== 检测模型（仅用于表格区域检测） ==============

_DET_MODEL = None
_DET_PROCESSOR = None


def _get_det_model():
    global _DET_MODEL, _DET_PROCESSOR
    if _DET_MODEL is None:
        logger.info("Loading table-transformer-detection...")
        _DET_MODEL = TableTransformerForObjectDetection.from_pretrained(
            "microsoft/table-transformer-detection", revision="no_timm"
        )
        _DET_PROCESSOR = AutoImageProcessor.from_pretrained(
            "microsoft/table-transformer-detection", revision="no_timm"
        )
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        _DET_MODEL = _DET_MODEL.to(dev)
        logger.info(f"Detection model ready on {dev}.")
    return _DET_MODEL, _DET_PROCESSOR


# ============== 词坐标工具 ==============


def _get_words(page: fitz.Page) -> List[Dict]:
    """获取页面上所有词，缓存。"""
    if not hasattr(page, "_word_cache"):
        raw = page.get_text("words")
        page._word_cache = [
            {"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3],
             "text": w[4], "cx": (w[0] + w[2]) / 2, "cy": (w[1] + w[3]) / 2}
            for w in raw
        ]
    return page._word_cache


_CITE_RE = re.compile(r'\[[\d,\-\s]+\]')


def _clean_text(text: str) -> str:
    """去引用标记 + 多余空格。"""
    text = _CITE_RE.sub('', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


# ============== Caption 检测 ==============

_TABLE_NUM_RE = re.compile(r'^(\d+)[.:]$')


def _find_all_captions(page: fitz.Page) -> List[Dict]:
    """找出页面上所有 'Table N[:.]' 词对，返回 [(bbox, table_number, text_start_idx)]。

    这对精确匹配 caption，每个表格 1 个。
    """
    words = _get_words(page)
    captions = []
    for i, w in enumerate(words):
        if w["text"].lower() != "table":
            continue
        if i + 1 >= len(words):
            continue
        nxt = words[i + 1]
        m = _TABLE_NUM_RE.match(nxt["text"])
        if not m:
            continue
        if abs(w["cy"] - nxt["cy"]) > 5:
            continue  # 不在同一行

        table_num = int(m.group(1))

        # 收集同行的 caption 文本
        cap_words = [f"Table {table_num}:"]
        cap_y = w["cy"]
        for j in range(i + 2, min(len(words), i + 50)):
            cw = words[j]
            if abs(cw["cy"] - cap_y) > 5:
                break
            cap_words.append(cw["text"])

        caption_text = _clean_text(" ".join(cap_words))

        captions.append({
            "table_num": table_num,
            "text": caption_text,
            "y0": w["y0"],
            "y1": words[i + 1]["y1"],
            "x0": w["x0"],
            "x1": words[i + 1]["x1"],
            "word_idx": i,
            "cy": w["cy"],
        })

    # 去重（同一 table_num 取第一次出现）
    seen = set()
    unique = []
    for c in captions:
        if c["table_num"] not in seen:
            seen.add(c["table_num"])
            unique.append(c)
    return unique


# ============== 表格区域划分 ==============


def _find_table_extents(
    page: fitz.Page, captions: List[Dict]
) -> List[Dict]:
    """根据 caption 位置划分表格纵向范围。

    - 两个相邻 caption 之间 = 前一个 table 的 body 范围
    - 最后一个 caption 下方 2× 表格高度 = 最后一张表
    - 如果 caption 上方有密集词区域 = caption 在下方（少见）
    """
    words = _get_words(page)
    captions_sorted = sorted(captions, key=lambda c: c["cy"])
    page_h = page.rect.height
    page_w = page.rect.width

    table_regions = []
    for ci, cap in enumerate(captions_sorted):
        cap_y = cap["cy"]

        # 下边界：下一个 caption 或页底
        if ci + 1 < len(captions_sorted):
            next_y = captions_sorted[ci + 1]["cy"]
            bottom_y = next_y - 10  # 留 10pt 空隙
        else:
            bottom_y = page_h - 20

        # 默认：表格在 caption 下方
        top_y = cap["y1"] + 8

        # 但如果 caption 下方 30pt 无词而上方有密集词 → 表格在上方
        below_words = [w for w in words if top_y <= w["cy"] <= top_y + 30]
        above_words = [w for w in words if cap_y - 80 <= w["cy"] <= cap["y0"] - 5]
        if not below_words and len(above_words) > 5:
            top_y = max(0, cap["y0"] - 200)
            bottom_y = cap["y0"] - 5

        # 横向范围：看区域内词的 X 分布
        region_words = [w for w in words if top_y <= w["cy"] <= bottom_y]
        if region_words:
            x0 = min(w["x0"] for w in region_words) - 5
            x1 = max(w["x1"] for w in region_words) + 5
        else:
            x0 = cap["x0"] - 10
            x1 = page_w - 10

        table_regions.append({
            "table_num": cap["table_num"],
            "caption": cap["text"],
            "x0": max(0, x0),
            "y0": top_y,
            "x1": min(page_w, x1),
            "y1": bottom_y,
        })

    return table_regions


# ============== 行列聚类核心算法 ==============


def _cluster_words_to_grid(
    region: Dict, page: fitz.Page
) -> Tuple[List[List[Cell]], str]:
    """在给定区域内，纯用词坐标聚类出行和列。

    算法：
    1. 收集区域内所有词
    2. Y 方向：找自然间隙（连续词之间 Y 跳跃 > 行高 50%）→ 行边界
    3. X 方向：每行内找自然间隙 → 列边界
    4. 组装 grid
    """
    words = _get_words(page)
    x0, y0, x1, y1 = region["x0"], region["y0"], region["x1"], region["y1"]

    # 取区域内的词，排序
    region_words = [
        w for w in words
        if x0 - 5 <= w["cx"] <= x1 + 5 and y0 - 3 <= w["cy"] <= y1 + 3
    ]
    if not region_words:
        return [], ""

    region_words.sort(key=lambda w: (w["cy"], w["cx"]))

    # ===== Y 聚类：分行 =====
    # 计算 typ 行高（用词高中位数）
    heights = sorted([w["y1"] - w["y0"] for w in region_words])
    typ_h = heights[len(heights) // 2] if heights else 10

    # 扫描 Y 方向：当连续词的 Y 跳跃 > typ_h * 0.6 时，开启新行
    row_groups: List[List[Dict]] = []
    current_row: List[Dict] = []
    last_cy = None

    for w in region_words:
        if last_cy is not None and (w["cy"] - last_cy) > typ_h * 0.6:
            if current_row:
                row_groups.append(current_row)
            current_row = [w]
        else:
            current_row.append(w)
        last_cy = w["cy"]

    if current_row:
        row_groups.append(current_row)

    if len(row_groups) < 2:
        return [], ""

    # ===== X 聚类：每行内分列 =====
    # 不预设列数，完全由 X 间隙决定
    all_cells: List[List[Cell]] = []

    # 用全表的 X 间隙确定一个"全局列模板"
    # 收集所有词的 X 中心，做密度聚类
    all_x = sorted(set(round(w["cx"], 0) for w in region_words))
    # 找 X 间隙（> typ_h * 2 = 列间分隔）
    col_boundaries = []
    for i in range(1, len(all_x)):
        if all_x[i] - all_x[i - 1] > typ_h * 1.5:
            col_boundaries.append((all_x[i - 1] + all_x[i]) / 2)

    # 用列边界 + 表区域左右边 构成列区间
    col_intervals: List[Tuple[float, float]] = []
    prev = x0
    for b in col_boundaries:
        col_intervals.append((prev, b))
        prev = b
    col_intervals.append((prev, x1))

    # 合并太窄的列（宽 < typ_h）
    merged_intervals: List[Tuple[float, float]] = [col_intervals[0]]
    for lo, hi in col_intervals[1:]:
        if (hi - lo) < typ_h and (merged_intervals[-1][1] - merged_intervals[-1][0]) < typ_h * 3:
            merged_intervals[-1] = (merged_intervals[-1][0], hi)
        else:
            merged_intervals.append((lo, hi))

    n_cols = len(merged_intervals)
    if n_cols < 2:
        return [], ""

    # 填充每行每列
    for ri, row_words in enumerate(row_groups):
        row_cells = []
        for ci, (cl, cr) in enumerate(merged_intervals):
            cell_texts = [
                w["text"] for w in row_words
                if cl - 2 <= w["cx"] <= cr + 2
            ]
            text = _clean_text(" ".join(cell_texts))
            row_cells.append(Cell(
                row_idx=ri, col_idx=ci,
                colspan=1, rowspan=1,
                text=text,
                is_header=(ri == 0),
                bbox=(cl, 0, cr, 0),
            ))
        if row_cells:
            all_cells.append(row_cells)

    # 去空列
    all_cells = _strip_empty_columns(all_cells)

    return all_cells, ""


def _strip_empty_columns(grid: List[List[Cell]]) -> List[List[Cell]]:
    if not grid:
        return grid
    ncols = max(len(r) for r in grid)
    empty_cols = set()
    for ci in range(ncols):
        if all(ci >= len(row) or not row[ci].text.strip() for row in grid):
            empty_cols.add(ci)
    if empty_cols:
        return [[c for ci, c in enumerate(row) if ci not in empty_cols] for row in grid]
    return grid


# ============== HTML / MD 输出 ==============


def _cells_to_html(table: ExtractedTable) -> str:
    if not table.rows:
        return '<p class="text-gray-500 text-sm">(empty)</p>'
    lines = ['<table class="border-collapse border border-gray-300 w-full text-xs">']
    if table.caption:
        lines.append(
            f'<caption class="text-left font-semibold text-gray-700 mb-1 text-sm">'
            f'{table.caption}</caption>'
        )
    for row in table.rows:
        lines.append('<tr>')
        for c in row:
            tag = 'th' if c.is_header else 'td'
            cls = 'border border-gray-300 px-1.5 py-0.5 align-top'
            if c.is_header:
                cls += ' bg-gray-100 font-semibold text-center'
            lines.append(f'  <{tag} class="{cls}">{c.text or "&nbsp;"}</{tag}>')
        lines.append('</tr>')
    lines.append('</table>')
    return '\n'.join(lines)


# ============== 主服务 ==============


class TableExtractionServiceV2:

    def __init__(self):
        self.use_detection = True  # 可选：用检测模型辅助

    def extract_tables(self, pdf_path: str) -> List[ExtractedTable]:
        doc = fitz.open(pdf_path)
        all_tables: List[ExtractedTable] = []

        for page_idx in range(doc.page_count):
            page = doc[page_idx]
            page_tables = self._extract_page(page, page_idx)
            all_tables.extend(page_tables)

        doc.close()
        return all_tables

    def _extract_page(self, page: fitz.Page, page_idx: int) -> List[ExtractedTable]:
        captions = _find_all_captions(page)
        if not captions:
            return []

        regions = _find_table_extents(page, captions)

        tables = []
        for region in regions:
            grid, _ = _cluster_words_to_grid(region, page)
            if not grid or len(grid) < 2:
                continue

            ncols = max(len(r) for r in grid)
            if ncols < 2:
                continue

            table = ExtractedTable(
                page=page_idx + 1,
                caption=region["caption"],
                bbox=(region["x0"], region["y0"], region["x1"], region["y1"]),
                rows=grid,
            )
            table.raw_html = _cells_to_html(table)
            tables.append(table)

        return tables


# 单例
table_extraction_v2 = TableExtractionServiceV2()
