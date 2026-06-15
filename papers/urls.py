from django.urls import path
from . import views

urlpatterns = [
    # 项目 (Project) 路由 - 之前叫 Session
    path('', views.session_list, name='session_list'),
    path('projects/', views.session_list, name='project_list'),
    path('projects/new/', views.session_create, name='project_create'),
    path('projects/<int:session_id>/', views.session_detail, name='project_detail'),
    path('projects/<int:session_id>/edit/', views.session_edit, name='project_edit'),
    path('projects/<int:session_id>/delete/', views.session_delete, name='project_delete'),
    path('projects/<int:session_id>/upload/', views.upload, name='upload'),
    path('projects/<int:session_id>/compare/', views.compare, name='compare'),

    # 论文 (Article) 路由
    path('articles/<int:paper_id>/', views.paper_detail, name='article_detail'),
    path('articles/<int:paper_id>/pdf/', views.serve_pdf, name='serve_pdf'),
    path('articles/<int:paper_id>/status/', views.paper_status, name='article_status'),
    path('articles/<int:paper_id>/retry/', views.retry_parse, name='article_retry'),
    path('articles/<int:paper_id>/delete/', views.paper_delete, name='article_delete'),
    path('articles/<int:paper_id>/add_record/', views.add_record, name='add_record'),
    path('articles/<int:paper_id>/verify_all/', views.verify_all_records, name='verify_all_records'),
    path('articles/<int:paper_id>/merge_metrics/', views.merge_metrics, name='merge_metrics'),

    # 表格图片
    path('table-images/<int:table_id>/toggle/', views.toggle_table_compare, name='toggle_table_compare'),
    path('table-images/<int:table_id>/confirm/', views.confirm_table_records, name='confirm_table_records'),
    path('table-images/<int:table_id>/delete-group/', views.delete_table_group, name='delete_table_group'),

    # 记录
    path('records/<int:record_id>/', views.update_record, name='update_record'),
    path('records/<int:record_id>/delete/', views.delete_record, name='delete_record'),

    # AI 表格提取
    path('articles/<int:paper_id>/extract-tables/', views.extract_tables_api, name='extract_tables_api'),
]
