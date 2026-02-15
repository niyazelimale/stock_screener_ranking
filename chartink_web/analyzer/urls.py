from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/scan/start/', views.start_scan, name='start_scan'),
    path('api/status/<int:job_id>/', views.scan_status, name='scan_status'),
    path('results/<int:job_id>/', views.result_detail, name='result_detail'),
    
    path('config/', views.screener_list, name='screener_list'),
    path('config/add/', views.screener_add, name='screener_add'),
    path('config/edit/<int:id>/', views.screener_edit, name='screener_edit'),
    path('config/delete/<int:id>/', views.screener_delete, name='screener_delete'),
    path('config/import/', views.screener_import, name='screener_import'),
    path('settings/update/', views.update_settings, name='update_settings'),
    
    path('new-stocks/', views.new_stocks_view, name='new_stocks'),
    path('download-csv/<int:job_id>/', views.download_csv, name='download_csv'),
]
