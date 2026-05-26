import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'benchhub.settings')

import django
django.setup()

from papers.models import Paper, ExperimentRecord
from services.marker_service import marker_service
from services.parser_service import parser_service
from services.llm_service import llm_service


def parse_paper_task(paper_id: int):
    """
    异步解析论文任务
    1. PDF -> Markdown (Marker)
    2. Markdown -> JSON (LLM)
    3. 写入 ExperimentRecord
    """
    try:
        paper = Paper.objects.get(id=paper_id)
        paper.status = Paper.Status.PROCESSING
        paper.save()

        pdf_path = paper.local_pdf.path

        md_content = marker_service.convert_pdf_to_markdown(pdf_path)
        paper.raw_markdown = md_content

        table_text = parser_service.extract_tables_for_llm(md_content)
        if not table_text:
            paper.status = Paper.Status.FAILED
            paper.error_message = "未找到任何表格"
            paper.save()
            return

        extracted_data = llm_service.extract_table_data(table_text)
        if not extracted_data:
            paper.status = Paper.Status.FAILED
            paper.error_message = "LLM 未能提取到有效数据"
            paper.save()
            return

        for item in extracted_data:
            ExperimentRecord.objects.create(
                paper=paper,
                dataset=item.get('dataset', ''),
                model_name=item.get('model', ''),
                metric=item.get('metric', ''),
                value=item.get('value', 0.0),
                is_verified=False
            )

        paper.status = Paper.Status.COMPLETED
        paper.save()

    except Exception as e:
        if 'paper' in locals():
            paper.status = Paper.Status.FAILED
            paper.error_message = str(e)
            paper.save()
        raise


if __name__ == '__main__':
    import django
    django.setup()
    paper_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    parse_paper_task(paper_id)
