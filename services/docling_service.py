"""Docling 表格提取服务。

Docling 负责 PDF 解析、caption 提取、附录过滤。
表格 HTML 由 Docling/TableFormer 结构化数据 (table.data.table_cells) 直接生成，
利用 column_header / row_section / col_span / row_span 等模型推理结果。
"""

import re
import logging
from pathlib import Path
from typing import List, Dict

import fitz
from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)
_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        logger.info("Initializing Docling DocumentConverter...")
        _converter = DocumentConverter()
        logger.info("Docling converter ready.")
    return _converter


def _search_caption_bidirectional(pdf_path: str, page_num: int, table, doc) -> str:
    """Docling 未找到 caption 时，用 PyMuPDF 在表格上方搜索最近的 'Table N:'。

    同一页多表时，只取表格上方最近的那条 caption，避免误匹配前一张表的标题。
    """
    try:
        import re as _re
        pdf_doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > pdf_doc.page_count:
            pdf_doc.close(); return ""
        page = pdf_doc[page_num - 1]
        ph = page.rect.height

        prov = table.prov[0]
        bbox = getattr(prov, 'bbox', None)
        if not bbox: pdf_doc.close(); return ""

        tx0 = bbox.l; ty0 = ph - bbox.t; ty1 = ph - bbox.b

        # 搜索区域：表格上方 120pt，左右各 40pt
        search_top = max(0, ty0 - 120)
        search_bot = min(ph - 1, ty0)  # 只搜表格上方，不含表格本身及下方
        clip = fitz.Rect(max(0, tx0 - 40), search_top, min(page.rect.width, bbox.r + 40), search_bot)
        text = page.get_text("text", clip=clip)
        pdf_doc.close()

        if not text: return ""

        # 找出所有 "Table N:" 候选，取 Y 坐标最靠近表格顶部（即最后一个）的那条
        candidates = list(_re.finditer(
            r'(?:^|\n)\s*(Table\s+\d+[.:][^\n]*)', text, _re.IGNORECASE
        ))
        if candidates:
            return candidates[-1].group(1).strip()

        # 兜底：按行搜索
        lines = text.strip().split('\n')
        for line in reversed(lines):
            if _re.search(r'\bTable\s+\d+\b', line, _re.IGNORECASE):
                return line.strip()[:200]
    except Exception:
        pass
    return ""


def _find_appendix_start(pdf_path: str) -> int | None:
    """扫描 PDF，找到第一个 Appendix 起始页（1-indexed），无则返回 None。"""
    try:
        pdf_doc = fitz.open(pdf_path)
        for i in range(pdf_doc.page_count):
            text = pdf_doc[i].get_text()
            for line in text.strip().split('\n')[:5]:
                stripped = line.strip()
                if re.match(r'^(?:Appendix\b|[A-F]\.\s+\w+|Supplementary\s+Material)',
                            stripped, re.IGNORECASE) and len(stripped) < 100:
                    pdf_doc.close(); return i + 1
        pdf_doc.close()
    except Exception:
        pass
    return None


def extract_tables(pdf_path: str) -> List[Dict]:
    """提取 PDF 中正文部分的表格，跳过 Appendix。每张表返回 {caption, html, page}。"""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    appendix_start = _find_appendix_start(str(path))
    converter = _get_converter()
    result = converter.convert(str(path))
    doc = result.document

    tables = []
    for table in doc.tables:
        # 取页码，过滤 Appendix
        page_num = 1
        try:
            if table.prov and len(table.prov) > 0:
                pn = getattr(table.prov[0], 'page_no', None)
                if pn: page_num = pn
        except Exception: pass
        if appendix_start and page_num >= appendix_start: continue

        # 取 caption
        caption = ""
        try:
            cap = table.caption_text(doc)
            if cap: caption = str(cap).strip()
        except Exception: pass
        if not caption:
            caption = _search_caption_bidirectional(str(path), page_num, table, doc)
        if caption:
            caption = re.sub(r'\[[\d,\-\s]+\]', '', caption)
            caption = re.sub(r'\s{2,}', ' ', caption).strip()

        # 从 TableFormer 结构化数据生成 HTML（含子行拆分）
        html = _table_cells_to_html(table, str(path), page_num)
        if not html: continue

        tables.append({
            "caption": caption, "html": html, "page": page_num,
            "rows": len(re.findall(r'<tr[^>]*>', html)),
            "cols": len(re.findall(r'<(t[dh])[^>]*>', re.search(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL).group(1) if re.search(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL) else '')),
        })
    return tables


# ==================== 表格 HTML 生成（基于 TableFormer 结构化数据） ====================

def _table_cells_to_html(table, pdf_path: str = None, page_num: int = None) -> str:
    """从 Docling TableFormer 结构化数据直接生成 HTML 表格（含 Tailwind 样式）。

    利用 TableFormer 已识别的语义标记：
    - column_header → <th>（蓝底表头）
    - row_section → 全宽段标题行（紫底，如 "UDA" / "DG"）
    - col_span / row_span → colspan / rowspan

    若提供 pdf_path + page_num，自动检测数据 cell 内子行并按 Y 坐标拆分，
    解决 TableFormer 将多个物理子行合并为一个逻辑行的问题。
    """
    data = table.data
    cells = data.table_cells or []
    if not cells:
        return None

    # 从 cells 推断表格维度（TableItem 无 num_rows/num_cols 属性）
    n_rows = max(tc.end_row_offset_idx for tc in cells) + 1
    n_cols = max(tc.end_col_offset_idx for tc in cells) + 1

    # 子行拆分（有 PDF 路径时自动检测）
    sub_rows = _detect_sub_rows(cells, pdf_path, page_num) if (pdf_path and page_num) else {}

    # 按 origin 位置排序
    sorted_cells = sorted(cells,
                          key=lambda tc: (tc.start_row_offset_idx, tc.start_col_offset_idx))

    rows_html = []      # 所有 <tr>...</tr>
    visible_row = 0     # 斑马纹计数器

    for row_idx in range(n_rows):
        # 本行 origin cells
        row_cells = [tc for tc in sorted_cells
                     if tc.start_row_offset_idx == row_idx]
        if not row_cells:
            continue

        # 段标题行
        if all(tc.row_section for tc in row_cells):
            text = _clean_cell_text(row_cells[0].text)
            if text:
                rows_html.append(
                    f'<tr class="bg-purple-50">'
                    f'<th colspan="{n_cols}" class="border border-purple-200 px-3 py-1.5 '
                    f'bg-purple-100 font-bold text-center text-xs text-purple-800">'
                    f'{text}</th></tr>'
                )
            continue

        # 子行数：1（正常行）或 N（需拆分）
        n_sub = sub_rows.get(row_idx, 1)

        for sub_idx in range(n_sub):
            zebra = 'bg-gray-50' if visible_row % 2 == 1 else 'bg-white'
            visible_row += 1

            # 子行分隔线：第一个子行不加，后续子行加虚线顶边
            sep_class = ' border-t border-dashed border-gray-300' if sub_idx > 0 else ''

            tr_parts = []
            for tc in row_cells:
                # 如果这个 cell 在上一子行已经用 rowspan 覆盖了，跳过
                spanned = False
                if sub_idx > 0 and n_sub > 1:
                    # 检查是否有 (row, col, 0) 但没有 (row, col, sub_idx)
                    if (row_idx, tc.start_col_offset_idx, 0) in sub_rows and \
                       (row_idx, tc.start_col_offset_idx, sub_idx) not in sub_rows:
                        spanned = True
                if spanned:
                    continue

                # 取子行文本
                sub_key = (row_idx, tc.start_col_offset_idx, sub_idx)
                if sub_key in sub_rows:
                    text = sub_rows[sub_key]
                else:
                    text = _clean_cell_text(tc.text)
                if not text:
                    text = '&nbsp;'

                # 若本 cell 内容在所有子行中相同 → rowspan=n_sub
                extra_attrs = _span_attrs(tc)
                if n_sub > 1 and sub_idx == 0:
                    varies = any(
                        (row_idx, tc.start_col_offset_idx, si) in sub_rows
                        for si in range(1, n_sub)
                    )
                    if not varies:
                        extra_attrs += f' rowspan="{n_sub}"'

                if tc.column_header:
                    tr_parts.append(
                        f'<th class="{sep_class} border border-gray-400 px-2 py-1.5 '
                        f'bg-blue-50 text-center font-semibold text-gray-700"'
                        f'{extra_attrs}>{text}</th>'
                    )
                elif tc.row_header:
                    tr_parts.append(
                        f'<td class="{sep_class} border border-gray-300 px-2 py-1 '
                        f'text-left font-medium text-gray-900"'
                        f'{extra_attrs}>{text}</td>'
                    )
                else:
                    tr_parts.append(
                        f'<td class="{sep_class} border border-gray-300 px-2 py-1 '
                        f'text-center text-gray-700"'
                        f'{extra_attrs}>{text}</td>'
                    )

            rows_html.append(f'<tr class="{zebra}">{"".join(tr_parts)}</tr>')

    return (
        '<table class="w-full border-collapse border border-gray-300 text-sm">\n'
        + '\n'.join(rows_html)
        + '\n</table>'
    )


def _clean_cell_text(text: str) -> str:
    """清洗 cell 文本：去引用编号、合并空白。"""
    if not text:
        return ''
    text = re.sub(r'\[[\d,\-\s]+\]', '', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _span_attrs(tc) -> str:
    """colspan / rowspan HTML 属性。"""
    attrs = []
    if tc.col_span > 1:
        attrs.append(f'colspan="{tc.col_span}"')
    if tc.row_span > 1:
        attrs.append(f'rowspan="{tc.row_span}"')
    return (' ' + ' '.join(attrs)) if attrs else ''


# ==================== 子行拆分（PyMuPDF 词坐标 Y 聚类） ====================

def _detect_sub_rows(cells, pdf_path: str, page_num: int) -> dict:
    """检测并拆分被 TableFormer 合并的子行。

    返回 dict，混合键类型：
      row_idx → n_sub_rows           (例: 3 → 2 表示逻辑行 3 有 2 个物理子行)
      (row_idx, col, sub_idx) → text (例: (3, 6, 1) → "48.5" 子行 1 列 6 的文本)

    调用方据此为每个子行渲染独立 <tr>：不同内容的 cell 各自渲染，
    相同内容的 cell 在子行 0 用 rowspan=n 跨行。
    """
    try:
        pdf_doc = fitz.open(pdf_path)
        if page_num < 1 or page_num > pdf_doc.page_count:
            pdf_doc.close()
            return {}
        page = pdf_doc[page_num - 1]
    except Exception:
        return {}

    # Step 1: 为每个含多数值的数据 cell 做 Y 聚类
    cell_clusters = {}  # (row, col) -> list[list[words]]
    for tc in cells:
        if tc.column_header or tc.row_section:
            continue
        if not tc.bbox:
            continue

        raw_text = tc.text or ''
        values = [m.group(1) for m in re.finditer(r'(\d+\.?\d*)', raw_text)
                  if not re.search(r'▲\s*[+\-]',
                                   raw_text[max(0, m.start() - 8):m.start()])]
        if len(values) < 2:
            continue

        b = tc.bbox
        rect = fitz.Rect(b.l - 2, b.t - 2, b.r + 2, b.b + 2)
        words = page.get_text("words", clip=rect)
        if len(words) <= 1:
            continue

        words.sort(key=lambda w: w[1])
        clusters = [[words[0]]]
        for w in words[1:]:
            if w[1] - clusters[-1][-1][1] > 4:
                clusters.append([w])
            else:
                clusters[-1].append(w)

        if len(clusters) >= 2:
            cell_clusters[(tc.start_row_offset_idx, tc.start_col_offset_idx)] = clusters

    # Step 2: 逐行一致性检查
    row_cells = {}
    for (r, c) in cell_clusters:
        row_cells.setdefault(r, []).append(c)

    result = {}

    for r, cols in row_cells.items():
        multi_num_cols = [col for col in cols if (r, col) in cell_clusters]
        if len(multi_num_cols) < 2:
            continue

        n_clusters_per_cell = [len(cell_clusters[(r, col)]) for col in multi_num_cols]
        most_common_n = max(set(n_clusters_per_cell), key=n_clusters_per_cell.count)

        consistent = sum(1 for n in n_clusters_per_cell if n == most_common_n)
        if consistent < len(multi_num_cols) * 0.7:
            continue

        # 记录该行子行数
        result[r] = most_common_n

        # Step 3: 为该行所有数据 cell 生成子行文本
        row_data_cells = [tc for tc in cells
                          if tc.start_row_offset_idx == r
                          and not tc.column_header
                          and not tc.row_section
                          and tc.bbox]

        for tc in row_data_cells:
            col = tc.start_col_offset_idx
            clusters = cell_clusters.get((r, col))

            if clusters is None:
                # 无自然多簇 → 在子行 0 存储文本，由 rowspan 覆盖其余子行
                text = _clean_cell_text(tc.text) or '&nbsp;'
                result[(r, col, 0)] = text
            else:
                # 有自然多簇 → 生成各子行文本
                parts = []
                for cluster in clusters:
                    part = ' '.join(w[4] for w in cluster)
                    part = _clean_cell_text(part)
                    parts.append(part or '&nbsp;')

                if len(set(parts)) == 1:
                    # 所有子行内容相同 → 只在子行 0 存一份（rowspan）
                    result[(r, col, 0)] = parts[0]
                else:
                    # 子行内容不同 → 每个子行各存一份
                    for si, part in enumerate(parts):
                        result[(r, col, si)] = part

    pdf_doc.close()
    return result
