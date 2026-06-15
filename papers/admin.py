from django.contrib import admin
from .models import Session, Paper, ExperimentRecord


class ExperimentRecordInline(admin.TabularInline):
    model = ExperimentRecord
    extra = 0
    fields = ['benchmark', 'model_name', 'dataset', 'metric', 'value', 'is_verified']


class PaperInline(admin.TabularInline):
    model = Paper
    extra = 0
    fields = ['title', 'status', 'arxiv_id', 'created_at']
    readonly_fields = ['created_at']
    show_change_link = True
    ordering = ['-created_at']


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ['name', 'paper_count', 'record_count_display', 'updated_at']
    search_fields = ['name', 'description']
    list_filter = ['updated_at']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [PaperInline]

    def paper_count(self, obj):
        return obj.papers.count()
    paper_count.short_description = '论文数'

    def record_count_display(self, obj):
        return ExperimentRecord.objects.filter(paper__session=obj).count()
    record_count_display.short_description = '数据条数'


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ['title', 'session', 'status', 'arxiv_id', 'record_count', 'table_chunk_count', 'created_at']
    list_filter = ['status', 'session', 'created_at']
    search_fields = ['title', 'arxiv_id', 'session__name']
    readonly_fields = ['created_at']
    inlines = [ExperimentRecordInline]

    def record_count(self, obj):
        return obj.results.count()
    record_count.short_description = '记录数'

    def table_chunk_count(self, obj):
        return obj.table_chunks.count()
    table_chunk_count.short_description = '表格数'


@admin.register(ExperimentRecord)
class ExperimentRecordAdmin(admin.ModelAdmin):
    list_display = ['paper', 'benchmark', 'model_name', 'dataset', 'metric', 'value', 'is_verified']
    list_filter = ['benchmark', 'dataset', 'metric', 'is_verified', 'paper__session']
    search_fields = ['model_name', 'dataset', 'benchmark', 'paper__title']
    list_editable = ['is_verified']
