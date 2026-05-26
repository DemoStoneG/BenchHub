import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'benchhub.settings')

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .models import Paper, ExperimentRecord
from .tasks import parse_paper_task


def index(request):
    """论文列表页"""
    papers = Paper.objects.all()
    return render(request, 'papers/paper_list.html', {'papers': papers})


def upload(request):
    """上传 PDF"""
    if request.method == 'POST' and request.FILES.get('pdf'):
        pdf_file = request.FILES['pdf']
        title = request.POST.get('title', pdf_file.name)
        arxiv_id = request.POST.get('arxiv_id', '')

        paper = Paper.objects.create(
            title=title,
            arxiv_id=arxiv_id,
            local_pdf=pdf_file,
            status=Paper.Status.PENDING
        )

        subprocess.Popen(
            [sys.executable, str(settings.BASE_DIR / 'papers' / 'tasks.py'), str(paper.id)],
            cwd=str(settings.BASE_DIR)
        )

        return JsonResponse({'id': paper.id, 'status': 'started'})

    return render(request, 'papers/upload.html')


def paper_status(request, paper_id):
    """轮询论文解析状态"""
    paper = get_object_or_404(Paper, id=paper_id)
    return JsonResponse({
        'id': paper.id,
        'status': paper.status,
        'error_message': paper.error_message
    })


def paper_detail(request, paper_id):
    """论文详情/校验页"""
    paper = get_object_or_404(Paper, id=paper_id)
    records = paper.results.all()
    return render(request, 'papers/review.html', {
        'paper': paper,
        'records': records
    })


def serve_pdf(request, paper_id):
    """专用 PDF 预览视图"""
    paper = get_object_or_404(Paper, id=paper_id)
    if not paper.local_pdf:
        return HttpResponse("No PDF", status=404)

    with open(paper.local_pdf.path, 'rb') as f:
        pdf_content = f.read()

    response = HttpResponse(pdf_content, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{paper.title}.pdf"'
    # 显式移除 X-Frame-Options
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@csrf_exempt
def update_record(request, record_id):
    """更新单条实验记录"""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        record = get_object_or_404(ExperimentRecord, id=record_id)

        record.dataset = data.get('dataset', record.dataset)
        record.model_name = data.get('model_name', record.model_name)
        record.metric = data.get('metric', record.metric)
        record.value = float(data.get('value', record.value))
        record.is_verified = data.get('is_verified', record.is_verified)
        record.save()

        return JsonResponse({'status': 'ok'})

    return JsonResponse({'status': 'error'}, status=400)


def delete_record(request, record_id):
    """删除单条实验记录"""
    if request.method == 'POST':
        record = get_object_or_404(ExperimentRecord, id=record_id)
        record.delete()
        return JsonResponse({'status': 'ok'})

    return JsonResponse({'status': 'error'}, status=400)


def add_record(request, paper_id):
    """为论文添加实验记录"""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        paper = get_object_or_404(Paper, id=paper_id)

        record = ExperimentRecord.objects.create(
            paper=paper,
            dataset=data.get('dataset', ''),
            model_name=data.get('model_name', ''),
            metric=data.get('metric', ''),
            value=float(data.get('value', 0.0)),
            is_verified=True
        )

        return JsonResponse({'id': record.id, 'status': 'ok'})

    return JsonResponse({'status': 'error'}, status=400)


def compare(request):
    """对比视图"""
    selected_ids = request.GET.getlist('papers')
    papers = Paper.objects.filter(id__in=selected_ids) if selected_ids else []

    if not papers:
        all_papers = Paper.objects.all()
        return render(request, 'papers/compare.html', {'papers': all_papers, 'selected': []})

    records = ExperimentRecord.objects.filter(paper__in=papers)
    datasets = sorted(set(r.dataset for r in records))
    models = sorted(set(r.model_name for r in records))

    data = [ {
        'model': r.model_name,
        'dataset': r.dataset,
        'metric': r.metric,
        'value': r.value
    } for r in records ]

    from services.latex_service import latex_service
    latex_code = latex_service.generate_table(data, datasets, models)

    return render(request, 'papers/compare.html', {
        'papers': papers,
        'selected': [p.id for p in papers],
        'records': records,
        'datasets': datasets,
        'models': models,
        'latex_code': latex_code
    })
