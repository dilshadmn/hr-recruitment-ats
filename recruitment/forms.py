from django import forms

from .models import Candidate, Role


class BootstrapFormMixin:
    """Adds the Bootstrap 5 `form-control` / `form-select` / `form-check-input`
    classes to every field so templates don't need `{{ field }}|add_class` tags.
    """

    def _add_bootstrap_classes(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class CandidateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Candidate
        fields = [
            'full_name', 'email', 'phone', 'role', 'cv', 'source',
            'experience', 'notice_period', 'expected_salary', 'remarks',
        ]
        widgets = {
            'remarks': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].queryset = Role.objects.filter(is_active=True)
        self.fields['role'].required = False
        self._add_bootstrap_classes()


class RoleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Role
        fields = ['title', 'department', 'location', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


class BlacklistForm(BootstrapFormMixin, forms.Form):
    blacklist_reason = forms.CharField(
        label='Reason', widget=forms.Textarea(attrs={'rows': 3}), required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


class BulkUploadForm(BootstrapFormMixin, forms.Form):
    file = forms.FileField(label='Excel file (.xlsx)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()

    def clean_file(self):
        f = self.cleaned_data['file']
        if not f.name.lower().endswith('.xlsx'):
            raise forms.ValidationError('Please upload a .xlsx file.')
        return f


class BulkStatusForm(BootstrapFormMixin, forms.Form):
    candidate_ids = forms.CharField(widget=forms.HiddenInput)
    new_status = forms.ChoiceField(choices=Candidate.Status.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()

    def clean_candidate_ids(self):
        raw = self.cleaned_data['candidate_ids']
        ids = [v for v in raw.split(',') if v.strip()]
        if not ids:
            raise forms.ValidationError('Select at least one candidate.')
        return ids
