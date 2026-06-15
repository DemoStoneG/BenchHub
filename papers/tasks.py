import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'benchhub.settings')

import django
django.setup()

from papers.models import Paper, ExperimentRecord, TableChunk
from services.docling_service import extract_tables as docling_extract_tables


def extract_llm_from_chunks(paper_id: int) -> int:
    """对一篇论文的所有 TableChunk 调用 LLM 提取实验数据 + 打标签。"""
    from services.llm_service import llm_service, _normalize_dataset

    paper = Paper.objects.get(id=paper_id)
    paper.status = Paper.Status.CALLING_LLM
    paper.progress_message = '正在 LLM 提取实验数据...'
    paper.save()

    # 清旧 records（重新提取）
    # paper.results.all().delete()  # 不再全量清空，改为逐表替换

    chunks = list(paper.table_chunks.all())
    total_records = 0

    for tc in chunks:
        paper.progress_message = f'LLM 提取: Table {tc.table_n}/{len(chunks)}...'
        paper.save()

        records, tags, is_experimental, filter_reason = llm_service.extract_from_table_chunk(tc)

        # 保存 tags（含 is_experimental / filter_reason）
        tags['is_experimental'] = is_experimental
        tags['filter_reason'] = filter_reason
        tc.tags = tags
        tc.save(update_fields=['tags'])

        # 仅对实验数据表写入 records；非实验表跳过（但仍保存 tags 中的过滤信息）
        if records and is_experimental and not ExperimentRecord.objects.filter(table_chunk=tc).exists():
            # 噪声数据集名黑名单
            NOISE_DATASETS = {'', 'val', 'test', 'overall', 'noun', 'verb', 'noun verb',
                              'unknown', 'action', 'noun verb score', 'noun top-1 top-5'}
            for rec_data in records:
                dataset = _normalize_dataset(rec_data.get('dataset', ''))
                if dataset.lower() in NOISE_DATASETS:
                    continue
                ExperimentRecord.objects.create(
                    paper=paper,
                    table_chunk=tc,
                    benchmark=rec_data.get('benchmark', ''),
                    dataset=dataset,
                    model_name=rec_data.get('model', ''),
                    metric=rec_data.get('metric', ''),
                    value=float(rec_data.get('value', 0.0)),
                    is_verified=False,
                )
                total_records += 1

    paper.status = Paper.Status.COMPLETED
    paper.progress_message = f'完成，{len(chunks)} 张表格，{total_records} 条数据'
    paper.save()
    return total_records


def parse_paper_task(paper_id: int, skip_llm: bool = False):
    """异步解析论文任务：表格提取 + LLM 数据抽取。

    1. Docling 识别 PDF 中所有表格（正文部分，跳过 Appendix）
    2. 每张表写入 TableChunk（HTML 快照 + caption + page）
    3. 自动调用 LLM 逐表提取实验数据 + 打标签
    """
    paper = None
    try:
        paper = Paper.objects.get(id=paper_id)

        # 清空旧数据
        paper.results.all().delete()
        paper.table_chunks.all().delete()

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

        # Step 2: LLM 逐表提取实验数据 + 打标签
        if not skip_llm:
            extract_llm_from_chunks(paper.id)
        else:
            paper.status = Paper.Status.COMPLETED
            paper.progress_message = f'完成（跳过LLM），{len(tables)} 张表格'
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
