from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.utils import timezone
from django.views.generic import TemplateView

from candidates.models import Candidate, CandidateStatusHistory
from candidates.permissions import ANY_STAFF, GroupRequiredMixin
from interviews.models import Interview
from jobs.models import Job

STATUS = Candidate.Status


class HRDashboardView(GroupRequiredMixin, TemplateView):
    template_name = 'dashboard/dashboard.html'
    allowed_groups = ANY_STAFF

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['kpis_display'] = [
            ('Open Vacancies', Job.objects.filter(status=Job.Status.OPEN, is_archived=False).count()),
            ('Total Applicants', Candidate.objects.count()),
            ('New Applicants', Candidate.objects.filter(status=STATUS.OPEN).count()),
            ('Shortlisted', Candidate.objects.filter(status=STATUS.SHORTLISTED).count()),
            ('Interviews Scheduled', Interview.objects.filter(status=Interview.Status.SCHEDULED).count()),
            ('Hired', Candidate.objects.filter(status=STATUS.HIRED).count()),
            ('Rejected', Candidate.objects.filter(status=STATUS.REJECTED).count()),
            ('Blacklisted', Candidate.objects.filter(status=STATUS.BLACKLISTED).count()),
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

        total = Candidate.objects.count()
        hired = Candidate.objects.filter(status=STATUS.HIRED).count()
        rejected = Candidate.objects.filter(status=STATUS.REJECTED).count()

        ctx['rejection_ratio'] = round(rejected / total * 100, 1) if total else 0

        total_jobs = Job.objects.count()
        jobs_with_hire = Job.objects.filter(candidates__status=STATUS.HIRED).distinct().count()
        ctx['fill_rate'] = round(jobs_with_hire / total_jobs * 100, 1) if total_jobs else 0

        hire_durations = (
            CandidateStatusHistory.objects.filter(new_status=STATUS.HIRED)
            .annotate(duration=ExpressionWrapper(F('changed_at') - F('candidate__created_at'), output_field=DurationField()))
            .aggregate(avg=Avg('duration'))
        )
        avg_duration = hire_durations['avg']
        ctx['avg_time_to_hire_days'] = round(avg_duration.total_seconds() / 86400, 1) if avg_duration else None

        ctx['source_effectiveness'] = (
            Candidate.objects.exclude(source__isnull=True).exclude(source='')
            .values('source')
            .annotate(total=Count('id'), hired=Count('id', filter=Q(status=STATUS.HIRED)))
            .order_by('-total')
        )
        return ctx
