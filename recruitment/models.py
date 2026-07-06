from django.conf import settings
from django.db import models
from django.urls import reverse


class Role(models.Model):
    title = models.CharField(max_length=255)
    department = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('role_list')

    @property
    def open_candidate_count(self):
        return self.candidate_set.exclude(
            current_status__in=[Candidate.Status.REJECTED, Candidate.Status.BLACKLISTED]
        ).count()


class Candidate(models.Model):
    class Status(models.TextChoices):
        NEW = 'NEW', 'New'
        REAPPLY = 'REAPPLY', 'Reapply'
        UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
        SHORTLISTED = 'SHORTLISTED', 'Shortlisted'
        REJECTED = 'REJECTED', 'Rejected'
        BLACKLISTED = 'BLACKLISTED', 'Blacklisted'
        HIRED = 'HIRED', 'Hired'

    STATUS_CHOICES = Status.choices

    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, null=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    cv = models.FileField(upload_to='cvs/', blank=True, null=True)
    current_status = models.CharField(max_length=50, choices=STATUS_CHOICES, default=Status.NEW)
    source = models.CharField(max_length=255, blank=True, null=True)
    experience = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    notice_period = models.CharField(max_length=100, blank=True, null=True)
    expected_salary = models.CharField(max_length=100, blank=True, null=True)
    duplicate_flag = models.BooleanField(default=False)
    blacklist_reason = models.TextField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-applied_at']

    def __str__(self):
        return f"{self.full_name} ({self.email})"

    def get_absolute_url(self):
        return reverse('candidate_detail', args=[self.pk])


class CandidateStatusHistory(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='history')
    old_status = models.CharField(max_length=50, blank=True)
    new_status = models.CharField(max_length=50)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']
        verbose_name_plural = 'Candidate status histories'

    def __str__(self):
        return f"{self.candidate.full_name}: {self.old_status} -> {self.new_status}"
