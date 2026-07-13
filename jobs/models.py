from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Job(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        CLOSED = 'CLOSED', 'Closed'

    job_code = models.CharField(max_length=50, unique=True, blank=True)
    title = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    requirements = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_on = models.DateTimeField(auto_now_add=True)
    closing_date = models.DateField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    is_archived = models.BooleanField(default=False)
    openings = models.PositiveIntegerField(default=1, help_text='Number of positions to fill.')
    jd_file = models.FileField('Job Description', upload_to='jds/', blank=True, null=True)

    class Meta:
        ordering = ['-created_on']

    def __str__(self):
        return f"{self.job_code} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.job_code:
            self.job_code = f"JOB-{timezone.now():%y%m}-{Job.objects.count() + 1:04d}"
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('vacancy_detail', args=[self.job_code])

    @property
    def is_open(self):
        return self.status == self.Status.OPEN and not self.is_archived
