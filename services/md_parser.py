"""将 PDF 转换为按"表格"切分的 Markdown 片段。

每个 TableChunk 包含 caption + 完整的 |...|...| 表格块，
直接喂给 LLM 做单表抽取，准确率比"整篇 PDF 文本"高得多。
"""
import re
from dataclasses import dataclass
from typing import List, Optional

import pymupdf4llm


@dataclass
class TableChunk:
    page: int            # 1-indexed page number
    table_n: int         # Table N 里的 N
    caption: str         # "Table N: 完整 caption 文本"
    markdown_text: str   # caption + 紧随其后的 |...|...| 表格段


_TABLE_START = re.compile(r'(?:^|\n)\s*Table\s+(\d+)\s*[:.]', re.MULTILINE | re.IGNORECASE)
# 段落标题候选：Markdown 标题或粗体段标题（**xxx.**），用于 body 截断
_HEADING_LIKE = re.compile(
    r'(?:^|\n)(?:\s*#{1,4}\s+\S|\s*\*\*[A-Z][^*\n]{0,80}\.\*\*)',
    re.MULTILINE,
)
# 截断黑名单：表格 caption 自身就是 "Table N: ...\n" 开头，避免被误判
_TABLE_OR_HEADING = re.compile(
    r'(?:^|\n)(?:\s*Table\s+\d+\s*[:.]|\s*#{1,4}\s+\S|\s*\*\*[A-Z][^*\n]{0,80}\.\*\*)',
    re.MULTILINE,
)


def _find_body_end(text: str, start: int, default_end: int) -> int:
    """从 start 向后找最近的"段落标题"或下一个 Table 标记，取最小的位置作为 body 终点。
    避免 table body 越界吞正文。
    """
    candidates = []
    for m in _TABLE_OR_HEADING.finditer(text, pos=start):
        candidates.append(m.start())
        if len(candidates) >= 10:  # 防御：最多扫 10 个标记
            break
    if not candidates:
        return default_end
    return min(candidates)


def _split_page_into_sections(text: str) -> List[dict]:
    """把一页 MD 文本按 "Table N: ..." 切分。

    返回列表，每个元素：
      {'table_n': int|None, 'caption': str, 'body': str}
    非表段 table_n=None（页面顶部的引言/正文）。
    """
    matches = list(_TABLE_START.finditer(text))
    if not matches:
        return [{'table_n': None, 'caption': '', 'body': text.strip()}]

    sections: List[dict] = []
    if matches[0].start() > 0:
        preamble = text[:matches[0].start()].strip()
        if preamble:
            sections.append({'table_n': None, 'caption': '', 'body': preamble})

    for i, m in enumerate(matches):
        table_n = int(m.group(1))
        line_start = m.start()
        newline_pos = text.find('\n', m.end())
        line_end = newline_pos if newline_pos != -1 else len(text)
        caption_line = text[line_start:line_end].strip()

        body_start = newline_pos + 1 if newline_pos != -1 else m.end()
        # body 终点 = 下一个 Table 标记 OR 段落标题（防止吞正文）
        default_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body_end = _find_body_end(text, body_start, default_end)
        body = text[body_start:body_end].strip()

        sections.append({
            'table_n': table_n,
            'caption': caption_line,
            'body': body,
        })
    return sections


def _table_chunk_to_text(caption: str, body: str) -> str:
    """把 caption + body 拼成喂给 LLM 的 markdown_text。"""
    if body:
        return f"{caption}\n\n{body}"
    return caption


def parse_pdf_to_table_chunks(pdf_path: str) -> List[TableChunk]:
    """PDF → TableChunk 列表。

    每张识别到的表一个 chunk；同一页多张表分别返回。
    """
    page_chunks = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
    out: List[TableChunk] = []

    for pc in page_chunks:
        page_num = pc.get('metadata', {}).get('page_number', 0)  # 1-indexed
        text = pc.get('text', '') or ''
        if not text.strip():
            continue

        for sec in _split_page_into_sections(text):
            if sec['table_n'] is None:
                continue
            out.append(TableChunk(
                page=page_num,
                table_n=sec['table_n'],
                caption=sec['caption'],
                markdown_text=_table_chunk_to_text(sec['caption'], sec['body']),
            ))
    return out


def parse_pdf_to_markdown(pdf_path: str) -> str:
    """PDF → 整篇 Markdown（供存档/兜底用）。"""
    return pymupdf4llm.to_markdown(pdf_path)


md_parser = type('md_parser', (), {})()  # 简易命名空间，与 services/ 其他模块风格一致
md_parser.parse_pdf_to_table_chunks = staticmethod(parse_pdf_to_table_chunks)
md_parser.parse_pdf_to_markdown = staticmethod(parse_pdf_to_markdown)
