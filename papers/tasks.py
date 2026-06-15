import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'benchhub.settings')

import django
django.setup()

from papers.models import Paper, ExperimentRecord, TableChunk
from services.docling_service import extract_tables as docling_extract_tables


def parse_paper_task(paper_id: int, skip_llm: bool = False):
    """异步解析论文任务（Docling 表格提取）。

    1. Docling 识别 PDF 中所有表格（正文部分，跳过 Appendix）
    2. 每张表写入 TableChunk（HTML 快照 + caption + page）
    3. 暂不调用 LLM（LLM 抽取为独立步骤）
    """
    paper = None
    try:
        paper = Paper.objects.get(id=paper_id)

        # 清空旧数据
        paper.results.all().delete()
        paper.table_chunks.all().delete()
        for ti in paper.table_images.all():
            try:
                if ti.image:
                    ti.image.delete(save=False)
            except Exception:
                pass
        paper.table_images.all().delete()

        paper.status = Paper.Status.EXTRACTING
        paper.progress_message = '正在 Docling 提取表格...'
        paper.error_message = ''
        paper.save()

        pdf_path = paper.local_pdf.path

        # Docling 表格提取
        tables = docling_extract_tables(pdf_path)
        if not tables:
            paper.status = Paper.Status.FAILED
            paper.error_message = "Docling 未识别到任何表格"
            paper.save()
            return

        # 写入 TableChunk
        for ti, t in enumerate(tables, start=1):
            html = t['html']
            TableChunk.objects.create(
                paper=paper,
                table_n=ti,
                sub_table_index=0,
                page=t['page'],
                caption=(t.get('caption') or '')[:500],
                markdown_text=html,
                extraction_method='docling',
                cells_json=[],
                header_json=[],
                bbox_json={
                    'html': html,
                    'caption': t.get('caption', ''),
                    'page': t['page'],
                    'rows': t.get('rows', 0),
                    'cols': t.get('cols', 0),
                },
            )

        paper.status = Paper.Status.COMPLETED
        paper.progress_message = f'完成，{len(tables)} 张表格'
        paper.save()

    except Exception as e:
        if paper is not None:
            paper.status = Paper.Status.FAILED
            paper.error_message = str(e)[:500]
            paper.save()
        raise


if __name__ == '__main__':
    paper_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    skip_llm = '--no-llm' in sys.argv
    parse_paper_task(paper_id, skip_llm=skip_llm)
