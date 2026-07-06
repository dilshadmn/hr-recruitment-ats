from django.urls import path

from . import views

urlpatterns = [
    path('careers/<str:job_code>/apply/', views.ApplicationCreateView.as_view(), name='application_create'),
    path('careers/thank-you/<str:candidate_code>/', views.ApplicationThankYouView.as_view(), name='application_thank_you'),
]
