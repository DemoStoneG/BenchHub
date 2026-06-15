"""Table Transformer 表格提取服务。

两阶段管线：
1. Detection Model (microsoft/table-transformer-detection) → 页面图片 → 每张表的 bbox
2. Structure Recognition Model (microsoft/table-transformer-structure-recognition) → 裁切表格图 → cells (row/col bbox)
3. 用 PyMuPDF 坐标匹配取原生文字（无需 OCR）
"""

from __future__ import annotations

import io
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import numpy as np
import pypdfium2 as pdfium
import torch
from PIL import Image
from transformers import AutoImageProcessor, TableTransformerForObjectDetection

logger = logging.getLogger(__name__)

# ============== 数据结构 ==============


@dataclass
class Cell:
    """单个表格单元格"""
    row_idx: int
    col_idx: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""
    is_header: bool = False
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)  # (x0, y0, x1, y1) in page coords


@dataclass
class ExtractedTable:
    """一张提取出的表格"""
    page: int
    table_index: int  # 该页中的第几张表
    caption: str = ""
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)  # 页面绝对坐标
    rows: List[List[Cell]] = field(default_factory=list)
    raw_html: str = ""
    raw_markdown: str = ""


# ============== 模型加载（单例） ==============

_MODEL_REGISTRY: Dict[str, object] = {}


def _load_model_safe(model_name: str, revision: str = "no_timm"):
    """加载 Table Transformer 模型 + processor。"""
    model = TableTransformerForObjectDetection.from_pretrained(model_name, revision=revision)
    processor = AutoImageProcessor.from_pretrained(model_name, revision=revision)
    return model, processor


def _get_detection_model():
    if "det_model" not in _MODEL_REGISTRY:
        logger.info("Loading table-transformer-detection...")
        model, processor = _load_model_safe("microsoft/table-transformer-detection")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        _MODEL_REGISTRY["det_model"] = model
        _MODEL_REGISTRY["det_processor"] = processor
        logger.info(f"Detection model loaded on {device}.")
    return _MODEL_REGISTRY["det_model"], _MODEL_REGISTRY["det_processor"]


def _get_structure_model():
    if "str_model" not in _MODEL_REGISTRY:
        logger.info("Loading table-transformer-structure-recognition...")
        model, processor = _load_model_safe(
            "microsoft/table-transformer-structure-recognition",
            revision="no_timm",
        )
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        _MODEL_REGISTRY["str_model"] = model
        _MODEL_REGISTRY["str_processor"] = processor
        logger.info(f"Structure model loaded on {device}.")
    return _MODEL_REGISTRY["str_model"], _MODEL_REGISTRY["str_processor"]


# ============== 推理函数 ==============


def _render_page_image(doc: fitz.Document, page_idx: int, scale: float = 2.0) -> Image.Image:
    """用 pypdfium2 渲染 PDF 页面为 PIL Image。

    scale=2.0 ≈ 144 DPI，兼顾检测精度与推理速度。
    """
    pdf_doc = pdfium.PdfDocument(doc.name)
    pil_img = pdf_doc[page_idx].render(scale=scale).to_pil()
    pdf_doc.close()
    return pil_img


def _detect_tables(image: Image.Image, confidence_threshold: float = 0.7) -> List[Dict]:
    """检测页面图片中所有表格区域。

    Returns: [{"bbox": (x0,y0,x1,y1), "score": float}, ...]
    坐标相对于原图尺寸 (pixels)。
    """
    model, processor = _get_detection_model()
    device = next(model.parameters()).device

    # 预处理（processor 可能 resize），记录处理后尺寸用于坐标映射
    inputs = processor(images=image, return_tensors="pt")
    proc_h, proc_w = inputs["pixel_values"].shape[-2:]
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)

    # 以 processor 内部尺寸 denormalize
    target_sizes = torch.tensor([[proc_h, proc_w]]).to(device)
    results = processor.post_process_object_detection(
        outputs, threshold=confidence_threshold, target_sizes=target_sizes
    )[0]

    # 映射回原图坐标
    orig_w, orig_h = image.size
    scale_x = orig_w / proc_w
    scale_y = orig_h / proc_h

    tables = []
    for score, label_id, box in zip(results["scores"], results["labels"], results["boxes"]):
        label_str = model.config.id2label[label_id.item()]
        if "table" in label_str.lower() and "rotated" not in label_str.lower():
            x0, y0, x1, y1 = box.tolist()
            tables.append({
                "bbox": (x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y),
                "score": score.item(),
            })
    return tables


def _recognize_structure(
    image: Image.Image, confidence_threshold: float = 0.5
) -> Dict[str, List[Dict]]:
    """识别表格图片中的行列结构。

    Returns:
        {"rows": [...], "columns": [...], "headers": [...], "spanning_cells": [...]}
    坐标相对于输入图片 (pixels)。
    """
    model, processor = _get_structure_model()
    device = next(model.parameters()).device

    inputs = processor(images=image, return_tensors="pt")
    proc_h, proc_w = inputs["pixel_values"].shape[-2:]
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)

    # 以 processor 内部尺寸 denormalize
    target_sizes = torch.tensor([[proc_h, proc_w]]).to(device)
    results = processor.post_process_object_detection(
        outputs, threshold=confidence_threshold, target_sizes=target_sizes
    )[0]

    # 映射回原图坐标
    orig_w, orig_h = image.size
    scale_x = orig_w / proc_w
    scale_y = orig_h / proc_h

    rows, columns, headers, spanning_cells = [], [], [], []
    for score, label_id, box in zip(results["scores"], results["labels"], results["boxes"]):
        label_str = model.config.id2label[label_id.item()]
        x0, y0, x1, y1 = box.tolist()
        item = {
            "bbox": (x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y),
            "score": score.item(),
        }
        if label_str == "table row":
            rows.append(item)
        elif label_str == "table column":
            columns.append(item)
        elif label_str == "table spanning cell":
            spanning_cells.append(item)
        elif label_str in ("table column header", "table projected row header"):
            headers.append(item)

    return {
        "rows": rows, "columns": columns,
        "headers": headers, "spanning_cells": spanning_cells,
    }


# ============== 核心算法：结构元素 → 网格 ==============


def _get_page_words(page: fitz.Page) -> List[Dict]:
    """获取页面所有词的坐标，缓存于 page 对象上。"""
    if not hasattr(page, "_word_cache"):
        words = page.get_text("words")
        page._word_cache = [
            {"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3],
             "text": w[4], "cx": (w[0] + w[2]) / 2, "cy": (w[1] + w[3]) / 2}
            for w in words
        ]
    return page._word_cache


def _clean_cell_text(text: str) -> str:
    """清理 cell 文本：去除引用标记 [1] [1,2] [1-3]、多余空白、行内换行。"""
    import re as _re
    # 去除引用标记: 一个或多个 [数字] 或 [数字, 数字] 或 [数字-数字]
    # 也处理单独的编号引用如 "[23]" 跟在代码名后面
    text = _re.sub(r'\[[\d,\-\s]+\]', '', text)
    # 多空格 → 单空格
    text = _re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _boxes_to_grid(
    rows: List[Dict],
    columns: List[Dict],
    headers: List[Dict],
    table_image: Image.Image,
    page: fitz.Page,
    table_bbox_page: Tuple[float, float, float, float],
) -> List[List[Cell]]:
    """用结构模型的列框定列边界 + 词坐标分行的混合方法。

    1. 列边界: 用结构模型 columns 检测框 → 映射到页面坐标 → 定 n 个列 bin
    2. 行边界: 用结构模型 row count → 等分 Y 范围 → 聚类词到行
    3. 每列内用 PyMuPDF 词坐标精准取字
    """
    n_rows = len(rows)
    if n_rows < 1 or len(columns) < 2:
        return []

    tx0, ty0, tx1, ty1 = table_bbox_page
    img_w, img_h = table_image.size

    # ===== 列边界: 从结构模型 column boxes 映射到页面坐标 =====
    cols_sorted = sorted(columns, key=lambda c: c["bbox"][0])
    scale_x = (tx1 - tx0) / img_w
    scale_y = (ty1 - ty0) / img_h

    # 提取每列在页面坐标中的 X 范围
    col_bounds_px: List[Tuple[float, float]] = []  # (x_left, x_right) in page pts
    for c in cols_sorted:
        bx0, by0, bx1, by1 = c["bbox"]
        page_x0 = tx0 + bx0 * scale_x
        page_x1 = tx0 + bx1 * scale_x
        col_bounds_px.append((page_x0, page_x1))

    # 合并极度重叠的列 (< 30% 独立宽度)
    merged: List[Tuple[float, float]] = [col_bounds_px[0]]
    for x0, x1 in col_bounds_px[1:]:
        prev_x0, prev_x1 = merged[-1]
        overlap = min(prev_x1, x1) - max(prev_x0, x0)
        w_a = prev_x1 - prev_x0
        w_b = x1 - x0
        if w_a > 0 and w_b > 0 and overlap / min(w_a, w_b) > 0.7:
            merged[-1] = (min(prev_x0, x0), max(prev_x1, x1))
        else:
            merged.append((x0, x1))
    col_bounds_px = merged
    n_cols = len(col_bounds_px)

    # ===== 行边界: Y 方向等分 + 词聚类 =====
    all_words = _get_page_words(page)
    table_words = [
        w for w in all_words
        if tx0 - 8 <= w["cx"] <= tx1 + 8 and ty0 - 5 <= w["cy"] <= ty1 + 5
    ]
    if len(table_words) < n_cols:
        return []

    y_min = min(w["cy"] for w in table_words)
    y_max = max(w["cy"] for w in table_words)
    y_step = max((y_max - y_min) / n_rows, 1.0)

    row_bins: dict = {}
    for w in table_words:
        r = min(int((w["cy"] - y_min) / y_step), n_rows - 1)
        row_bins.setdefault(r, []).append(w)

    row_y_medians = sorted(
        [(ri, sum(w["cy"] for w in ws) / len(ws)) for ri, ws in row_bins.items()],
        key=lambda x: x[1]
    )

    # ===== 组装网格: 每行 × 每个列边界 = 一个 cell =====
    grid: List[List[Cell]] = []
    for rank, (ri, _) in enumerate(row_y_medians):
        row_words = row_bins[ri]
        row_cells = []

        for ci, (cx0, cx1) in enumerate(col_bounds_px):
            # 取该列 X 范围内的所有词
            cell_words = [w["text"] for w in sorted(row_words, key=lambda w: w["cx"])
                          if cx0 - 2 <= w["cx"] <= cx1 + 2]
            text = _clean_cell_text(" ".join(cell_words))
            row_cells.append(Cell(
                row_idx=rank, col_idx=ci,
                colspan=1, rowspan=1,
                text=text,
                is_header=(rank == 0),
                bbox=(cx0, 0, cx1, 0),
            ))
        if row_cells:
            grid.append(row_cells)

    # 去空列
    return _remove_empty_columns(grid)


def _deduplicate_captions(tables: List[ExtractedTable]) -> List[ExtractedTable]:
    """同页内，同一个 caption 只保留给 Y 距离最近的表格，其余清空。"""
    from collections import defaultdict
    cap_map: dict = defaultdict(list)  # caption → [(table, dist_to_caption)]
    for t in tables:
        if t.caption:
            dist = abs((t.bbox[1] + t.bbox[3]) / 2 - 0)  # placeholder
            cap_map[t.caption].append(t)

    # 对于重复的 caption，只保留表格 Y 中心离 caption 最近的那个
    for cap, tlist in cap_map.items():
        if len(tlist) <= 1:
            continue
        # 计算每个表格 Y 中心，保留最小者
        tlist.sort(key=lambda t: t.bbox[1])  # 用表格顶部排序
        best = tlist[0]
        for t in tlist[1:]:
            t.caption = ""
            t.raw_html = _cells_to_html(t)
            t.raw_markdown = _cells_to_markdown(t)
    return tables


def _remove_empty_columns(grid: List[List[Cell]]) -> List[List[Cell]]:
    """去除完全空的末尾列。"""
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


def _is_chart_or_figure(table: ExtractedTable) -> bool:
    """启发式判断检测到的"表格"是否实际上是图表。

    图表特征：
    - 行列极少（< 3 行 或 < 3 列）
    - 文字量极少（avg < 3 chars/cell）
    - 大量空 cell（> 60%）
    """
    if not table.rows:
        return True
    nrows = len(table.rows)
    ncols = max(len(r) for r in table.rows)
    if nrows < 3 or ncols < 3:
        return True
    total_chars = sum(len(c.text) for row in table.rows for c in row)
    total_cells = nrows * ncols
    empty_cells = sum(1 for row in table.rows for c in row if not c.text.strip())
    avg_chars = total_chars / max(1, total_cells)
    empty_ratio = empty_cells / max(1, total_cells)
    return avg_chars < 2.0 or empty_ratio > 0.7


def _boxes_y_overlap(a: Tuple, b: Tuple) -> float:
    """两个 bbox 在 Y 方向的重叠比例（用于判断 row 是否与 header 框重叠）。"""
    y_overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    a_h = a[3] - a[1]
    if a_h <= 0:
        return 0.0
    return y_overlap / a_h


def _boxes_overlap(a: Tuple, b: Tuple) -> float:
    """两个 bbox 的重叠面积 / min(a面积, b面积)"""
    x_overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    y_overlap = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    overlap = x_overlap * y_overlap
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    min_area = min(area_a, area_b)
    if min_area <= 0:
        return 0.0
    return overlap / min_area


def _extract_text_in_rect(page: fitz.Page, rect: Tuple[float, float, float, float]) -> str:
    """从 PDF 页面某个矩形区域内提取文本（利用 PyMuPDF 原生文字坐标，无 OCR）。"""
    x0, y0, x1, y1 = rect
    # 扩张边距以容忍坐标误差和截断问题
    margin = 4.0
    clip = fitz.Rect(x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    try:
        text = page.get_text("text", clip=clip)
    except Exception:
        return ""
    if text:
        text = text.strip()
        # 合并多行 → 单行（用于 cell 内展示）
        text = " ".join(text.splitlines())
    return text


# ============== 输出格式化 ==============


def _cells_to_html(table: ExtractedTable) -> str:
    """将提取的表格转为 HTML 字符串，保留 colspan/rowspan。"""
    if not table.rows:
        return "<p><em>(empty table)</em></p>"

    lines = ['<table class="extracted-table border-collapse border border-gray-300 w-full text-sm">']
    if table.caption:
        lines.append(f'<caption class="text-left font-medium text-gray-700 mb-1">{table.caption}</caption>')

    for row_cells in table.rows:
        lines.append("<tr>")
        for cell in row_cells:
            tag = "th" if cell.is_header else "td"
            attrs = []
            if cell.colspan > 1:
                attrs.append(f'colspan="{cell.colspan}"')
            if cell.rowspan > 1:
                attrs.append(f'rowspan="{cell.rowspan}"')
            cls = "border border-gray-400 px-2 py-1"
            if cell.is_header:
                cls += " bg-gray-100 font-semibold text-center"
            attrs.append(f'class="{cls}"')
            lines.append(f"  <{tag} {' '.join(attrs)}>{cell.text or '&nbsp;'}</{tag}>")
        lines.append("</tr>")

    lines.append("</table>")
    return "\n".join(lines)


def _cells_to_markdown(table: ExtractedTable) -> str:
    """转为简单 Markdown（忽略 colspan/rowspan 合并，便于 LLM 处理）。"""
    if not table.rows:
        return ""

    lines = []
    if table.caption:
        lines.append(f"**{table.caption}**\n")

    n_cols = max(len(row) for row in table.rows)
    for ri, row_cells in enumerate(table.rows):
        cells = [c.text for c in row_cells]
        while len(cells) < n_cols:
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")
        if ri == 0 and any(c.is_header for c in row_cells):
            lines.append("|" + " --- |" * n_cols)

    return "\n".join(lines)


# ============== 公开 API ==============


class TableTransformerService:
    """PDF 表格提取主服务"""

    def __init__(self, device: str = "cuda"):
        self.device = device if torch.cuda.is_available() else "cpu"
        logger.info(f"TableTransformerService using device: {self.device}")

    def extract_tables(self, pdf_path: str, confidence: float = 0.7) -> List[ExtractedTable]:
        """从 PDF 中提取所有表格。

        Args:
            pdf_path: PDF 文件路径
            confidence: 检测置信度阈值

        Returns:
            List[ExtractedTable]: 按页排列的表格列表
        """
        doc = fitz.open(pdf_path)
        all_tables: List[ExtractedTable] = []

        for page_idx in range(doc.page_count):
            page = doc[page_idx]
            page_tables = self._extract_tables_from_page(doc, page, page_idx, confidence)
            all_tables.extend(page_tables)

        doc.close()
        return all_tables

    def _extract_tables_from_page(
        self, doc: fitz.Document, page: fitz.Page, page_idx: int, confidence: float
    ) -> List[ExtractedTable]:
        """从单页提取表格。"""
        # 1. 渲染页面图片
        page_image = _render_page_image(doc, page_idx, scale=2.0)

        # 2. 检测表格
        table_boxes = _detect_tables(page_image, confidence_threshold=confidence)
        if not table_boxes:
            return []

        img_w, img_h = page_image.size
        page_w = page.rect.width
        page_h = page.rect.height
        scale_x = page_w / img_w
        scale_y = page_h / img_h

        tables = []
        for ti, tb in enumerate(table_boxes):
            # 图片坐标 → 页面坐标
            tx0 = tb["bbox"][0] * scale_x
            ty0 = tb["bbox"][1] * scale_y
            tx1 = tb["bbox"][2] * scale_x
            ty1 = tb["bbox"][3] * scale_y

            # 裁切表格图片（留 5px 边距）
            margin = 5
            crop_box = (
                max(0, int(tb["bbox"][0]) - margin),
                max(0, int(tb["bbox"][1]) - margin),
                min(img_w, int(tb["bbox"][2]) + margin),
                min(img_h, int(tb["bbox"][3]) + margin),
            )
            table_crop = page_image.crop(crop_box)

            # 校正裁切后的页面坐标偏移
            crop_offset_x = crop_box[0] * scale_x
            crop_offset_y = crop_box[1] * scale_y
            table_bbox_page = (
                max(0, tx0 - margin * scale_x),
                max(0, ty0 - margin * scale_y),
                min(page_w, tx1 + margin * scale_x),
                min(page_h, ty1 + margin * scale_y),
            )

            # 3. 识别表格结构
            structure = _recognize_structure(table_crop)

            if not structure["rows"] or not structure["columns"]:
                continue

            # 4. 组装网格
            grid = _boxes_to_grid(
                structure["rows"],
                structure["columns"],
                structure["headers"],
                table_crop,
                page,
                table_bbox_page,
            )

            if not grid:
                continue

            # 5. 推断 caption（表格上方或下方的 "Table N:" 文本）
            caption = self._find_caption(page, table_bbox_page)

            table = ExtractedTable(
                page=page_idx + 1,
                table_index=ti,
                caption=caption,
                bbox=table_bbox_page,
                rows=grid,
            )

            # 过滤图表/非表格
            if _is_chart_or_figure(table):
                logger.debug(f"P{page_idx+1} T{ti}: filtered as chart/figure "
                            f"({len(table.rows)}r×{max(len(r) for r in table.rows)}c)")
                continue

            table.raw_html = _cells_to_html(table)
            table.raw_markdown = _cells_to_markdown(table)
            tables.append(table)

        # 同页去重：同一 caption 只分配给最近的表格
        tables = _deduplicate_captions(tables)

        return tables

    def _find_caption(self, page: fitz.Page, table_bbox: Tuple[float, float, float, float]) -> str:
        """在表格附近（上方或下方）寻找完整多行 caption。

        PyMuPDF words 中 'Table' 和 '1:' 是两个独立词，需要合并匹配。
        匹配后收集所有同一行的词及后续行，直到遇到空段落或表头行。
        """
        tx0, ty0, tx1, ty1 = table_bbox
        words = _get_page_words(page)

        import re
        table_num_re = re.compile(r'^\d+[.:]$')

        # 找到 "Table" + 紧邻的 "N:"/"N." 词对（同一个 block/line）
        candidates = []
        for i, w in enumerate(words):
            if w["text"].lower() != "table":
                continue
            if i + 1 >= len(words):
                continue
            wnext = words[i + 1]
            if not table_num_re.match(wnext["text"]):
                continue
            # 两个词必须在同一行（Y 坐标接近）
            if abs(w["cy"] - wnext["cy"]) > 6:
                continue
            # 表格编号（去冒号/句号）
            table_n = int(re.sub(r'[.:]', '', wnext["text"]))

            # 计算到表格的距离（优先上方，其次下方）
            cap_y = w["cy"]
            if cap_y < ty0:
                dist_y = ty0 - cap_y  # 上方 → 小值优先
            elif cap_y > ty1:
                dist_y = (cap_y - ty1) + 1000  # 下方 → 加惩罚使其排在后面
            else:
                dist_y = 0
            if dist_y < 1300:
                candidates.append((dist_y, i, table_n, w, wnext))

        if not candidates:
            return ""

        # 取距离最近的
        candidates.sort(key=lambda x: x[0])
        dist_y, start_idx, table_n, cap_start, cap_num = candidates[0]

        # 收集 caption 文本：从 "Table N:" 后的词开始，连续取到第一个明显的 Y 间隙。
        # Y 间隙 > 12pt 代表跳到了下一个段落（表头或正文）
        caption_words = [f"Table {table_n}:"]
        prev_y = cap_start["cy"]

        for j in range(start_idx + 2, len(words)):
            w = words[j]
            # 忽略 table 上方的词
            if w["cy"] < cap_start["cy"] - 3:
                continue
            # 检测 Y 间隙：跳 > 12pt → 新段落，caption 结束
            y_gap = w["cy"] - prev_y
            if y_gap > 15:
                break
            # Caption 可能比表格本体更宽（尤其 Table N: 左对齐），放宽 X 范围
            if w["cx"] < tx0 - 120 or w["cx"] > tx1 + 80:
                if y_gap > 6:
                    break
                continue
            # 遇到下一个 "Table N:" → 停止
            if (w["text"].lower() == "table" and j + 1 < len(words)
                    and table_num_re.match(words[j + 1]["text"])):
                break
            caption_words.append(w["text"])
            prev_y = w["cy"]

        caption = " ".join(caption_words).strip()
        caption = _clean_cell_text(caption) or caption
        caption = re.sub(r'\s{2,}', ' ', caption)
        # 过滤碎片
        if len(caption) < 40:
            return ""
        return caption


# 单例
table_transformer_service = TableTransformerService()
