import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'benchhub.settings')

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .models import Session, Paper, ExperimentRecord, TableImage, TableChunk
from .tasks import parse_paper_task


# ============== Session 相关 ==============

def session_list(request):
    """首页：列出所有 session（项目）"""
    q = request.GET.get('q', '').strip()
    sessions = Session.objects.all()
    if q:
        sessions = sessions.filter(name__icontains=q)

    # 每个 session 附加一些统计信息
    session_data = []
    for s in sessions:
        papers = s.papers.all()
        session_data.append({
            'obj': s,
            'paper_count': papers.count(),
            'completed_count': papers.filter(status=Paper.Status.COMPLETED).count(),
            'record_count': ExperimentRecord.objects.filter(paper__session=s).count(),
        })

    return render(request, 'papers/session_list.html', {
        'sessions': session_data,
        'q': q,
    })


def session_create(request):
    """创建新 session"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        if not name:
            return render(request, 'papers/session_form.html', {
                'error': '项目名称不能为空',
                'name': name,
                'description': description,
            })
        session = Session.objects.create(name=name, description=description)
        return redirect('project_detail', session_id=session.id)
    return render(request, 'papers/session_form.html', {'session': None})


def session_edit(request, session_id):
    """编辑 session"""
    session = get_object_or_404(Session, id=session_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        if not name:
            return render(request, 'papers/session_form.html', {
                'session': session,
                'error': '项目名称不能为空',
            })
        session.name = name
        session.description = description
        session.save()
        return redirect('project_detail', session_id=session.id)
    return render(request, 'papers/session_form.html', {'session': session})


@csrf_exempt
def session_delete(request, session_id):
    session = get_object_or_404(Session, id=session_id)
    if request.method == 'POST':
        name = session.name
        session.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'ok', 'deleted': name})
        return redirect('session_list')
    return render(request, 'papers/session_confirm_delete.html', {'session': session})


def session_detail(request, session_id):
    """session 详情页：显示该 session 下的论文列表、上传/对比按钮"""
    session = get_object_or_404(Session, id=session_id)

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    papers = session.papers.all()
    if q:
        papers = papers.filter(title__icontains=q)
    if status:
        papers = papers.filter(status=status)

    return render(request, 'papers/session_detail.html', {
        'session_obj': session,
        'papers': papers,
        'q': q,
        'status_filter': status,
        'status_choices': Paper.Status.choices,
    })


# ============== 上传与对比（session 作用域） ==============

def upload(request, session_id):
    """上传 PDF（必须指定 session）"""
    session = get_object_or_404(Session, id=session_id)

    if request.method == 'POST' and request.FILES.get('pdf'):
        pdf_file = request.FILES['pdf']
        title = request.POST.get('title', pdf_file.name)
        arxiv_id = request.POST.get('arxiv_id', '')

        paper = Paper.objects.create(
            session=session,
            title=title,
            arxiv_id=arxiv_id,
            local_pdf=pdf_file,
            status=Paper.Status.PENDING
        )

        subprocess.Popen(
            [sys.executable, str(settings.BASE_DIR / 'papers' / 'tasks.py'), str(paper.id)],
            cwd=str(settings.BASE_DIR)
        )

        return JsonResponse({'id': paper.id, 'status': 'started', 'session_id': session.id})

    return render(request, 'papers/upload.html', {'session_obj': session})


def compare(request, session_id):
    """对比视图（仅展示该 session 内的论文）"""
    session = get_object_or_404(Session, id=session_id)

    selected_ids = request.GET.getlist('papers')
    selected_ids = [int(i) for i in selected_ids if i.isdigit()]
    # 强制只取当前 session 的论文
    papers_qs = session.papers.all()
    selected_papers = papers_qs.filter(id__in=selected_ids) if selected_ids else papers_qs.none()

    if not selected_ids:
        return render(request, 'papers/compare.html', {
            'session_obj': session,
            'papers': papers_qs,
            'selected': [],
            'models': [],
            'bench_groups': [],
            'latex_code': '',
        })

    records = list(ExperimentRecord.objects.filter(paper__in=selected_papers))

    # 模型集合（取所有论文的并集，每个 benchmark 表都会展示）
    models = sorted(set(r.model_name for r in records))
    benchmarks = sorted(set(r.benchmark or '(未指定)' for r in records))

    # 按 benchmark 分组，每个 benchmark 自带 datasets/metrics/records
    bench_groups = []
    for bench in benchmarks:
        bench_records = [r for r in records if (r.benchmark or '(未指定)') == bench]
        bench_datasets = sorted(set(r.dataset for r in bench_records))
        bench_metrics = sorted(set(r.metric for r in bench_records))
        bench_groups.append({
            'name': bench,
            'records': bench_records,
            'datasets': bench_datasets,
            'metrics': bench_metrics,
            'dataset_colspan': len(bench_metrics),
        })

    # LaTeX：每个 benchmark 一段 tabular
    data = [{
        'model': r.model_name,
        'benchmark': r.benchmark,
        'dataset': r.dataset,
        'metric': r.metric,
        'value': r.value
    } for r in records]

    from services.latex_service import latex_service
    latex_code = latex_service.generate_tables_by_benchmark(data)

    return render(request, 'papers/compare.html', {
        'session_obj': session,
        'papers': papers_qs,
        'selected': [p.id for p in selected_papers],
        'selected_papers': selected_papers,
        'records': records,
        'models': models,
        'bench_groups': bench_groups,
        'latex_code': latex_code,
    })


# ============== Paper 操作 ==============

def paper_status(request, paper_id):
    paper = get_object_or_404(Paper, id=paper_id)
    return JsonResponse({
        'id': paper.id,
        'status': paper.status,
        'progress_message': paper.progress_message,
        'error_message': paper.error_message
    })


@csrf_exempt
def retry_parse(request, paper_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)

    paper = get_object_or_404(Paper, id=paper_id)
    paper.status = Paper.Status.PENDING
    paper.error_message = ''
    paper.progress_message = ''
    paper.save()

    subprocess.Popen(
        [sys.executable, str(settings.BASE_DIR / 'papers' / 'tasks.py'), str(paper.id)],
        cwd=str(settings.BASE_DIR)
    )

    return JsonResponse({'id': paper.id, 'status': 'started'})


@csrf_exempt
def paper_delete(request, paper_id):
    """删除一篇论文：清理 PDF 文件 + 实验数据"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)

    paper = get_object_or_404(Paper, id=paper_id)
    title = paper.title or f"#{paper.id}"
    session_id = paper.session_id

    # 先删物理 PDF（FieldFile.delete 删 storage 上的文件）
    try:
        if paper.local_pdf:
            paper.local_pdf.delete(save=False)
    except Exception:
        pass

    # 再删数据库记录（会级联删 ExperimentRecord）
    paper.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok', 'deleted': title, 'session_id': session_id})
    return redirect('project_detail', session_id=session_id)


def _chunk_to_renderable(tc) -> dict:
    """TableChunk → 模板可用 dict。支持 docling HTML 和结构化解析两种来源。"""
    # Docling 路径：直接渲染 HTML
    if tc.extraction_method == 'docling':
        bbox = tc.bbox_json if isinstance(tc.bbox_json, dict) else {}
        return {
            'id': tc.id,
            'table_n': tc.table_n,
            'page': tc.page,
            'caption': tc.caption,
            'extraction_method': tc.extraction_method,
            'is_section_header': False,
            'section_text': '',
            'header_rows': [],
            'body_rows': [],
            'markdown_text': '',
            'has_structured': False,
            'is_docling_html': True,
            'html_content': bbox.get('html', tc.markdown_text),
            'html_rows': bbox.get('rows', 0),
            'html_cols': bbox.get('cols', 0),
        }

    # 结构化解析路径（旧 camelot 数据保留兼容）
    bbox = tc.bbox_json if isinstance(tc.bbox_json, dict) else {}
    body_rows = bbox.get('body_rows', [])
    is_section_header = bool(bbox.get('is_section_header'))
    section_text = ''
    if is_section_header and body_rows:
        first = body_rows[0][0] if body_rows[0] else {}
        section_text = first.get('text', '') if isinstance(first, dict) else str(first)

    rendered_body = []
    for row in body_rows:
        if not row or not isinstance(row[0], dict):
            rendered_body.append(row)
            continue
        section_cell = next((c for c in row if isinstance(c, dict) and c.get('is_section_marker')), None)
        if section_cell:
            new_row = list(row)
            new_row[0] = {
                **section_cell,
                'colspan': len(row),
            }
            rendered_body.append(new_row)
        else:
            rendered_body.append(row)

    return {
        'id': tc.id,
        'table_n': tc.table_n,
        'page': tc.page,
        'caption': tc.caption,
        'extraction_method': tc.extraction_method,
        'is_section_header': is_section_header,
        'section_text': section_text,
        'header_rows': tc.header_json,
        'body_rows': rendered_body,
        'markdown_text': tc.markdown_text,
        'has_structured': bool(tc.header_json) or bool(body_rows),
        'is_docling_html': False,
        'html_content': '',
    }


def paper_detail(request, paper_id):
    """论文详情：按 TableChunk 分组展示。
    每组 = 一个 TableChunk（结构化 header/body + records）+ 该 chunk 抽取出的 records。
    """
    paper = get_object_or_404(Paper, id=paper_id)
    records = list(paper.results.all())
    chunks = list(paper.table_chunks.all().prefetch_related('records'))

    # 按 table_chunk_id 分组
    records_by_chunk = {}
    for r in records:
        key = r.table_chunk_id
        records_by_chunk.setdefault(key, []).append(r)

    chunk_groups = []  # [{'chunk': dict(renderable), 'records': [...]}]
    for tc in chunks:
        chunk_groups.append({
            'chunk': _chunk_to_renderable(tc),
            'records': records_by_chunk.get(tc.id, []),
        })
    unlinked = records_by_chunk.get(None, [])
    if unlinked:
        chunk_groups.append({
            'chunk': None,
            'records': unlinked,
        })

    metric_counts = {}
    bench_counts = {}
    for r in records:
        metric_counts[r.metric] = metric_counts.get(r.metric, 0) + 1
        b = r.benchmark or '(未指定)'
        bench_counts[b] = bench_counts.get(b, 0) + 1
    metric_summary = sorted(metric_counts.items(), key=lambda x: -x[1])
    bench_summary = sorted(bench_counts.items(), key=lambda x: -x[1])

    return render(request, 'papers/review.html', {
        'paper': paper,
        'records': records,
        'chunk_groups': chunk_groups,
        'metric_summary': metric_summary,
        'bench_summary': bench_summary,
        'verified_count': sum(1 for r in records if r.is_verified),
    })


@csrf_exempt
def toggle_table_compare(request, table_id):
    """切换某张表格是否参与对比"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)
    table = get_object_or_404(TableImage, id=table_id)
    data = {}
    try:
        import json
        data = json.loads(request.body or b'{}')
    except Exception:
        pass
    if 'selected' in data:
        table.selected_for_compare = bool(data['selected'])
    else:
        table.selected_for_compare = not table.selected_for_compare
    table.save(update_fields=['selected_for_compare'])
    return JsonResponse({'status': 'ok', 'id': table.id, 'selected': table.selected_for_compare})


@csrf_exempt
def confirm_table_records(request, table_id):
    """确认某张表下的所有 record（标记为已校验）"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)
    table = get_object_or_404(TableImage, id=table_id)
    updated = table.records.filter(is_verified=False).update(is_verified=True)
    return JsonResponse({'status': 'ok', 'updated': updated, 'table_id': table.id})


@csrf_exempt
def delete_table_group(request, table_id):
    """删除整张表：先删 record，再删物理图片 + TableImage 行"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)
    table = get_object_or_404(TableImage, id=table_id)
    paper_id = table.paper_id
    records_deleted = table.records.count()
    table.records.all().delete()
    try:
        if table.image:
            table.image.delete(save=False)
    except Exception:
        pass
    table.delete()
    return JsonResponse({
        'status': 'ok',
        'paper_id': paper_id,
        'records_deleted': records_deleted,
    })


def serve_pdf(request, paper_id):
    paper = get_object_or_404(Paper, id=paper_id)
    if not paper.local_pdf:
        return HttpResponse("No PDF", status=404)

    with open(paper.local_pdf.path, 'rb') as f:
        pdf_content = f.read()

    response = HttpResponse(pdf_content, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{paper.title}.pdf"'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


# ============== Record 操作 ==============

@csrf_exempt
def update_record(request, record_id):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        record = get_object_or_404(ExperimentRecord, id=record_id)

        if 'benchmark' in data:
            record.benchmark = data['benchmark']
        record.dataset = data.get('dataset', record.dataset)
        record.model_name = data.get('model_name', record.model_name)
        record.metric = data.get('metric', record.metric)
        record.value = float(data.get('value', record.value))
        record.is_verified = data.get('is_verified', record.is_verified)
        record.save()

        return JsonResponse({'status': 'ok'})

    return JsonResponse({'status': 'error'}, status=400)


def delete_record(request, record_id):
    if request.method == 'POST':
        record = get_object_or_404(ExperimentRecord, id=record_id)
        record.delete()
        return JsonResponse({'status': 'ok'})

    return JsonResponse({'status': 'error'}, status=400)


def add_record(request, paper_id):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        paper = get_object_or_404(Paper, id=paper_id)

        record = ExperimentRecord.objects.create(
            paper=paper,
            benchmark=data.get('benchmark', ''),
            dataset=data.get('dataset', ''),
            model_name=data.get('model_name', ''),
            metric=data.get('metric', ''),
            value=float(data.get('value', 0.0)),
            is_verified=True
        )

        return JsonResponse({'id': record.id, 'status': 'ok'})

    return JsonResponse({'status': 'error'}, status=400)


@csrf_exempt
def verify_all_records(request, paper_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)

    paper = get_object_or_404(Paper, id=paper_id)
    updated = paper.results.filter(is_verified=False).update(is_verified=True)
    return JsonResponse({'status': 'ok', 'updated': updated})


def extract_tables_api(request, paper_id):
    """AI 表格提取 API：用 Table Transformer 提取 PDF 中的所有表格，返回 HTML。"""
    paper = get_object_or_404(Paper, id=paper_id)
    if not paper.local_pdf or not os.path.exists(paper.local_pdf.path):
        return JsonResponse({'status': 'error', 'msg': 'PDF 文件不存在'}, status=400)

    try:
        from services.docling_service import extract_tables as docling_extract

        tables = docling_extract(paper.local_pdf.path)
        return JsonResponse({'status': 'ok', 'tables': tables})
    except Exception as e:
        import traceback
        return JsonResponse({
            'status': 'error',
            'msg': str(e)[:500],
            'traceback': traceback.format_exc()[-500:],
        }, status=500)


@csrf_exempt
def merge_metrics(request, paper_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=400)

    import json
    data = json.loads(request.body)
    target = data.get('target', '').strip()
    sources = data.get('sources', [])

    if not target or not sources:
        return JsonResponse({'status': 'error', 'msg': 'target 或 sources 为空'}, status=400)

    paper = get_object_or_404(Paper, id=paper_id)
    updated = 0
    skipped = 0
    for record in paper.results.filter(metric__in=sources):
        collision = paper.results.filter(
            model_name=record.model_name,
            dataset=record.dataset,
            metric=target
        ).exclude(id=record.id).exists()
        if collision:
            skipped += 1
            continue
        record.metric = target
        record.save(update_fields=['metric'])
        updated += 1

    return JsonResponse({'status': 'ok', 'updated': updated, 'skipped': skipped})

