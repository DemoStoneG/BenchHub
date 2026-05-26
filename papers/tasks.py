import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'benchhub.settings')

import django
django.setup()

from papers.models import Paper, ExperimentRecord
from services.pdf_service import pdf_service
from services.llm_service import llm_service


def parse_paper_task(paper_id: int):
    """
    异步解析论文任务
    1. PDF -> 文本 (pypdf)
    2. 文本 -> JSON (LLM)
    3. 写入 ExperimentRecord
    """
    try:
        paper = Paper.objects.get(id=paper_id)
        paper.status = Paper.Status.PROCESSING
        paper.save()

        pdf_path = paper.local_pdf.path

        # 提取文本
        text_content = pdf_service.extract_text_from_pdf(pdf_path)
        paper.raw_markdown = text_content

        if not text_content or len(text_content.strip()) < 100:
            paper.status = Paper.Status.FAILED
            paper.error_message = "PDF 文本提取失败或内容过少"
            paper.save()
            return

        # 直接传原始文本给 LLM，让它自己识别表格
        extracted_data = llm_service.extract_table_data(text_content)

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
