from django import forms
from django.forms import inlineformset_factory

from jobs.models import Job

from .models import Candidate, CandidateEducation, CandidateExperience, CommunicationLog, Note


class BootstrapFormMixin:
    def _add_bootstrap_classes(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class CandidateApplicationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Candidate
        fields = [
            'full_name', 'email', 'phone', 'dob', 'current_location',
            'qualification', 'institution', 'last_role', 'last_company',
            'total_experience_years', 'skills',
            'linkedin', 'portfolio_url', 'notice_period', 'expected_salary',
            'current_salary', 'resume_blob_url',
        ]
        labels = {
            'qualification': 'Highest Qualification',
            'institution': 'Institution',
            'resume_blob_url': 'Resume (PDF/DOC)',
            'skills': 'Key Skills',
        }
        widgets = {
            'dob': forms.DateInput(attrs={'type': 'date'}),
            'skills': forms.Textarea(attrs={'rows': 2, 'placeholder': 'e.g. Python, SQL, Excel'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['resume_blob_url'].required = True
        self._add_bootstrap_classes()


class CandidateEducationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CandidateEducation
        fields = ['qualification', 'institution', 'year_completed', 'percentage', 'specialization']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


class CandidateExperienceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CandidateExperience
        fields = ['company_name', 'designation', 'start_date', 'end_date', 'total_experience', 'skills']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


class CandidateNoteForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Note
        fields = ['text']
        widgets = {'text': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Add a note about this candidate...'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


class CommunicationLogForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CommunicationLog
        fields = ['channel', 'subject', 'message']
        widgets = {'message': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


class BulkUploadForm(BootstrapFormMixin, forms.Form):
    job = forms.ModelChoiceField(queryset=Job.objects.filter(status=Job.Status.OPEN), label='Vacancy')
    source = forms.ChoiceField(choices=[
        ('Careers Portal', 'Careers Portal'), ('Referral', 'Referral'), ('LinkedIn', 'LinkedIn'),
        ('Naukri', 'Naukri'), ('Agency', 'Agency'), ('Other', 'Other'),
    ])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


EducationFormSet = inlineformset_factory(
    Candidate, CandidateEducation, form=CandidateEducationForm,
    extra=1, can_delete=True,
)

ExperienceFormSet = inlineformset_factory(
    Candidate, CandidateExperience, form=CandidateExperienceForm,
    extra=1, can_delete=True,
)
