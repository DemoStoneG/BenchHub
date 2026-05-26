import re
from typing import List, Dict


class ParserService:
    """Markdown 表格解析服务 - 规则解析"""

    def parse_markdown_tables(self, markdown_content: str) -> List[Dict]:
        """
        解析 Markdown 中的所有表格，返回结构化数据
        """
        tables = []
        lines = markdown_content.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if self._is_table_header(line):
                table_lines = [line]
                i += 1

                if i < len(lines) and self._is_table_delimiter(lines[i]):
                    i += 1
                    while i < len(lines) and lines[i].strip():
                        table_lines.append(lines[i].strip())
                        i += 1

                table = self._parse_table_lines(table_lines)
                if table:
                    tables.append(table)
            else:
                i += 1

        return tables

    def _is_table_header(self, line: str) -> bool:
        return line.startswith('|') and line.endswith('|')

    def _is_table_delimiter(self, line: str) -> bool:
        return re.match(r'^\|[\s\-:|]+\|$', line) is not None

    def _parse_table_lines(self, lines: List[str]) -> Dict:
        if len(lines) < 2:
            return None

        headers = self._parse_row(lines[0])
        if not headers:
            return None

        rows = []
        for line in lines[2:]:
            cells = self._parse_row(line)
            if cells and len(cells) == len(headers):
                rows.append(cells)

        return {
            'headers': headers,
            'rows': rows
        }

    def _parse_row(self, line: str) -> List[str]:
        cells = line.strip('|').split('|')
        return [cell.strip() for cell in cells]

    def extract_tables_for_llm(self, markdown_content: str) -> str:
        """
        提取表格部分用于 LLM 提取，拼接成文本
        """
        tables = self.parse_markdown_tables(markdown_content)
        if not tables:
            return ""

        result = []
        for i, table in enumerate(tables):
            result.append(f"\n--- 表格 {i+1} ---\n")
            result.append("| " + " | ".join(table['headers']) + " |")
            result.append("| " + " | ".join(['---'] * len(table['headers'])) + " |")
            for row in table['rows']:
                result.append("| " + " | ".join(row) + " |")

        return "\n".join(result)


parser_service = ParserService()
