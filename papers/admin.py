from django.contrib import admin
from django.utils.html import format_html
from .models import Session, Paper, ExperimentRecord, TableImage


class ExperimentRecordInline(admin.TabularInline):
    model = ExperimentRecord
    extra = 0
    fields = ['benchmark', 'model_name', 'dataset', 'metric', 'value', 'is_verified']
    readonly_fields = []


class TableImageInline(admin.TabularInline):
    model = TableImage
    extra = 0
    fields = ['order', 'page_number', 'caption', 'image_preview', 'selected_for_compare']
    readonly_fields = ['image_preview']
    ordering = ['page_number', 'order']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:80px; max-width:200px; border:1px solid #ddd;" />',
                obj.image.url
            )
        return '-'
    image_preview.short_description = '预览'


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
    list_display = ['title', 'session', 'status', 'arxiv_id', 'record_count', 'table_count', 'created_at']
    list_filter = ['status', 'session', 'created_at']
    search_fields = ['title', 'arxiv_id', 'session__name']
    readonly_fields = ['created_at']
    inlines = [ExperimentRecordInline, TableImageInline]

    def record_count(self, obj):
        return obj.results.count()
    record_count.short_description = '记录数'

    def table_count(self, obj):
        return obj.table_images.count()
    table_count.short_description = '表格图数'


@admin.register(ExperimentRecord)
class ExperimentRecordAdmin(admin.ModelAdmin):
    list_display = ['paper', 'benchmark', 'model_name', 'dataset', 'metric', 'value', 'is_verified']
    list_filter = ['benchmark', 'dataset', 'metric', 'is_verified', 'paper__session']
    search_fields = ['model_name', 'dataset', 'benchmark', 'paper__title']
    list_editable = ['is_verified']


@admin.register(TableImage)
class TableImageAdmin(admin.ModelAdmin):
    list_display = ['id', 'paper', 'page_number', 'order', 'caption_preview', 'selected_for_compare', 'image_preview']
    list_filter = ['selected_for_compare', 'paper__session', 'paper']
    search_fields = ['caption', 'paper__title']
    list_editable = ['selected_for_compare', 'order']
    readonly_fields = ['image_preview_large', 'created_at']

    def caption_preview(self, obj):
        if obj.caption:
            return obj.caption[:80] + ('...' if len(obj.caption) > 80 else '')
        return '-'
    caption_preview.short_description = 'caption'

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:40px; max-width:80px; border:1px solid #ddd;" />',
                obj.image.url
            )
        return '-'
    image_preview.short_description = '缩略图'

    def image_preview_large(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:300px; max-width:600px; border:1px solid #ddd;" />',
                obj.image.url
            )
        return '-'
    image_preview_large.short_description = '图片预览'
