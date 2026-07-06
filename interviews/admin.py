from django.contrib import admin

from .models import Interview


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = (
        'candidate', 'round_type', 'interviewer', 'scheduled_date',
        'mode', 'status', 'result', 'score',
    )
    list_filter = ('round_type', 'mode', 'status', 'result', 'interviewer')
    search_fields = ('candidate__full_name', 'candidate__email')
    date_hierarchy = 'scheduled_date'
