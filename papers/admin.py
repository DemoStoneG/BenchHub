from django.contrib import admin
from .models import Paper, ExperimentRecord


class ExperimentRecordInline(admin.TabularInline):
    model = ExperimentRecord
    extra = 0


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['title', 'arxiv_id']
    inlines = [ExperimentRecordInline]


@admin.register(ExperimentRecord)
class ExperimentRecordAdmin(admin.ModelAdmin):
    list_display = ['model_name', 'dataset', 'metric', 'value', 'paper', 'is_verified']
    list_filter = ['dataset', 'metric', 'is_verified']
    search_fields = ['model_name', 'dataset', 'paper__title']
