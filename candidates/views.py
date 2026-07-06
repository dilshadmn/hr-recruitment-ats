from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView

from jobs.models import Job

from . import services
from .forms import CandidateApplicationForm, EducationFormSet, ExperienceFormSet
from .models import Candidate


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
