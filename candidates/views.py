import re
import uuid

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView, UpdateView

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
from .models import Candidate
from .permissions import ANY_STAFF, HIRING_MANAGER, HR_ADMIN, RECRUITER, GroupRequiredMixin

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

    def get_queryset(self):
        qs = Candidate.objects.select_related('job').all()
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
        ctx['tab'] = self.get_tab()
        ctx['tabs'] = REPOSITORY_TABS
        ctx['jobs'] = Job.objects.all()
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
        if self.require_reason and not reason:
            messages.error(request, 'A reason is required.')
            return redirect(request.POST.get('next') or reverse('candidate_timeline', args=[pk]))

        if self.target_status == STATUS.BLACKLISTED:
            services.blacklist_candidate(candidate, reason, user=request.user)
        else:
            services.change_status(candidate, self.target_status, user=request.user, remarks=reason or None)
        messages.success(request, f'{candidate.full_name} moved to "{candidate.get_status_display()}".')
        next_url = request.POST.get('next')
        return redirect(next_url or reverse('candidate_timeline', args=[pk]))


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
