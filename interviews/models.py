from django.conf import settings
from django.db import models
from django.urls import reverse

from candidates.models import Candidate


class Interview(models.Model):
    class RoundType(models.TextChoices):
        ROUND1 = 'ROUND1', 'Round 1'
        TECHNICAL = 'TECHNICAL', 'Technical'
        MANAGERIAL = 'MANAGERIAL', 'Managerial'
        FINAL = 'FINAL', 'Final'
        HR = 'HR', 'HR Round'

    class Mode(models.TextChoices):
        ONSITE = 'ONSITE', 'Onsite'
        PHONE = 'PHONE', 'Phone'
        VIDEO = 'VIDEO', 'Video'

    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        RESCHEDULED = 'RESCHEDULED', 'Rescheduled'

    class Result(models.TextChoices):
        PASS_ = 'PASS', 'Pass'
        FAIL = 'FAIL', 'Fail'
        PENDING = 'PENDING', 'Pending'

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='interviews')
    round_type = models.CharField(max_length=20, choices=RoundType.choices, default=RoundType.ROUND1)
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='interviews'
    )
    scheduled_date = models.DateTimeField()
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.VIDEO)
    meeting_link = models.URLField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    result = models.CharField(max_length=20, choices=Result.choices, default=Result.PENDING)
    feedback = models.TextField(blank=True, null=True)
    score = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['scheduled_date']

    def __str__(self):
        return f"{self.candidate.full_name} - {self.get_round_type_display()} on {self.scheduled_date:%Y-%m-%d %H:%M}"

    def get_absolute_url(self):
        return reverse('interview_detail', args=[self.pk])
