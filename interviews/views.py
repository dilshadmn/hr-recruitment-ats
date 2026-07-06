from django.contrib import messages
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from candidates.models import Candidate
from candidates.permissions import ANY_STAFF, HR_ADMIN, INTERVIEWER, RECRUITER, GroupRequiredMixin

from .forms import InterviewForm, InterviewResultForm
from .models import Interview


class InterviewSchedulerListView(GroupRequiredMixin, ListView):
    """Agenda-style 'calendar view': all interviews grouped by date,
    filterable by interviewer/status/date range."""
    model = Interview
    template_name = 'interviews/scheduler.html'
    context_object_name = 'interviews'
    allowed_groups = ANY_STAFF

    def get_queryset(self):
        qs = Interview.objects.select_related('candidate', 'interviewer').all()
        interviewer_id = self.request.GET.get('interviewer')
        if interviewer_id:
            qs = qs.filter(interviewer_id=interviewer_id)
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        date_from = self.request.GET.get('date_from')
        if date_from:
            qs = qs.filter(scheduled_date__date__gte=date_from)
        date_to = self.request.GET.get('date_to')
        if date_to:
            qs = qs.filter(scheduled_date__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['interviewers'] = User.objects.filter(groups__name=INTERVIEWER).distinct()
        ctx['status_choices'] = Interview.Status.choices
        return ctx


class InterviewScheduleView(GroupRequiredMixin, CreateView):
    model = Interview
    form_class = InterviewForm
    template_name = 'interviews/interview_form.html'
    allowed_groups = (HR_ADMIN, RECRUITER)

    def dispatch(self, request, *args, **kwargs):
        self.candidate = get_object_or_404(Candidate, pk=kwargs['candidate_id'])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['candidate'] = self.candidate
        return ctx

    def form_valid(self, form):
        form.instance.candidate = self.candidate
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Interview scheduled for {self.candidate.full_name}.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('candidate_timeline', args=[self.candidate.pk])


class InterviewRescheduleView(GroupRequiredMixin, UpdateView):
    model = Interview
    form_class = InterviewForm
    template_name = 'interviews/interview_form.html'
    allowed_groups = (HR_ADMIN, RECRUITER)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['candidate'] = self.object.candidate
        return ctx

    def form_valid(self, form):
        form.instance.status = Interview.Status.RESCHEDULED
        messages.success(self.request, 'Interview rescheduled.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('candidate_timeline', args=[self.object.candidate_id])


class InterviewResultView(GroupRequiredMixin, UpdateView):
    model = Interview
    form_class = InterviewResultForm
    template_name = 'interviews/interview_result_form.html'
    allowed_groups = (HR_ADMIN, INTERVIEWER)

    def form_valid(self, form):
        messages.success(self.request, 'Interview result recorded.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('candidate_timeline', args=[self.object.candidate_id])


class InterviewSendInviteView(GroupRequiredMixin, View):
    """Sends the invite via Django's configured email backend (console
    backend in dev - see settings.EMAIL_BACKEND). Wire up real SMTP
    settings in production to actually deliver these."""
    allowed_groups = (HR_ADMIN, RECRUITER)

    def post(self, request, pk):
        interview = get_object_or_404(Interview, pk=pk)
        candidate = interview.candidate
        if candidate.email:
            send_mail(
                subject=f'Interview Invitation - {interview.get_round_type_display()}',
                message=(
                    f"Dear {candidate.full_name},\n\n"
                    f"You are invited for a {interview.get_round_type_display()} interview on "
                    f"{interview.scheduled_date:%d %b %Y %H:%M} ({interview.get_mode_display()}).\n"
                    f"{'Meeting link: ' + interview.meeting_link if interview.meeting_link else ''}\n\n"
                    f"Regards,\nHR Team"
                ),
                from_email=None,
                recipient_list=[candidate.email],
                fail_silently=True,
            )
        messages.success(request, f'Invite sent to {candidate.email}.')
        return redirect('candidate_timeline', pk=candidate.pk)
