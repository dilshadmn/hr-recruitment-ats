from django import forms

from .models import Interview


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


class InterviewForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Interview
        fields = ['round_type', 'interviewer', 'scheduled_date', 'mode', 'meeting_link']
        widgets = {
            'scheduled_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()


class InterviewResultForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Interview
        fields = ['status', 'result', 'score', 'feedback']
        widgets = {'feedback': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_bootstrap_classes()
