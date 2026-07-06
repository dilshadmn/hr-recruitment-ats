from django.urls import path

from . import views

urlpatterns = [
    path('careers/', views.VacancyListView.as_view(), name='vacancy_list'),
    path('careers/<str:job_code>/', views.VacancyDetailView.as_view(), name='vacancy_detail'),
]
