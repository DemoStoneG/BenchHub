from django.urls import path
from . import views

urlpatterns = [
    # 项目 (Project) 路由
    path('', views.session_list, name='session_list'),
    path('projects/', views.session_list, name='project_list'),
    path('projects/new/', views.session_create, name='project_create'),
    path('projects/<int:session_id>/', views.session_detail, name='project_detail'),
    path('projects/<int:session_id>/edit/', views.session_edit, name='project_edit'),
    path('projects/<int:session_id>/delete/', views.session_delete, name='project_delete'),
    path('projects/<int:session_id>/upload/', views.upload, name='upload'),

    # 排行榜（按项目划分）
    path('projects/<int:session_id>/leaderboards/', views.leaderboard_list, name='leaderboard_list'),
    path('projects/<int:session_id>/leaderboards/detail/', views.leaderboard_detail, name='leaderboard_detail'),

    # 论文 (Article) 路由
    path('articles/<int:paper_id>/', views.paper_detail, name='article_detail'),
    path('articles/<int:paper_id>/pdf/', views.serve_pdf, name='serve_pdf'),
    path('articles/<int:paper_id>/status/', views.paper_status, name='article_status'),
    path('articles/<int:paper_id>/retry/', views.retry_parse, name='article_retry'),
    path('articles/<int:paper_id>/delete/', views.paper_delete, name='article_delete'),
]
