import subprocess
import os
import tempfile
from pathlib import Path


class MarkerService:
    """Marker PDF 转 Markdown 服务"""

    def __init__(self):
        self.marker_cmd = os.environ.get('MARKER_CMD', 'marker')

    def convert_pdf_to_markdown(self, pdf_path: str) -> str:
        """
        调用 marker 将 PDF 转换为 Markdown
        返回: Markdown 文本内容
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            output_path = output_dir / "output.md"

            cmd = [
                self.marker_cmd,
                pdf_path,
                str(output_dir),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode != 0:
                raise Exception(f"Marker 执行失败: {result.stderr}")

            if not output_path.exists():
                raise Exception(f"Marker 未生成输出文件: {result.stdout}")

            return output_path.read_text(encoding='utf-8')


marker_service = MarkerService()
