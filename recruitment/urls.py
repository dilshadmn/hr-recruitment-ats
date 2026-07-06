from django.urls import path

from . import views
from .models import Candidate

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),

    path('candidates/', views.CandidateListView.as_view(), name='candidate_list'),
    path('candidate/add/', views.CandidateCreateView.as_view(), name='candidate_add'),
    path('candidate/<int:pk>/', views.CandidateDetailView.as_view(), name='candidate_detail'),
    path('candidate/<int:pk>/edit/', views.CandidateUpdateView.as_view(), name='candidate_edit'),

    path('candidate/<int:pk>/shortlist/', views.CandidateStatusActionView.as_view(
        target_status=Candidate.Status.SHORTLISTED), name='candidate_shortlist'),
    path('candidate/<int:pk>/reject/', views.CandidateStatusActionView.as_view(
        target_status=Candidate.Status.REJECTED), name='candidate_reject'),
    path('candidate/<int:pk>/blacklist/', views.CandidateStatusActionView.as_view(
        target_status=Candidate.Status.BLACKLISTED, require_reason=True), name='candidate_blacklist'),
    path('candidate/<int:pk>/hire/', views.CandidateStatusActionView.as_view(
        target_status=Candidate.Status.HIRED), name='candidate_hire'),
    path('candidate/<int:pk>/review/', views.CandidateStatusActionView.as_view(
        target_status=Candidate.Status.UNDER_REVIEW), name='candidate_review'),

    path('candidates/bulk-upload/', views.BulkUploadView.as_view(), name='candidate_bulk_upload'),
    path('candidates/bulk-status/', views.BulkStatusUpdateView.as_view(), name='candidate_bulk_status'),

    path('roles/', views.RoleListView.as_view(), name='role_list'),
    path('roles/add/', views.RoleCreateView.as_view(), name='role_add'),
    path('roles/<int:pk>/edit/', views.RoleUpdateView.as_view(), name='role_edit'),
    path('roles/<int:pk>/delete/', views.RoleDeleteView.as_view(), name='role_delete'),
]
