import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse

from jobs.models import Job


def candidate_resume_path(instance, filename):
    """cvs/<job_id>/<candidate_code>/resume.<ext> - matches the Blob Storage
    layout the design calls for; swapping DEFAULT_FILE_STORAGE to Azure Blob
    later needs no change here."""
    ext = filename.rsplit('.', 1)[-1] if '.' in filename else 'pdf'
    job_part = instance.job_id or 'general'
    return f"cvs/{job_part}/{instance.candidate_code}/resume.{ext}"


class Candidate(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        SHORTLISTED = 'SHORTLISTED', 'Shortlisted'
        ROUND1 = 'ROUND1', 'Round 1'
        INTERVIEW = 'INTERVIEW', 'Interview'
        FINAL_SELECTION = 'FINAL_SELECTION', 'Final Selection'
        HIRED = 'HIRED', 'Hired'
        REJECTED = 'REJECTED', 'Rejected'
        BLACKLISTED = 'BLACKLISTED', 'Blacklisted'

    candidate_code = models.CharField(max_length=20, unique=True, blank=True)
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, blank=True, related_name='candidates')

    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    current_location = models.CharField(max_length=255, blank=True, null=True)

    qualification = models.CharField('Last Education', max_length=255, blank=True, null=True)
    institution = models.CharField('Last Institution', max_length=255, blank=True, null=True)
    last_role = models.CharField(max_length=255, blank=True, null=True)
    last_company = models.CharField(max_length=255, blank=True, null=True)
    total_experience_years = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    skills = models.TextField(blank=True, null=True)

    linkedin = models.URLField(blank=True, null=True)
    portfolio_url = models.URLField(blank=True, null=True)
    notice_period = models.CharField(max_length=100, blank=True, null=True)
    expected_salary = models.CharField(max_length=100, blank=True, null=True)
    current_salary = models.CharField(max_length=100, blank=True, null=True)

    status = models.CharField(max_length=30, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(max_length=255, blank=True, null=True)
    resume_blob_url = models.FileField('Resume', upload_to=candidate_resume_path, blank=True, null=True)

    is_duplicate = models.BooleanField(default=False)
    is_blacklisted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.full_name} ({self.email})"

    def save(self, *args, **kwargs):
        if not self.candidate_code:
            self.candidate_code = f"CAND-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('candidate_detail', args=[self.pk])


class CandidateEducation(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='education')
    qualification = models.CharField(max_length=255)
    institution = models.CharField(max_length=255, blank=True, null=True)
    year_completed = models.PositiveIntegerField(blank=True, null=True)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    specialization = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ['-year_completed']

    def __str__(self):
        return f"{self.qualification} - {self.institution or ''}"


class CandidateExperience(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='experience_set')
    company_name = models.CharField(max_length=255)
    designation = models.CharField(max_length=255, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    total_experience = models.DecimalField(max_digits=5, decimal_places=1, blank=True, null=True)
    skills = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.designation or ''} @ {self.company_name}"


class CandidateStatusHistory(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='history')
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']
        verbose_name_plural = 'Candidate status histories'

    def __str__(self):
        return f"{self.candidate.full_name}: {self.old_status} -> {self.new_status}"


class Blacklist(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='blacklist_entries')
    reason = models.TextField()
    blacklisted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    blacklisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-blacklisted_at']

    def __str__(self):
        return f"{self.candidate.full_name} blacklisted on {self.blacklisted_at:%Y-%m-%d}"


class EmailRegistry(models.Model):
    """Fast duplicate-detection lookup: one row per unique applicant email."""
    email = models.EmailField(unique=True)
    first_candidate = models.ForeignKey(
        Candidate, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    application_count = models.PositiveIntegerField(default=1)
    last_applied_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.email} ({self.application_count} applications)"


class Note(models.Model):
    """Free-text HR notes on a candidate, e.g. "Strong communication,
    salary expectation high"."""
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.candidate.full_name} by {self.author}"


class CommunicationLog(models.Model):
    class Channel(models.TextChoices):
        EMAIL = 'EMAIL', 'Email'
        PHONE = 'PHONE', 'Phone'
        OTHER = 'OTHER', 'Other'

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='communication_logs')
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.EMAIL)
    subject = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    logged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-logged_at']

    def __str__(self):
        return f"{self.get_channel_display()} with {self.candidate.full_name} on {self.logged_at:%Y-%m-%d}"


class Attachment(models.Model):
    """Extra documents beyond the resume (ID proof, certificates, etc.)."""
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='attachments/')
    label = models.CharField(max_length=255, blank=True, null=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.label or self.file.name


class Offer(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        DECLINED = 'DECLINED', 'Declined'

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='offers')
    offer_letter = models.FileField(upload_to='offers/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Offer for {self.candidate.full_name} ({self.get_status_display()})"
