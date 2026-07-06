from django.urls import path

from . import views

urlpatterns = [
    path('hr/dashboard/', views.HRDashboardView.as_view(), name='hr_dashboard'),
    path('hr/reports/', views.ReportsView.as_view(), name='hr_reports'),
]
