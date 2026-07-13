import re
import uuid

from django.contrib import messages
from django.db.models import Max, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, UpdateView

from interviews.models import Interview
from jobs.models import Job

from . import services
from .forms import (
    BulkUploadForm,
    CandidateApplicationForm,
    CandidateNoteForm,
    CommunicationLogForm,
    EducationFormSet,
    ExperienceFormSet,
)
from .models import Candidate, CandidateStatusHistory, Note
from .permissions import ANY_STAFF, HIRING_MANAGER, HR_ADMIN, RECRUITER, GroupRequiredMixin


def _performed_by(request):
    """Free-text 'Done by' from the action form, defaulting to the logged-in user."""
    return (request.POST.get('performed_by', '').strip()
            or request.user.get_full_name() or request.user.get_username())

STATUS = Candidate.Status

REPOSITORY_TABS = [
    ('open', 'Open Applications', STATUS.OPEN),
    ('shortlisted', 'Shortlisted', STATUS.SHORTLISTED),
    ('round1', 'Round 1', STATUS.ROUND1),
    ('interview', 'Interview', STATUS.INTERVIEW),
    ('final_selection', 'Final Selection', STATUS.FINAL_SELECTION),
    ('hired', 'Hired', STATUS.HIRED),
    ('rejected', 'Rejected', STATUS.REJECTED),
    ('blacklisted', 'Blacklisted', STATUS.BLACKLISTED),
]
TAB_STATUS_MAP = {key: status for key, _, status in REPOSITORY_TABS}


class ApplicationCreateView(View):
    template_name = 'candidates/application_form.html'

    def get_job(self, job_code):
        return get_object_or_404(Job, job_code=job_code, status=Job.Status.OPEN, is_archived=False)

    def get(self, request, job_code):
        job = self.get_job(job_code)
        context = {
            'job': job,
            'form': CandidateApplicationForm(),
            'education_formset': EducationFormSet(prefix='edu'),
            'experience_formset': ExperienceFormSet(prefix='exp'),
        }
        return render(request, self.template_name, context)

    def post(self, request, job_code):
        job = self.get_job(job_code)
        form = CandidateApplicationForm(request.POST, request.FILES)
        education_formset = EducationFormSet(request.POST, prefix='edu')
        experience_formset = ExperienceFormSet(request.POST, prefix='exp')

        if form.is_valid() and education_formset.is_valid() and experience_formset.is_valid():
            candidate = form.save(commit=False)
            candidate.job = job
            candidate.source = candidate.source or 'Careers Portal'
            services.submit_application(candidate)

            education_formset.instance = candidate
            education_formset.save()
            experience_formset.instance = candidate
            experience_formset.save()

            return redirect('application_thank_you', candidate_code=candidate.candidate_code)

        return render(request, self.template_name, {
            'job': job,
            'form': form,
            'education_formset': education_formset,
            'experience_formset': experience_formset,
        })


class ApplicationThankYouView(DetailView):
    model = Candidate
    slug_field = 'candidate_code'
    slug_url_kwarg = 'candidate_code'
    context_object_name = 'candidate'
    template_name = 'candidates/thank_you.html'


# ---------------------------------------------------------------------------
# HR admin: Candidate Repository
# ---------------------------------------------------------------------------


class CandidateRepositoryListView(GroupRequiredMixin, ListView):
    model = Candidate
    template_name = 'candidates/repository.html'
    context_object_name = 'candidates'
    allowed_groups = ANY_STAFF

    def get_tab(self):
        return self.request.GET.get('tab', 'open')

    def _apply_flow(self, qs, flow):
        from .flows import flow_filter
        return flow_filter(qs, flow)

    def get_queryset(self):
        last_action = (CandidateStatusHistory.objects
                       .filter(candidate=OuterRef('pk')).order_by('-changed_at', '-id')
                       .values('changed_at')[:1])
        next_interview = (Interview.objects
                          .filter(candidate=OuterRef('pk')).order_by('-scheduled_date')
                          .values('scheduled_date')[:1])
        qs = (Candidate.objects.select_related('job')
              .annotate(last_action_at=Subquery(last_action),
                        interview_at=Subquery(next_interview)))

        # A "flow" link (from the dashboard Overview) filters by a derived stage
        # set and overrides the normal current-status tab filter.
        flow = self.request.GET.get('flow')
        if flow:
            qs = self._apply_flow(qs, flow)
        else:
            status = TAB_STATUS_MAP.get(self.get_tab())
            if status is not None:
                qs = qs.filter(status=status)

        job_id = self.request.GET.get('job')
        if job_id:
            qs = qs.filter(job_id=job_id)

        skill = self.request.GET.get('skill')
        if skill:
            qs = qs.filter(skills__icontains=skill)

        min_experience = self.request.GET.get('min_experience')
        if min_experience:
            qs = qs.filter(total_experience_years__gte=min_experience)

        date_from = self.request.GET.get('date_from')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = self.request.GET.get('date_to')
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # A flow view isn't a single status, so don't highlight/act on a tab.
        ctx['tab'] = 'all' if self.request.GET.get('flow') else self.get_tab()
        ctx['flow'] = self.request.GET.get('flow', '')
        ctx['tabs'] = REPOSITORY_TABS
        ctx['jobs'] = Job.objects.all()
        u = self.request.user
        ctx['is_hr_admin'] = u.is_superuser or u.groups.filter(name=HR_ADMIN).exists()
        return ctx


class CandidateTimelineView(GroupRequiredMixin, DetailView):
    model = Candidate
    template_name = 'candidates/timeline.html'
    context_object_name = 'candidate'
    allowed_groups = ANY_STAFF

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        candidate = self.object
        ctx['history'] = candidate.history.select_related('changed_by').all()
        ctx['notes'] = candidate.notes.select_related('author').all()
        ctx['communication_logs'] = candidate.communication_logs.select_related('logged_by').all()
        ctx['attachments'] = candidate.attachments.all()
        ctx['offers'] = candidate.offers.all()
        ctx['interviews'] = candidate.interviews.select_related('interviewer').all()
        ctx['note_form'] = CandidateNoteForm()
        ctx['comm_form'] = CommunicationLogForm()

        stage_dates = {}
        for h in ctx['history'].order_by('changed_at'):
            stage_dates.setdefault(h.new_status, h.changed_at)
        ctx['stage_dates'] = stage_dates

        # Unified activity feed: every action (status changes, notes, calls,
        # interviews, offers) in one chronological list with remarks.
        labels = dict(Candidate.Status.choices)
        events = []
        for h in ctx['history']:
            events.append({
                'when': h.changed_at, 'icon': 'arrow-right-circle',
                'title': f"Status: {labels.get(h.old_status, h.old_status or '—')} → {labels.get(h.new_status, h.new_status)}",
                'detail': h.remarks, 'who': h.performed_by or h.changed_by})
        for n in ctx['notes']:
            events.append({'when': n.created_at, 'icon': 'sticky',
                           'title': 'Note added', 'detail': n.text, 'who': n.author})
        for l in ctx['communication_logs']:
            title = l.get_channel_display() + (f": {l.subject}" if l.subject else " logged")
            events.append({'when': l.logged_at, 'icon': 'telephone',
                           'title': title, 'detail': l.message, 'who': l.logged_by})
        for i in ctx['interviews']:
            events.append({
                'when': i.scheduled_date, 'icon': 'calendar-event',
                'title': f"{i.get_round_type_display()} interview — {i.get_status_display()} / {i.get_result_display()}",
                'detail': i.feedback, 'who': i.interviewer or i.created_by})
        for o in ctx['offers']:
            events.append({'when': o.sent_at or o.created_at, 'icon': 'file-earmark-text',
                           'title': f"Offer {o.get_status_display()}", 'detail': None, 'who': o.created_by})
        events.sort(key=lambda e: e['when'], reverse=True)
        ctx['activity'] = events

        u = self.request.user
        ctx['is_hr_admin'] = u.is_superuser or u.groups.filter(name=HR_ADMIN).exists()
        ctx['can_revert'] = ctx['is_hr_admin'] or u.groups.filter(name=RECRUITER).exists()
        ctx['all_jobs'] = Job.objects.all().order_by('title')
        return ctx


class CandidateUpdateView(GroupRequiredMixin, UpdateView):
    model = Candidate
    form_class = CandidateApplicationForm
    template_name = 'candidates/candidate_form.html'
    allowed_groups = (HR_ADMIN, RECRUITER)

    def form_valid(self, form):
        messages.success(self.request, f'{form.instance.full_name} updated.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('candidate_timeline', args=[self.object.pk])


class CandidateChangeJobView(GroupRequiredMixin, View):
    """Manually re-map a candidate to a different vacancy (e.g. move a
    'General Application' to a specific opening)."""
    allowed_groups = (HR_ADMIN, RECRUITER, HIRING_MANAGER)

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        old = candidate.job.title if candidate.job else 'None'
        job_id = request.POST.get('job') or None
        candidate.job = get_object_or_404(Job, pk=job_id) if job_id else None
        candidate.save(update_fields=['job', 'updated_at'])
        new = candidate.job.title if candidate.job else 'None'
        if old != new:
            Note.objects.create(candidate=candidate, author=request.user,
                                text=f'Vacancy changed: {old} -> {new}')
            messages.success(request, f'Vacancy updated to "{new}".')
        return redirect('candidate_timeline', pk=pk)


class AddNoteView(GroupRequiredMixin, View):
    allowed_groups = ANY_STAFF

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        form = CandidateNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.candidate = candidate
            note.author = request.user
            note.save()
            messages.success(request, 'Note added.')
        return redirect('candidate_timeline', pk=pk)


class AddCommunicationLogView(GroupRequiredMixin, View):
    allowed_groups = ANY_STAFF

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        form = CommunicationLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.candidate = candidate
            log.logged_by = request.user
            log.save()
            messages.success(request, 'Communication logged.')
        return redirect('candidate_timeline', pk=pk)


class CandidateStatusActionView(GroupRequiredMixin, View):
    """Generic POST-only status transition for the Candidate Repository
    workflow (Open -> Shortlisted -> Round1 -> Interview -> FinalSelection
    -> Hired, with Reject/Blacklist available from any stage)."""
    target_status = None
    require_reason = False
    allowed_groups = (HR_ADMIN, RECRUITER, HIRING_MANAGER)

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        reason = request.POST.get('reason', '').strip()
        performed_by = _performed_by(request)
        if self.require_reason and not reason:
            messages.error(request, 'A reason is required.')
            return redirect(request.POST.get('next') or reverse('candidate_timeline', args=[pk]))

        if self.target_status == STATUS.BLACKLISTED:
            services.blacklist_candidate(candidate, reason, user=request.user, performed_by=performed_by)
        else:
            services.change_status(candidate, self.target_status, user=request.user,
                                   remarks=reason or None, performed_by=performed_by)
        messages.success(request, f'{candidate.full_name} moved to "{candidate.get_status_display()}".')
        next_url = request.POST.get('next')
        return redirect(next_url or reverse('candidate_timeline', args=[pk]))


class CandidateRevertLastActionView(GroupRequiredMixin, View):
    """Undo the most recent status change, restoring the previous status and
    logging the reversal (for accidental clicks)."""
    allowed_groups = (HR_ADMIN, RECRUITER)

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        last = candidate.history.order_by('-changed_at', '-id').first()
        next_url = request.POST.get('next') or reverse('candidate_timeline', args=[pk])
        if not last or not last.old_status:
            messages.error(request, 'There is no previous status to revert to.')
            return redirect(next_url)
        labels = dict(Candidate.Status.choices)
        note = (f'Reverted accidental change '
                f'({labels.get(last.new_status, last.new_status)} -> '
                f'{labels.get(last.old_status, last.old_status)}).')
        services.change_status(candidate, last.old_status, user=request.user,
                               remarks=note, performed_by=_performed_by(request))
        messages.success(request, f'Reverted {candidate.full_name} to "{candidate.get_status_display()}".')
        return redirect(next_url)


class CandidateDeleteView(GroupRequiredMixin, View):
    """Permanently delete a candidate and all their related records (HR Admin only)."""
    allowed_groups = (HR_ADMIN,)

    def post(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        name = candidate.full_name
        candidate.delete()
        messages.success(request, f'Candidate "{name}" and all their records were deleted.')
        next_url = request.POST.get('next')
        if next_url and f'/candidates/{pk}/' in next_url:
            next_url = None  # came from the deleted candidate's own page
        return redirect(next_url or reverse('candidate_repository'))


class BulkRejectClosedVacanciesView(GroupRequiredMixin, View):
    """Move every still-active candidate under a CLOSED vacancy to Rejected.
    Hired and already-terminal candidates are left untouched."""
    allowed_groups = (HR_ADMIN,)
    ACTIVE = (STATUS.OPEN, STATUS.SHORTLISTED, STATUS.ROUND1, STATUS.INTERVIEW, STATUS.FINAL_SELECTION)

    def post(self, request):
        performed_by = _performed_by(request)
        cands = list(Candidate.objects.filter(
            job__status=Job.Status.CLOSED, status__in=self.ACTIVE).select_related('job'))
        history = [CandidateStatusHistory(
            candidate=c, old_status=c.status, new_status=STATUS.REJECTED,
            changed_by=request.user, performed_by=performed_by,
            remarks=f'Auto-rejected: vacancy "{c.job.title}" is closed.') for c in cands]
        Candidate.objects.filter(pk__in=[c.pk for c in cands]).update(
            status=STATUS.REJECTED, updated_at=timezone.now())
        CandidateStatusHistory.objects.bulk_create(history, batch_size=100)
        messages.success(request, f'{len(cands)} candidate(s) in closed vacancies moved to Rejected.')
        return redirect('job_manage_list')


# ---------------------------------------------------------------------------
# HR admin: Bulk Upload CV
# ---------------------------------------------------------------------------


def _name_from_filename(filename):
    stem = filename.rsplit('.', 1)[0]
    stem = re.sub(r'[_\-\.]+', ' ', stem)
    stem = re.sub(r'\b(cv|resume)\b', '', stem, flags=re.IGNORECASE).strip()
    return stem.title() or 'Unnamed Candidate'


class BulkUploadCVView(GroupRequiredMixin, View):
    """Step 1: select vacancy + source, upload multiple CVs. Creates one
    draft Candidate per file (name guessed from the filename - no resume
    parsing is wired up here, see README) and redirects to the review step
    where HR edits/confirms each row."""
    template_name = 'candidates/bulk_upload.html'
    allowed_groups = (HR_ADMIN, RECRUITER)

    def get(self, request):
        return render(request, self.template_name, {'form': BulkUploadForm()})

    def post(self, request):
        form = BulkUploadForm(request.POST)
        files = request.FILES.getlist('cvs')
        if not files:
            messages.error(request, 'Select at least one CV file to upload.')
        if form.is_valid() and files:
            job = form.cleaned_data['job']
            source = form.cleaned_data['source']
            created_ids = []
            for f in files:
                candidate = Candidate(
                    full_name=_name_from_filename(f.name),
                    email=f"pending-{uuid.uuid4().hex[:12]}@placeholder.local",
                    job=job,
                    source=source,
                    status=STATUS.OPEN,
                    resume_blob_url=f,
                )
                candidate.save()
                services.record_creation(candidate, user=request.user, remarks='Created via Bulk Upload CV')
                created_ids.append(candidate.pk)
            messages.success(request, f'{len(created_ids)} candidate(s) created. Please review and edit their details below.')
            ids_param = ','.join(str(i) for i in created_ids)
            return redirect(f"{reverse('candidate_bulk_review')}?ids={ids_param}")
        return render(request, self.template_name, {'form': form})


class BulkReviewListView(GroupRequiredMixin, ListView):
    """Step 2: Edit Data / Confirm - lists the batch just created so HR can
    fix the auto-guessed names/emails before the rows enter the normal
    Candidate Repository workflow."""
    template_name = 'candidates/bulk_review.html'
    context_object_name = 'candidates'
    allowed_groups = (HR_ADMIN, RECRUITER)

    def get_queryset(self):
        ids = [i for i in self.request.GET.get('ids', '').split(',') if i]
        return Candidate.objects.filter(pk__in=ids)
