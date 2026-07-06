import os
import tempfile

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from . import services
from .forms import BulkStatusForm, BulkUploadForm, CandidateForm, RoleForm
from .models import Candidate, Role

TAB_STATUS_MAP = {
    'central': None,
    'under_review': Candidate.Status.UNDER_REVIEW,
    'shortlisted': Candidate.Status.SHORTLISTED,
    'rejected': Candidate.Status.REJECTED,
    'blacklisted': Candidate.Status.BLACKLISTED,
}


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'recruitment/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['tabs'] = [
            {
                'key': key,
                'label': label,
                'count': (
                    Candidate.objects.count()
                    if status is None
                    else Candidate.objects.filter(current_status=status).count()
                ),
            }
            for key, label, status in services.DASHBOARD_TABS
        ]
        ctx['active_tab'] = self.request.GET.get('tab', 'central')
        return ctx


class CandidateListView(LoginRequiredMixin, ListView):
    model = Candidate
    template_name = 'recruitment/candidate_list.html'
    context_object_name = 'candidates'
    paginate_by = None  # DataTables handles paging client-side

    def get_tab(self):
        return self.request.GET.get('tab', 'central')

    def get_queryset(self):
        qs = Candidate.objects.select_related('role').all()
        tab = self.get_tab()
        status = TAB_STATUS_MAP.get(tab, None)
        if tab != 'central' and status is not None:
            qs = qs.filter(current_status=status)

        role_id = self.request.GET.get('role')
        if role_id:
            qs = qs.filter(role_id=role_id)

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q))

        status_filter = self.request.GET.get('status')
        if status_filter:
            qs = qs.filter(current_status=status_filter)

        return qs

    def get(self, request, *args, **kwargs):
        if request.GET.get('export') == '1':
            buffer = services.export_candidates_xlsx(self.get_queryset())
            response = HttpResponse(
                buffer.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = 'attachment; filename="candidates.xlsx"'
            return response
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['tab'] = self.get_tab()
        ctx['tabs'] = services.DASHBOARD_TABS
        ctx['roles'] = Role.objects.all()
        ctx['status_choices'] = Candidate.Status.choices
        ctx['query_string'] = self.request.GET.urlencode()
        return ctx


class CandidateDetailView(LoginRequiredMixin, DetailView):
    model = Candidate
    template_name = 'recruitment/candidate_detail.html'
    context_object_name = 'candidate'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['history'] = self.object.history.select_related('changed_by').all()
        return ctx


class CandidateCreateView(LoginRequiredMixin, CreateView):
    model = Candidate
    form_class = CandidateForm
    template_name = 'recruitment/candidate_form.html'

    def form_valid(self, form):
        candidate = form.save(commit=False)
        status, duplicate_flag = services.determine_initial_status(candidate.email)
        candidate.current_status = status
        candidate.duplicate_flag = duplicate_flag
        candidate.save()
        services.record_creation(candidate, user=self.request.user)
        if duplicate_flag:
            messages.warning(
                self.request,
                f'{candidate.full_name} matched an existing email and was marked '
                f'"{candidate.get_current_status_display()}".',
            )
        else:
            messages.success(self.request, f'{candidate.full_name} added to the Central Repository.')
        self.object = candidate
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse('candidate_detail', args=[self.object.pk])


class CandidateUpdateView(LoginRequiredMixin, UpdateView):
    model = Candidate
    form_class = CandidateForm
    template_name = 'recruitment/candidate_form.html'

    def form_valid(self, form):
        messages.success(self.request, f'{form.instance.full_name} updated.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('candidate_detail', args=[self.object.pk])


class CandidateStatusActionView(LoginRequiredMixin, View):
    """Generic POST-only status transition, reused for shortlist / reject /
    blacklist / hire / move-to-review so each is a one-line urls.py entry."""
    target_status = None
    require_reason = False

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        reason = request.POST.get('blacklist_reason', '').strip()
        if self.require_reason and not reason:
            messages.error(request, 'A reason is required to blacklist a candidate.')
            return redirect(request.POST.get('next') or reverse('candidate_detail', args=[pk]))

        services.change_status(candidate, self.target_status, user=request.user, blacklist_reason=reason or None)
        messages.success(
            request, f'{candidate.full_name} moved to "{candidate.get_current_status_display()}".'
        )
        next_url = request.POST.get('next')
        return redirect(next_url or reverse('candidate_detail', args=[pk]))


class RoleListView(LoginRequiredMixin, ListView):
    model = Role
    template_name = 'recruitment/roles.html'
    context_object_name = 'roles'


class RoleCreateView(LoginRequiredMixin, CreateView):
    model = Role
    form_class = RoleForm
    template_name = 'recruitment/role_form.html'
    success_url = reverse_lazy('role_list')

    def form_valid(self, form):
        messages.success(self.request, f'Role "{form.instance.title}" created.')
        return super().form_valid(form)


class RoleUpdateView(LoginRequiredMixin, UpdateView):
    model = Role
    form_class = RoleForm
    template_name = 'recruitment/role_form.html'
    success_url = reverse_lazy('role_list')

    def form_valid(self, form):
        messages.success(self.request, f'Role "{form.instance.title}" updated.')
        return super().form_valid(form)


class RoleDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        title = role.title
        role.delete()
        messages.success(request, f'Role "{title}" deleted.')
        return redirect('role_list')


class BulkUploadView(LoginRequiredMixin, FormView):
    form_class = BulkUploadForm
    template_name = 'recruitment/bulk_upload.html'
    success_url = reverse_lazy('candidate_list')

    def form_valid(self, form):
        uploaded = form.cleaned_data['file']
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            for chunk in uploaded.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            result = services.import_workbook(tmp_path, user=self.request.user)
        finally:
            os.unlink(tmp_path)
        messages.success(
            self.request,
            f"Imported {result['candidates_created']} candidates "
            f"({result['candidates_skipped']} already existed), "
            f"{result['roles_created']} new roles.",
        )
        return super().form_valid(form)


class BulkStatusUpdateView(LoginRequiredMixin, View):
    def post(self, request):
        form = BulkStatusForm(request.POST)
        next_url = request.POST.get('next') or reverse('candidate_list')
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect(next_url)
        count = services.bulk_change_status(
            form.cleaned_data['candidate_ids'], form.cleaned_data['new_status'], user=request.user
        )
        messages.success(request, f'Updated status for {count} candidate(s).')
        return redirect(next_url)
