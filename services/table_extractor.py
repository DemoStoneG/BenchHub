"""从 PDF 中检测表格并渲染为带 caption 的 PNG 截图。

策略（重点修复截图被碎片化问题）：
1. 用「Table N:」标题位置定位每张表的纵向范围
2. 同列的下一张表标题 = 当前表的下界
3. 用 x 范围最宽文字决定当前表的横向范围
4. 在该范围内调 pdfplumber.extract_tables() 取 cell 数据
5. 只保留含「数据集 + Benchmark 任务 + 数据」的实验结果表
6. 自动检测附录边界并停止抽取
"""
import io
import re
from typing import List, Dict, Optional, Tuple

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image


RESULTS_KEYWORDS = [
    'benchmark', 'comparison', 'result', 'performance', 'evaluation',
    'experiment', 'experimental', 'ablation', 'main table', 'main results',
    'sota', 'state-of-the-art',
    'accuracy', 'acc', 'f1', 'map', 'recall', 'precision', 'auc',
    'top-1', 'top-5', 'top1', 'top5', 'mse', 'rmse', 'mae', 'bleu', 'rouge',
    'miou', 'psnr', 'ssim',
    'dataset', 'test set', 'val set', 'training set',
    'image classification', 'object detection', 'segmentation', 'recognition',
    'action', 'retrieval', 'generation', 'translation', 'captioning',
    'qa', 'vqa', 'reasoning', 'summarization', 'dialogue',
]

# 示例/演示性表格的黑名单词：含这些词的表通常不是结果表
TABLE_EXCLUSION_HINTS = [
    'candidate', 'candidates', 'videoclip', 'video clip', 'select the correct',
    'query example', 'example query', 'illustration', 'illustrative example',
    'options (a)', 'options (b)', '(a) (b) (c)', '(a)(b)(c)',
]


def _is_results_table(table_data, caption: str) -> bool:
    if not table_data or len(table_data) < 2:
        return False
    header = table_data[0] if table_data else []
    if not header or len(header) < 2:
        return False
    has_number = False
    for row in table_data:
        for cell in row:
            if cell and re.search(r'\d+\.?\d*', str(cell)):
                has_number = True
                break
        if has_number:
            break
    if not has_number:
        return False
    caption_lc = (caption or '').lower()
    header_lc = ' '.join(str(c) for c in header if c).lower()
    first_col_lc = ' '.join(
        str(row[0]) for row in table_data[1:] if row and row[0]
    ).lower() if all(len(r) > 0 for r in table_data[1:] if r) else ''
    text_lc = caption_lc + ' ' + header_lc + ' ' + first_col_lc
    has_percent = bool(re.search(r'\d+\.?\d*\s*%', text_lc))
    has_decimal = bool(re.search(r'\d+\.\d+', text_lc))
    if has_percent or has_decimal:
        return True
    for kw in RESULTS_KEYWORDS:
        if kw.lower() in text_lc:
            return True
    return False


def _find_table_caption_words(page) -> List[Tuple[float, float, str]]:
    """找出页面上所有 'Table N: ...' 标题词的 (top, x0, text) 列表。"""
    words = page.extract_words() or []
    captions = []
    for w in words:
        if re.match(r'^\s*Table\s*\d+', w['text'], re.IGNORECASE):
            # 跳过 TOC 形式的行（行末跟点+页码）
            if re.search(r'\.{2,}\s*\d+\s*$', w['text']):
                continue
            captions.append((w['top'], w['x0'], w['text']))
    return captions


def _group_caption_lines(captions: List[Tuple[float, float, str]], y_tol: float = 4.0):
    """把相邻行的 caption 词合并成一条 caption（caption 可能跨多行）。"""
    if not captions:
        return []
    captions = sorted(captions, key=lambda c: (c[0], c[1]))
    groups = [[captions[0]]]
    for c in captions[1:]:
        if c[0] - groups[-1][-1][0] <= y_tol:
            groups[-1].append(c)
        else:
            groups.append([c])
    return [
        (
            min(w[0] for w in g),  # top
            min(w[1] for w in g),  # x0
            ' '.join(w[2] for w in g),  # text
        )
        for g in groups
    ]


def _column_of(x: float, page_width: float) -> str:
    return 'left' if x < page_width / 2 else 'right'


def _cluster_h_lines(h_lines: List[Dict], initial_gap: float = 30.0, merge_gap: float = 150.0, x_tol: float = 10.0) -> List[List[Dict]]:
    """按 top 距离聚类水平线，再合并 x 范围接近、y 距离 < merge_gap 的相邻组。

    返回 List[List[Line]]，每个内部 list 是一组（理论上属于同一张表）。
    """
    if not h_lines:
        return []
    sorted_lines = sorted(h_lines, key=lambda l: l['top'])
    groups = [[sorted_lines[0]]]
    for l in sorted_lines[1:]:
        if l['top'] - groups[-1][-1]['top'] < initial_gap:
            groups[-1].append(l)
        else:
            groups.append([l])

    # 同栏/同宽合并
    merged = True
    while merged:
        merged = False
        new_groups = [groups[0]]
        for g in groups[1:]:
            prev = new_groups[-1]
            px0, px1 = min(l['x0'] for l in prev), max(l['x1'] for l in prev)
            cx0, cx1 = min(l['x0'] for l in g), max(l['x1'] for l in g)
            same_col = abs(px0 - cx0) < x_tol and abs(px1 - cx1) < x_tol
            cur_top = min(l['top'] for l in g)
            gap = cur_top - max(l['bottom'] for l in prev)
            if same_col and gap < merge_gap:
                new_groups[-1].extend(g)
                merged = True
            else:
                new_groups.append(g)
        groups = new_groups
    return groups


def _bbox_of_group(group: List[Dict]) -> Dict:
    return {
        'x0': min(l['x0'] for l in group),
        'top': min(l['top'] for l in group),
        'x1': max(l['x1'] for l in group),
        'bottom': max(l['bottom'] for l in group),
    }


def _find_table_regions(page) -> List[Dict]:
    """通过水平横线聚类定位每张表的 (x0, top, x1, bottom)。

    关键设计：
    1. 用横线聚类，**不依赖 caption 文字位置**（很多表的 caption 在下方）
    2. 横线的 x0/x1 就是表格的**真实左右边界**（无两侧空白）
    3. 之后再**双向找 caption**（group 上方 50pt 内 或 下方 80pt 内），
       并把 caption 文字区域也并入 bbox，确保截图含 caption
    """
    # 收集所有水平线（短于 2pt 高的细线，且 x 范围有一定宽度）
    h_lines = [
        l for l in (page.lines or [])
        if l.get('height', 99) < 2 and (l['x1'] - l['x0']) > 30
    ]
    if not h_lines:
        return []

    # 聚类得到每组（理论上一张表）
    groups = _cluster_h_lines(h_lines, initial_gap=30, merge_gap=150, x_tol=10)
    if not groups:
        return []

    page_width = page.width
    page_height = page.height
    footer_margin = 50
    line_padding_top = 2     # 表顶线往上 2pt
    line_padding_bottom = 2  # 表底线往下 2pt
    caption_above_gap = 50   # caption 在表上方最多 50pt
    caption_below_gap = 120  # caption 在表下方最多 120pt（caption 可能跨多行 + 行距大）

    # 收集 caption 词（用于双向查找）
    raw_caps = _find_table_caption_words(page)
    captions = _group_caption_lines(raw_caps)

    regions = []
    for gi, group in enumerate(groups):
        bb = _bbox_of_group(group)
        # 表 bbox = 横向线真实范围 + 一点 padding
        table_x0 = max(0, bb['x0'] - 1)
        table_x1 = min(page_width, bb['x1'] + 1)
        table_top = max(0, bb['top'] - line_padding_top)
        table_bottom = min(page_height, bb['bottom'] + line_padding_bottom)

        # 限制在页边距内
        table_x0 = max(0, table_x0)
        table_x1 = min(page_width, table_x1)

        # 双向找 caption：上方 (caption.bottom in [table_top - caption_above_gap, table_top])
        #                 或 下方 (caption.top in [table_bottom, table_bottom + caption_below_gap])
        # caption 必须 x 范围与表有重叠（同栏或全宽）
        matched_caption = None
        caption_extend_top = table_top
        caption_extend_bottom = table_bottom
        for cap_top, cap_x0, cap_text in captions:
            cap_x1 = cap_x0 + 200  # 粗略估算 caption 文本宽度
            x_overlap = cap_x0 < table_x1 and cap_x1 > table_x0
            if not x_overlap:
                continue
            if table_top - caption_above_gap <= cap_top <= table_top:
                # caption 在表上方
                if matched_caption is None or cap_top < matched_caption[0]:
                    matched_caption = (cap_top, cap_x0, cap_text)
            elif table_bottom <= cap_top <= table_bottom + caption_below_gap:
                # caption 在表下方
                if matched_caption is None or cap_top > matched_caption[0]:
                    matched_caption = (cap_top, cap_x0, cap_text)

        if matched_caption:
            cap_top_y, _, cap_text_str = matched_caption
            if cap_top_y < table_top:
                # caption 在上方
                caption_extend_top = max(0, cap_top_y - 2)
            else:
                # caption 在下方：扩展到 caption 段真实底部
                cap_words = page.extract_words() or []
                cap_bottoms = [
                    w['bottom'] for w in cap_words
                    if w['top'] >= cap_top_y - 1 and w['top'] <= cap_top_y + 60
                    and w['x0'] >= table_x0 - 5
                ]
                if cap_bottoms:
                    caption_extend_bottom = min(page_height, max(cap_bottoms) + 2)
                else:
                    # 找 caption 下方最近的同栏横线
                    next_line = None
                    for l in h_lines:
                        if l['top'] > cap_top_y + 5 and \
                           abs(l['x0'] - table_x0) < 50:
                            if next_line is None or l['top'] < next_line['top']:
                                next_line = l
                    if next_line:
                        caption_extend_bottom = min(page_height, next_line['top'] - 2)
                    else:
                        caption_extend_bottom = min(page_height, cap_top_y + 60)

        # 关键：扩展后的 bbox 不能侵入下一张表的本体
        # 找下一组 group 的 top（如果 x 范围有重叠）
        next_group_top = page_height
        for gj in range(gi + 1, len(groups)):
            other = _bbox_of_group(groups[gj])
            other_x0, other_x1 = other['x0'], other['x1']
            if other_x0 < table_x1 and other_x1 > table_x0:  # x 范围重叠
                if other['top'] < next_group_top:
                    next_group_top = other['top']
        caption_extend_bottom = min(caption_extend_bottom, next_group_top - 2)
        caption_extend_top = max(caption_extend_top, 0)

        regions.append({
            'x0': table_x0,
            'top': caption_extend_top,
            'x1': table_x1,
            'bottom': caption_extend_bottom,
            'caption_hint': matched_caption[2] if matched_caption else '',
        })
    return regions


def _extract_text_in_bbox(page, bbox) -> str:
    """在指定 bbox 内取全部文本（扁平化小写），用于 record 匹配。

    pdfplumber 的按行/按格抽取对无明显横线的学术表会切碎，所以直接用整段文本
    做字符串包含检查，更鲁棒。
    """
    try:
        x0, top, x1, bottom = bbox
        region = page.crop((x0, top, x1, bottom))
        return (region.extract_text() or '').lower()
    except Exception:
        return ''


def _first_row_in_bbox(page, bbox) -> str:
    """取 bbox 内第一行文字（用于粗略判断是否是表头/表的第一行内容）。"""
    text = _extract_text_in_bbox(page, bbox)
    if not text:
        return ''
    return text.split('\n')[0].strip()


def _is_results_table_text(text: str, caption: str) -> bool:
    """用扁平文本 + caption 判定是否含实验结果。

    pdfplumber 提取出的文本会丢掉空格（"top-1andtop-5"），用普通子串包含
    比词边界更鲁棒。
    """
    if not text or len(text) < 20:
        return False
    text_lc = (caption or '').lower() + ' ' + text

    # 黑名单：示例/演示性表格，含这些词就排除
    for hint in TABLE_EXCLUSION_HINTS:
        if hint in text_lc:
            return False

    # 必须有数字
    if not re.search(r'\d+\.?\d*', text):
        return False

    # 强信号：百分号 / 小数（结果表里几乎必出现）
    has_percent = bool(re.search(r'\d+\.?\d*\s*%', text_lc))
    has_decimal = bool(re.search(r'\d+\.\d+', text_lc))
    if has_percent or has_decimal:
        return True

    # 关键词命中：扁平文本里直接子串包含即可
    for kw in RESULTS_KEYWORDS:
        if kw.lower() in text_lc:
            return True
    return False


def _caption_in_bbox(page, bbox, max_chars: int = 300) -> str:
    """取 bbox 内的 caption 文本（caption 在表上方或下方，bbox 都会包住 caption）。

    启发式：在 bbox 内找 "Table N" 引导的文本段，作为 caption 提取出来。
    """
    try:
        x0, top, x1, bottom = bbox
        # 先取整段文本（扁平化），从中找 "Table N" 引导的段
        region = page.crop((x0, top, x1, bottom))
        text = (region.extract_text() or '').strip()
        if not text:
            return ''

        # 找 "Table N" 的位置，取该位置开始的整段
        m = re.search(r'\bTable\s*\d+', text)
        if m:
            caption_part = text[m.start():]
            # 截到合理长度
            if len(caption_part) > max_chars:
                caption_part = caption_part[:max_chars] + '...'
            return caption_part

        # fallback: 用整段文本
        if len(text) > max_chars:
            text = text[:max_chars] + '...'
        return text
    except Exception:
        return ''


class TableExtractor:
    RENDER_SCALE = 2.0
    PADDING = 4
    APPENDIX_HEAD_LOOKAHEAD_LINES = 5

    @staticmethod
    def _is_appendix_page(page) -> bool:
        try:
            text = page.extract_text() or ''
        except Exception:
            return False
        if not text:
            return False
        lines = [ln.strip() for ln in text.split('\n')[:TableExtractor.APPENDIX_HEAD_LOOKAHEAD_LINES]]
        for line in lines:
            if not line:
                continue
            if re.search(r'\.{2,}\s*\d+\s*$', line):
                continue
            if line.lower() == 'appendix':
                return True
            if re.match(r'^appendix\b[\s\.:]', line, re.IGNORECASE):
                return True
        return False

    def extract_tables(self, pdf_path: str, paper_id: int) -> List[Dict]:
        out: List[Dict] = []
        order = 0

        with pdfplumber.open(pdf_path) as pdf:
            pdfium_doc = pdfium.PdfDocument(pdf_path)
            try:
                for page_idx, page in enumerate(pdf.pages):
                    if self._is_appendix_page(page):
                        break

                    regions = _find_table_regions(page)
                    if not regions:
                        continue

                    pil_page = pdfium_doc[page_idx].render(
                        scale=self.RENDER_SCALE
                    ).to_pil()

                    for region in regions:
                        bbox = (region['x0'], region['top'], region['x1'], region['bottom'])
                        # 横线聚类得到的 group 高度太小(<25pt)的不可能是表
                        if bbox[3] - bbox[1] < 25:
                            continue

                        caption = _caption_in_bbox(page, bbox)
                        flat_text = _extract_text_in_bbox(page, bbox)

                        if not _is_results_table_text(flat_text, caption):
                            continue

                        scale = self.RENDER_SCALE
                        pad = self.PADDING
                        crop_box = (
                            max(0, int(bbox[0] * scale) - pad),
                            max(0, int(bbox[1] * scale) - pad),
                            min(pil_page.width, int(bbox[2] * scale) + pad),
                            min(pil_page.height, int(bbox[3] * scale) + pad),
                        )
                        cropped = pil_page.crop(crop_box)

                        buf = io.BytesIO()
                        cropped.save(buf, format='PNG', optimize=True)
                        out.append({
                            'page_number': page_idx + 1,
                            'image_bytes': buf.getvalue(),
                            'caption': caption,
                            'order': order,
                            'bbox': bbox,
                            'flat_text': flat_text,
                        })
                        order += 1
            finally:
                pdfium_doc.close()

        return out


table_extractor = TableExtractor()
