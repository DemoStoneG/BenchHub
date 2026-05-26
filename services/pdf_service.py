import io
import re
from pypdf import PdfReader


class PDFService:
    """PDF 文本提取服务 (使用 pypdf)"""

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        从 PDF 提取文本内容
        返回: 纯文本内容
        """
        reader = PdfReader(pdf_path)

        text_parts = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                text_parts.append(f"\n--- Page {i+1} ---\n{text}")

        return "\n".join(text_parts)

    def extract_tables_from_pdf(self, pdf_path: str) -> list:
        """
        尝试从 PDF 提取表格数据
        返回: 格式化后的表格文本列表
        """
        reader = PdfReader(pdf_path)
        tables = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text:
                continue

            lines = text.split('\n')

            for j, line in enumerate(lines):
                # 检测是否为表格数据行（包含多个数字的列）
                # 表格行特征：包含方法名 + 多个数字（通常是性能指标）
                if self._looks_like_table_row(line):
                    # 尝试提取连续表格行形成表格
                    table_lines = [line]
                    k = j + 1
                    while k < len(lines) and self._looks_like_table_row(lines[k]):
                        table_lines.append(lines[k])
                        k += 1

                    if len(table_lines) >= 2:
                        formatted = self._format_as_table(table_lines)
                        if formatted:
                            tables.append(f"\n--- Page {i+1} Table ---\n{formatted}")

        return tables

    def _looks_like_table_row(self, line: str) -> bool:
        """检测行是否像表格数据行"""
        # 移除空白
        line = line.strip()
        if not line or len(line) < 10:
            return False

        # 表格行通常包含数字和可能的模型名
        # 检查是否包含多个数字（至少3个）
        numbers = re.findall(r'\d+\.?\d*', line)
        if len(numbers) < 2:
            return False

        # 检查是否有字母数字混合（模型名特征）
        has_model_name = bool(re.search(r'[A-Za-z]{3,}.*\d', line))

        return has_model_name

    def _format_as_table(self, lines: list) -> str:
        """将表格行格式化为 Markdown 表格"""
        if not lines:
            return ""

        # 尝试解析列
        formatted_lines = []

        for line in lines:
            # 清理行
            line = line.strip()
            # 标准化空白
            parts = re.split(r'\s{2,}', line)
            if len(parts) < 3:
                # 尝试用多个空格分割
                parts = re.split(r'\s+', line)

            # 格式化为 pipe 表格
            formatted_lines.append("| " + " | ".join(parts) + " |")

        if len(formatted_lines) >= 2:
            return "\n".join(formatted_lines)

        return ""


pdf_service = PDFService()
