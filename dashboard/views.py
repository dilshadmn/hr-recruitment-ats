from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.utils import timezone
from django.views.generic import TemplateView

from candidates.models import Candidate, CandidateStatusHistory
from candidates.permissions import ANY_STAFF, GroupRequiredMixin
from interviews.models import Interview
from jobs.models import Job

STATUS = Candidate.Status


def _summary_counts_qs(qs):
    """Total / Open / Shortlisted / Rejected for a candidate queryset (one query)."""
    return qs.aggregate(
        total=Count('id'),
        open=Count('id', filter=Q(status=STATUS.OPEN)),
        shortlisted=Count('id', filter=Q(status=STATUS.SHORTLISTED)),
        rejected=Count('id', filter=Q(status=STATUS.REJECTED)),
    )


class HRDashboardView(GroupRequiredMixin, TemplateView):
    template_name = 'dashboard/dashboard.html'
    allowed_groups = ANY_STAFF

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job_id = self.request.GET.get('job') or ''
        base = Candidate.objects.all()
        if job_id:
            base = base.filter(job_id=job_id)

        ctx['jobs'] = Job.objects.all().order_by('title')
        ctx['selected_job'] = job_id
        ctx['view'] = self.request.GET.get('view', 'summary')

        # ---------- Summary ----------
        ctx['summary'] = _summary_counts_qs(base)
        ctx['by_job'] = (base.values('job__title')
                         .annotate(total=Count('id'),
                                   open=Count('id', filter=Q(status=STATUS.OPEN)),
                                   shortlisted=Count('id', filter=Q(status=STATUS.SHORTLISTED)),
                                   rejected=Count('id', filter=Q(status=STATUS.REJECTED)))
                         .order_by('-total'))
        ctx['by_source'] = (base.exclude(source__isnull=True).exclude(source='')
                            .values('source')
                            .annotate(total=Count('id'),
                                      open=Count('id', filter=Q(status=STATUS.OPEN)),
                                      shortlisted=Count('id', filter=Q(status=STATUS.SHORTLISTED)),
                                      rejected=Count('id', filter=Q(status=STATUS.REJECTED)))
                            .order_by('-total'))

        # ---------- Overview (stage flow, from history + interviews, not just
        # current status). Each item: (label, value, repository-tab or None) ----------
        R1 = Interview.RoundType.ROUND1
        PASS = Interview.Result.PASS_
        SCHED = Interview.Status.SCHEDULED
        NON_R1 = [t for t, _ in Interview.RoundType.choices if t != R1]

        def cnt(qs):
            return qs.distinct().count()

        ctx['overview'] = [
            ('Total Applicants', base.count(), None),
            ('Open', base.filter(status=STATUS.OPEN).count(), 'open'),
            ('Shortlisted', cnt(base.filter(history__new_status=STATUS.SHORTLISTED)), 'shortlisted'),
            ('Call Pending', cnt(base.filter(status=STATUS.SHORTLISTED, communication_logs__isnull=True)), 'shortlisted'),
            ('Round 1 Pending', base.filter(status=STATUS.ROUND1).count(), 'round1'),
            ('Round 1 Cleared', cnt(base.filter(interviews__round_type=R1, interviews__result=PASS)), None),
            ('Interview Pending', cnt(base.filter(status=STATUS.INTERVIEW).exclude(interviews__status=SCHED)), 'interview'),
            ('Interview Scheduled', cnt(base.filter(interviews__status=SCHED)), 'interview'),
            ('Interview Cleared', cnt(base.filter(interviews__result=PASS, interviews__round_type__in=NON_R1)), None),
            ('Final Selection Pending', base.filter(status=STATUS.FINAL_SELECTION).count(), 'final_selection'),
            ('Hired', base.filter(status=STATUS.HIRED).count(), 'hired'),
            ('Rejected', base.filter(status=STATUS.REJECTED).count(), 'rejected'),
            ('Blacklisted', base.filter(status=STATUS.BLACKLISTED).count(), 'blacklisted'),
        ]

        ctx['upcoming_interviews'] = Interview.objects.select_related('candidate', 'interviewer').filter(
            status=Interview.Status.SCHEDULED, scheduled_date__gte=timezone.now()
        ).order_by('scheduled_date')[:10]
        return ctx


class ReportsView(GroupRequiredMixin, TemplateView):
    template_name = 'dashboard/reports.html'
    allowed_groups = ANY_STAFF

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job_id = self.request.GET.get('job') or ''
        base = Candidate.objects.all()
        if job_id:
            base = base.filter(job_id=job_id)
        ctx['jobs'] = Job.objects.all().order_by('title')
        ctx['selected_job'] = job_id

        total = base.count()
        rejected = base.filter(status=STATUS.REJECTED).count()
        ctx['rejection_ratio'] = round(rejected / total * 100, 1) if total else 0

        jobs_qs = Job.objects.filter(pk=job_id) if job_id else Job.objects.all()
        total_jobs = jobs_qs.count()
        jobs_with_hire = jobs_qs.filter(candidates__status=STATUS.HIRED).distinct().count()
        ctx['fill_rate'] = round(jobs_with_hire / total_jobs * 100, 1) if total_jobs else 0

        hire_hist = CandidateStatusHistory.objects.filter(new_status=STATUS.HIRED)
        if job_id:
            hire_hist = hire_hist.filter(candidate__job_id=job_id)
        avg_duration = (
            hire_hist.annotate(duration=ExpressionWrapper(
                F('changed_at') - F('candidate__created_at'), output_field=DurationField()))
            .aggregate(avg=Avg('duration'))['avg']
        )
        ctx['avg_time_to_hire_days'] = round(avg_duration.total_seconds() / 86400, 1) if avg_duration else None

        # Source effectiveness: total, shortlisted (%), hired (conversion %).
        # distinct=True keeps counts correct despite the history join.
        rows = (base.exclude(source__isnull=True).exclude(source='')
                .values('source')
                .annotate(total=Count('id', distinct=True),
                          shortlisted=Count('id', filter=Q(history__new_status=STATUS.SHORTLISTED), distinct=True),
                          hired=Count('id', filter=Q(status=STATUS.HIRED), distinct=True))
                .order_by('-total'))
        data = []
        for r in rows:
            t = r['total'] or 0
            data.append({**r,
                         'shortlist_pct': round(r['shortlisted'] / t * 100, 1) if t else 0,
                         'conversion_pct': round(r['hired'] / t * 100, 1) if t else 0})
        ctx['source_effectiveness'] = data
        return ctx
