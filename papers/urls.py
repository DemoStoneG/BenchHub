from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='paper_list'),
    path('upload/', views.upload, name='upload'),
    path('paper/<int:paper_id>/', views.paper_detail, name='paper_detail'),
    path('paper/<int:paper_id>/status/', views.paper_status, name='paper_status'),
    path('record/<int:record_id>/', views.update_record, name='update_record'),
    path('record/<int:record_id>/delete/', views.delete_record, name='delete_record'),
    path('paper/<int:paper_id>/add_record/', views.add_record, name='add_record'),
    path('compare/', views.compare, name='compare'),
]
