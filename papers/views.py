import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'benchhub.settings')

from collections import defaultdict

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .models import Session, Paper, ExperimentRecord, TableChunk
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
            'tags': tc.tags if isinstance(tc.tags, dict) else {},
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
        'tags': tc.tags if isinstance(tc.tags, dict) else {},
    }


def paper_detail(request, paper_id):
    """论文详情：展示提取的表格，每张表标注提取数据条数。"""
    paper = get_object_or_404(Paper, id=paper_id)
    chunks = list(paper.table_chunks.all().prefetch_related('records'))
    total_records = sum(tc.records.count() for tc in chunks)

    chunk_groups = []
    for tc in chunks:
        chunk_groups.append({
            'chunk': _chunk_to_renderable(tc),
            'records_count': tc.records.count(),
        })

    return render(request, 'papers/review.html', {
        'paper': paper,
        'chunk_groups': chunk_groups,
        'total_records': total_records,
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


# ============== 排行榜 ==============

# Benchmark 任务说明（中文）
BENCHMARK_DESCRIPTIONS = {
    'Action Recognition': '动作识别：给定一段视频，判断其中人物正在执行的动作类别（如切菜、开门）。EPIC-KITCHENS 数据集按 Verb（动词）、Noun（名词）、Action（动作）三个维度评估。',
    'UDA': 'UDA（无监督领域自适应）：在源域（如特定厨房）训练模型，在目标域（不同的厨房/场景）测试，考察模型跨场景泛化能力。',
    'DG': 'DG（领域泛化）：类似 UDA，但目标域完全不可见，模型在训练时不能接触任何目标域数据，更贴近真实部署场景。',
    'Multi-Instance Retrieval': '多实例检索：给定一段文本描述，从视频库中检索出与之匹配的视频片段。评估指标为 mAP 和 nDCG。EPIC-KITCHENS 下有 V2T（视频检索文本）和 T2V（文本检索视频）两个子任务。',
    'Video-Text Retrieval': '视频-文本检索：衡量模型将视频内容与自然语言描述对齐的能力。与 Multi-Instance Retrieval 类似但侧重不同评估协议。',
    'NLQ': 'NLQ（自然语言查询）：给定一句自然语言问题（如"他刚才拿了什么？"），模型需在视频中定位答案片段。评估指标为 R@1 和 R@5（IoU 阈值）。',
    'Moment Query': '时刻查询：给定一个时间范围描述，模型需在长视频中精确定位对应片段。评估 R@1/R@5 和 mAP（多个 IoU 阈值）。',
    'Object State Change Classification': '物体状态变化分类：判断视频中物体状态是否发生变化（如瓶子从满→空），属细粒度时序理解任务。',
    'Long-term Action Anticipation': '长期动作预测：根据已观察的视频前缀，预测未来会发生的一系列动作及其时间点，属预测性任务。',
    'EgoMCQ': 'EgoMCQ（自监督视频-文本匹配）：通过对比学习判断视频片段与文本描述的匹配程度，包含 Intra-video（同视频内）和 Inter-video（跨视频）两种负样本策略。',
    'Ego4D Moment Retrieval': 'Ego4D 时刻检索：在 Ego4D 大规模第一人称视频数据集上根据文本查询定位时刻片段。',
    'Active Speaker Localization': '活跃说话人定位：在多说话人场景中识别当前正在说话的人，评估 mAP。',
    'ASL': 'ASL（自监督学习任务）：评估自监督预训练模型在下游任务上的迁移能力。',
    'Egocentric Action Recognition': '第一人称动作识别：与 Action Recognition 相同任务，但特指第一人称视角（穿戴相机）场景。',
}

# 描述无法覆盖的 benchmark 时，自动从关联的 TableChunk caption 中提取说明
def _get_benchmark_description(bench_name: str) -> str:
    """获取 Benchmark 的文字说明：优先匹配预定义描述 -> 抓一条 TableChunk caption 作为兜底。"""
    desc = BENCHMARK_DESCRIPTIONS.get(bench_name, '')
    if desc:
        return desc
    # 从所有该 Benchmark 的 TableChunk 中取第一条 caption 作为参考
    tc = TableChunk.objects.filter(records__benchmark=bench_name).first()
    if tc and tc.caption:
        return f'(从论文 caption 中自动提取) {tc.caption[:200]}'
    return ''


def leaderboard_list(request, session_id):
    """排行榜列表：按 Benchmark 分组，每组建一张卡片。点击进入包含多个数据集排名表的详情页。"""
    session = get_object_or_404(Session, id=session_id)

    records = ExperimentRecord.objects.select_related('paper', 'table_chunk').filter(
        paper__session=session
    )

    bench_groups = defaultdict(lambda: {'datasets': set(), 'papers': set(), 'models': set(), 'all_records': []})
    for r in records:
        bench = r.benchmark.strip()
        if not bench or bench == '(未指定)':
            continue
        g = bench_groups[bench]
        g['datasets'].add(r.dataset)
        g['papers'].add(r.paper_id)
        g['models'].add(r.model_name)
        g['all_records'].append(r)

    cards = []
    for bench in sorted(bench_groups.keys()):
        g = bench_groups[bench]
        best = max(g['all_records'], key=lambda r: r.value)
        metrics = sorted(set(r.metric for r in g['all_records']))
        cards.append({
            'benchmark': bench,
            'dataset_count': len(g['datasets']),
            'model_count': len(g['models']),
            'paper_count': len(g['papers']),
            'metrics': metrics,
            'best_model': best.model_name,
            'best_value': best.value,
            'best_metric': best.metric,
        })

    return render(request, 'papers/leaderboard_list.html', {
        'session_obj': session,
        'cards': cards,
    })


def leaderboard_detail(request, session_id):
    """排行榜详情：单个 Benchmark 下的所有数据集排名表（可排序）。"""
    session = get_object_or_404(Session, id=session_id)
    bench = request.GET.get('benchmark', '').strip()

    if not bench:
        return render(request, 'papers/leaderboard_detail.html', {
            'session_obj': session,
            'error': '缺少 benchmark 参数',
        })

    records = ExperimentRecord.objects.select_related('paper').filter(
        paper__session=session,
        benchmark=bench,
    )

    if not records.exists():
        return render(request, 'papers/leaderboard_detail.html', {
            'session_obj': session,
            'benchmark': bench,
            'error': '该 Benchmark 暂无数据',
        })

    # 按 dataset 分组，每组一个排名表（不排序，交给前端 Alpine.js）
    by_dataset = defaultdict(list)
    for r in records:
        by_dataset[r.dataset].append(r)

    datasets = []
    for ds_name in sorted(by_dataset.keys()):
        ds_records = by_dataset[ds_name]
        all_metrics = sorted(set(r.metric for r in ds_records))

        model_data = defaultdict(lambda: {'metrics': {}})
        for r in ds_records:
            m = model_data[r.model_name]
            m['paper_id'] = r.paper_id
            m['paper_title'] = r.paper.title
            m['table_chunk_id'] = r.table_chunk_id
            m['metrics'][r.metric] = round(r.value, 2) if r.value != int(r.value) else int(r.value)

        models = [{'model': name, **data} for name, data in model_data.items()]

        datasets.append({
            'name': ds_name,
            'all_metrics': all_metrics,
            'default_metric': all_metrics[0] if all_metrics else '',
            'models': models,
            'model_count': len(model_data),
        })

    return render(request, 'papers/leaderboard_detail.html', {
        'session_obj': session,
        'benchmark': bench,
        'datasets': datasets,
        'description': _get_benchmark_description(bench),
    })