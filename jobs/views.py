from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView

from .models import Job


class VacancyListView(ListView):
    model = Job
    template_name = 'jobs/vacancy_list.html'
    context_object_name = 'jobs'

    def get_queryset(self):
        return Job.objects.filter(status=Job.Status.OPEN, is_archived=False)


class VacancyDetailView(DetailView):
    model = Job
    context_object_name = 'job'
    slug_field = 'job_code'
    slug_url_kwarg = 'job_code'

    def get_queryset(self):
        return Job.objects.all()

    def get_template_names(self):
        if self.request.GET.get('partial') == '1' or self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return ['jobs/_vacancy_detail_content.html']
        return ['jobs/vacancy_detail.html']
